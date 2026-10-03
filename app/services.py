import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from .collectors import get_collectors, is_valid_alert_job_link, canonical_job_url
from .config import settings
from .database import SessionLocal
from .emailer import send_jobs
from .matching import eligibility_reason, score_job, canonical_key
from .models import Job, JobMatch, Notification, SearchRun, SourceRun

log = logging.getLogger(__name__)
EMAIL_SOURCES = ("LinkedIn Alerte", "APEC Alerte", "Indeed Alerte", "HelloWork Alerte", "Cadremploi Alerte", "Google Alertes (posts)")

def _utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def _is_recent(value) -> bool:
    return value is None or _utc(value) >= datetime.now(timezone.utc) - timedelta(hours=settings.max_job_age_hours)

def _purge_stale_or_invalid_jobs(db):
    jobs = db.scalars(
        select(Job).options(joinedload(Job.match)).join(JobMatch)
        .order_by(JobMatch.score.desc(), Job.first_seen_at.desc())
    ).unique().all()
    seen_external = set()
    seen_fingerprints = set()
    for job in jobs:
        eligible, _ = eligibility_reason(
            job.title, job.description, job.location, job.contract_type, job.source
        )
        valid_link = not job.source.endswith(" Alerte") or is_valid_alert_job_link(
            job.url, job.title, job.source
        )
        fingerprint = _dedupe_key({"title": job.title, "company": job.company, "location": job.location})
        company_known = job.company.lower() not in {"entreprise à vérifier", "voir l'alerte officielle"}
        duplicate = job.external_id in seen_external or (company_known and fingerprint in seen_fingerprints)
        if _is_recent(job.published_at or job.first_seen_at) and eligible and valid_link and not duplicate:
            seen_external.add(job.external_id)
            if company_known:
                seen_fingerprints.add(fingerprint)
            continue
        # Les notifications sont l'historique anti-doublons : conserver les
        # annonces notifiées même une fois sorties de la fenêtre de 24 h.
        notified = db.scalar(select(Notification.id).where(Notification.job_id == job.id))
        if not notified:
            db.delete(job)
    db.commit()

def _dedupe_key(data) -> str:
    return canonical_key(data.get("title", ""), data.get("company", ""), data.get("location", ""))

def _already_exists(db, data) -> bool:
    if db.scalar(select(Job.id).where(Job.external_id == data["external_id"])):
        return True
    if data.get("source", "").endswith(" Alerte"):
        candidates = db.scalars(select(Job).where(Job.source == data["source"])).all()
        incoming_url = canonical_job_url(data["url"], data["source"])
        if any(canonical_job_url(j.url, j.source) == incoming_url for j in candidates):
            return True
    key = _dedupe_key(data)
    recent = db.scalars(select(Job).where(
        Job.first_seen_at >= datetime.now(timezone.utc) - timedelta(days=30)
    )).all()
    return any(j.company.lower() not in {"entreprise à vérifier", "voir l'alerte officielle"}
               and data.get("company", "").lower() not in {"entreprise à vérifier", "voir l'alerte officielle"}
               and _dedupe_key({"title": j.title, "company": j.company, "location": j.location}) == key for j in recent)

def run_collection() -> dict:
    db = SessionLocal(); run = SearchRun(); db.add(run); db.commit()
    _purge_stale_or_invalid_jobs(db)
    found = inserted = rejected = 0; errors = []; new_eligible = []
    for collector in get_collectors():
        if collector.__name__ == "collect_public_posts":
            latest = db.scalar(
                select(SearchRun.started_at).join(SourceRun, SourceRun.search_run_id == SearchRun.id)
                .where(SourceRun.source == "Public Posts", SourceRun.error == "", SearchRun.id != run.id)
                .order_by(SearchRun.started_at.desc()).limit(1)
            )
            if latest and _utc(latest) > datetime.now(timezone.utc) - timedelta(hours=max(1, settings.public_posts_interval_hours)):
                continue
        source_found = source_inserted = source_rejected = 0
        source_error = ""
        email_counts = {name: {"found": 0, "inserted": 0, "rejected": 0} for name in EMAIL_SOURCES} if collector.__name__ == "collect_email_alerts" else None
        try:
            items = collector(); source_found = len(items); found += source_found
            for data in items:
                if email_counts is not None:
                    email_counts.setdefault(data["source"], {"found": 0, "inserted": 0, "rejected": 0})["found"] += 1
                if not _is_recent(data.get("published_at")):
                    source_rejected += 1; rejected += 1
                    if email_counts is not None: email_counts[data["source"]]["rejected"] += 1
                    continue
                eligible, reason = eligibility_reason(
                    data["title"], data.get("description", ""), data.get("location", ""),
                    data.get("contract_type", ""), data.get("source", ""),
                )
                if not eligible:
                    source_rejected += 1; rejected += 1
                    if email_counts is not None: email_counts[data["source"]]["rejected"] += 1
                    continue
                if _already_exists(db, data): continue
                match = score_job(data["title"], data.get("description", ""), data.get("location", ""), data.get("contract_type", ""))
                job = Job(**data); job.match = JobMatch(**match); db.add(job)
                try:
                    db.commit(); source_inserted += 1; inserted += 1
                    if email_counts is not None: email_counts[data["source"]]["inserted"] += 1
                    if job.match.score > 85 and job.match.score >= settings.min_instant_score:
                        new_eligible.append(job)
                except IntegrityError: db.rollback()
        except Exception as exc:
            log.exception("Collector failed: %s", collector.__name__)
            source_error = str(exc); errors.append(f"{collector.__name__}: {exc}")
        if email_counts is not None:
            for name, counts in email_counts.items():
                db.add(SourceRun(search_run_id=run.id, source=name, error=source_error, **counts))
        else:
            db.add(SourceRun(
                search_run_id=run.id,
                source=collector.__name__.removeprefix("collect_").replace("_", " ").title(),
                found=source_found,
                inserted=source_inserted,
                rejected=source_rejected,
                error=source_error,
            ))
        db.commit()
    if new_eligible:
        try:
            unsent = [j for j in new_eligible if not db.scalar(
                select(Notification.id).where(Notification.job_id == j.id))]
            if unsent and send_jobs(unsent, "nouvelle(s) offre(s) pertinente(s)"):
                db.add_all([Notification(job_id=j.id, kind="instant") for j in unsent])
        except Exception as exc:
            log.exception("Instant email failed"); errors.append(f"email: {exc}")
    run = db.get(SearchRun, run.id); run.finished_at = datetime.now(timezone.utc); run.found = found; run.inserted = inserted; run.errors = "\n".join(errors); db.commit(); db.close()
    return {"found": found, "inserted": inserted, "rejected": rejected, "errors": errors}

def send_daily_digest() -> int:
    db = SessionLocal()
    _purge_stale_or_invalid_jobs(db)
    # Ne renvoie pas le soir une offre déjà envoyée immédiatement.
    already_sent = select(Notification.job_id)
    jobs = db.scalars(select(Job).options(joinedload(Job.match)).join(JobMatch).where(JobMatch.score > 85, JobMatch.score >= settings.min_daily_score, Job.id.not_in(already_sent)).order_by(JobMatch.score.desc()).limit(50)).unique().all()
    sent = 0
    try:
        if send_jobs(jobs, "nouvelle(s) offre(s) dans ton récapitulatif"):
            db.add_all([Notification(job_id=j.id, kind="daily") for j in jobs]); db.commit(); sent = len(jobs)
    finally:
        db.close()
    return sent
