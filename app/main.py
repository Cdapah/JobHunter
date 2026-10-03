import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from .config import settings
from .collectors import enabled_source_names
from .database import Base, engine, get_db
from .emailer import send_test_email
from .models import Job, JobMatch, SearchRun, SourceRun
from .services import run_collection, send_daily_digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
scheduler = BackgroundScheduler(timezone="Europe/Paris")

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    scheduler.add_job(run_collection, "interval", minutes=settings.search_interval_minutes, id="collect", max_instances=1, coalesce=True, next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(send_daily_digest, "cron", hour=18, minute=0, id="daily_digest", max_instances=1, coalesce=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="JobHunter", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

@app.get("/")
def dashboard(request: Request, min_score: int = 0, status: str = "", message: str = "", db: Session = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_job_age_hours)
    freshness = func.coalesce(Job.published_at, Job.first_seen_at)
    q = select(Job).options(joinedload(Job.match)).join(JobMatch).where(
        JobMatch.score >= min_score, freshness >= cutoff
    ).order_by(freshness.desc(), JobMatch.score.desc())
    if status: q = q.where(Job.status == status)
    jobs = db.scalars(q.limit(250)).unique().all()
    stats = {
        "total": db.scalar(select(func.count(Job.id)).where(freshness >= cutoff)) or 0,
        "high": db.scalar(select(func.count(JobMatch.id)).join(Job).where(JobMatch.score >= settings.min_instant_score, freshness >= cutoff)) or 0,
        "relevant": db.scalar(select(func.count(JobMatch.id)).join(Job).where(JobMatch.score >= settings.min_daily_score, freshness >= cutoff)) or 0,
        "avg": db.scalar(select(func.avg(JobMatch.score)).join(Job).where(freshness >= cutoff)) or 0,
    }
    last_run = db.scalar(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(1))
    source_runs = []
    if last_run:
        source_runs = db.scalars(select(SourceRun).where(SourceRun.search_run_id == last_run.id).order_by(SourceRun.source)).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "jobs": jobs, "stats": stats, "last_run": last_run,
        "source_runs": source_runs, "enabled_sources": enabled_source_names(),
        "min_score": min_score, "status": status, "message": message,
        "daily_score": settings.min_daily_score, "instant_score": settings.min_instant_score,
        "max_job_age_hours": settings.max_job_age_hours,
    })

@app.post("/collect")
def collect_now():
    run_collection(); return RedirectResponse("/", status_code=303)

@app.post("/test-email")
def test_email():
    ok, message = send_test_email()
    prefix = "Succès : " if ok else "Erreur : "
    return RedirectResponse(f"/?{urlencode({'message': prefix + message})}", status_code=303)

@app.post("/jobs/{job_id}/status")
def change_status(job_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job: job.status = status; db.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/health")
def health(): return {"status": "ok"}
