from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

from app.matching import eligibility_reason
from app.public_posts import _post_from_result, parse_google_alert_posts


def test_public_post_requires_evidence_and_does_not_infer_from_query():
    now = datetime.now(timezone.utc)
    base = {
        "url": "https://www.linkedin.com/posts/recruiter_data-engineer-activity-7508033828133748737?utm_source=x",
        "title": "Recrutement Data Engineer | LinkedIn",
        "description": "Nous recrutons à Paris en CDI un Data Engineer junior Python SQL.",
        "page_age": (now - timedelta(hours=2)).isoformat(),
    }
    job = _post_from_result(base, now)
    assert job is not None
    assert "utm_source" not in job["url"]
    assert eligibility_reason(job["title"], job["description"], job["location"], job["contract_type"], job["source"])[0]
    assert _post_from_result({**base, "description": "Nous recrutons un Data Engineer junior en CDI."}, now) is None
    assert _post_from_result({**base, "description": "Nous recrutons à Paris un Data Engineer junior."}, now) is None
    assert _post_from_result({**base, "page_age": (now - timedelta(hours=30)).isoformat()}, now) is None
    assert _post_from_result({**base, "url": "https://other.example/posts/1"}, now) is None


def test_public_post_excludes_overqualified_roles():
    now = datetime.now(timezone.utc)
    job = _post_from_result({
        "url": "https://www.linkedin.com/posts/recruteur_data-activity-7508033828133748737",
        "title": "Data Engineer CDI Paris",
        "description": "5 ans d'expérience minimum demandés, Python SQL",
    }, now)
    assert job is not None
    assert not eligibility_reason(job["title"], job["description"], job["location"], job["contract_type"], job["source"])[0]


def _google_message(html: str, sender: str = "Google Alertes <googlealerts-noreply@google.com>"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Subject"] = 'site:linkedin.com/posts/ "Data Engineer" "CDI" "France"'
    msg.set_content("Notification Google Alertes")
    msg.add_alternative(html, subtype="html")
    return msg


def test_google_alert_keeps_context_per_post_and_unwraps_tracking_url():
    msg = _google_message('''
      <table><tr><td><a href="https://www.google.com/url?url=https%3A%2F%2Fwww.linkedin.com%2Fposts%2Frecruiter_data-activity-7508033828133748737%3Ftrk%3Demail">Data Engineer chez AFNOR</a></td></tr>
      <tr><td>Recrutement en CDI à Paris : Python, SQL, junior, données.</td></tr></table>
      <table><tr><td><a href="https://www.linkedin.com/posts/other_data-activity-7508033828133748738">Data Analyst senior</a></td></tr>
      <tr><td>5 ans d'expérience en CDI à Lyon.</td></tr></table>
    ''')
    jobs = parse_google_alert_posts(msg)
    assert len(jobs) == 2
    assert jobs[0]["source"] == "Google Alertes (posts)"
    assert "trk=" not in jobs[0]["url"]
    assert not eligibility_reason(jobs[1]["title"], jobs[1]["description"], jobs[1]["location"], jobs[1]["contract_type"], jobs[1]["source"])[0]


def test_google_alert_does_not_transfer_query_or_other_result_criteria():
    msg = _google_message('''
      <table><tr><td><a href="https://www.linkedin.com/posts/recruiter_data-activity-7508033828133748737">Data Engineer</a></td></tr>
      <tr><td>Nous recherchons un profil data, détails sur demande.</td></tr></table>
      <table><tr><td><a href="https://www.linkedin.com/posts/recruiter_data-activity-7508033828133748738">Data Analyst</a></td></tr>
      <tr><td>CDI à Paris, SQL et Python.</td></tr></table>
    ''')
    assert len(parse_google_alert_posts(msg)) == 1
    assert parse_google_alert_posts(_google_message(msg.get_body(preferencelist=("html",)).get_content(), "attacker@example.com")) == []
