"""Découverte de posts publics par l'index Brave Search, sans visiter LinkedIn."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from .config import settings
from .matching import FRANCE_LOCATIONS, _has

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
QUERIES = (
    'site:linkedin.com/posts/ "recrute" "data engineer" "France"',
    'site:linkedin.com/posts/ "recrute" "data analyst" "France"',
    'site:linkedin.com/posts/ "recrute" "développeur" "junior" "France"',
    'site:linkedin.com/posts/ "recrute" "power bi" "France"',
)
ROLE = re.compile(
    r"\b(?:data engineer|data analyst|business analyst|ingénieur(?:e)? logiciel|"
    r"développeur(?:se)?(?:\s+(?:python|backend|logiciel))?|power bi|power platform)\b",
    re.IGNORECASE,
)
POST_ID = re.compile(r"(?:activity|ugcPost)[-:]?(\d{12,})", re.IGNORECASE)
CONTRACT = re.compile(r"\b(?:CDI|contrat à durée indéterminée)\b", re.IGNORECASE)


def _post_url(raw: str) -> str | None:
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in {"linkedin.com", "www.linkedin.com", "fr.linkedin.com"}:
        return None
    if not parsed.path.startswith("/posts/"):
        return None
    # Ne conserver ni paramètres de suivi ni fragments.
    return "https://www.linkedin.com" + parsed.path.rstrip("/")


def _post_from_result(result: dict, now: datetime) -> dict | None:
    url = _post_url(result.get("url", ""))
    if not url:
        return None
    title = BeautifulText(result.get("title", ""))
    snippet = BeautifulText(result.get("description", ""))
    snippets = [BeautifulText(x) for x in (result.get("extra_snippets") or [])]
    evidence = " ".join((title, snippet, *snippets))
    role = ROLE.search(evidence)
    # Les mots de la requête ne sont PAS considérés comme des faits sur le post.
    if not role or not CONTRACT.search(evidence) or not _has(evidence, FRANCE_LOCATIONS):
        return None
    age = result.get("page_age")
    try:
        published = datetime.fromisoformat(age.replace("Z", "+00:00")) if age else None
        if published and published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        published = None
    if published and (published < now - timedelta(hours=settings.max_job_age_hours) or published > now + timedelta(hours=1)):
        return None
    # La date indexée peut être celle d'une modification, pas celle de l'annonce.
    # Sans date vérifiable, on indique explicitement cette incertitude.
    description = f"Extrait indexé (annonce, expérience et date à confirmer) : {evidence[:1200]}"
    post_id = POST_ID.search(url)
    external_id = post_id.group(1) if post_id else hashlib.sha256(url.encode()).hexdigest()
    return {
        "source": "Post LinkedIn public",
        "external_id": external_id,
        "title": role.group(0) + " — post de recrutement",
        "company": "Entreprise à vérifier",
        "location": next((place for place in FRANCE_LOCATIONS if _has(evidence, (place,))), "France"),
        "contract_type": "CDI à vérifier",
        "remote": "télétravail" in evidence.lower() or "hybride" in evidence.lower(),
        "url": url,
        "description": description,
        "published_at": published,
    }


def BeautifulText(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", unescape(value or "")).split())


def collect_public_posts() -> list[dict]:
    if not settings.brave_search_api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY manquante : source de posts publics inactive")
    now = datetime.now(timezone.utc)
    posts = {}
    with httpx.Client(timeout=20) as client:
        for query in QUERIES:
            response = client.get(
                BRAVE_URL,
                headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_search_api_key},
                params={"q": query, "freshness": "pd", "country": "FR", "search_lang": "fr", "count": 20, "extra_snippets": "true"},
            )
            response.raise_for_status()
            for result in response.json().get("web", {}).get("results", []):
                post = _post_from_result(result, now)
                if post:
                    posts[post["external_id"]] = post
    return list(posts.values())


def parse_google_alert_posts(message) -> list[dict]:
    """Extrait les posts LinkedIn des e-mails Google Alertes reçus sur Gmail."""
    from email.utils import parseaddr
    from bs4 import BeautifulSoup
    from .collectors import _message_bodies, _unwrap_url, _published_within_24h

    if parseaddr(message.get("From", ""))[1].lower() != "googlealerts-noreply@google.com":
        return []
    try:
        received = parsedate_to_datetime(message.get("Date", "")).astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        return []
    now = datetime.now(timezone.utc)
    if received < now - timedelta(hours=settings.max_job_age_hours) or received > now + timedelta(hours=1):
        return []
    html, plain = _message_bodies(message)
    results = {}
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = _unwrap_url(anchor["href"])
        if not _post_url(href):
            continue
        # Chaque résultat doit garder son extrait ; ne jamais utiliser le
        # sujet de l'alerte comme preuve de CDI, France ou niveau junior.
        context = anchor.get_text(" ", strip=True)
        for parent in anchor.parents:
            if parent.name not in {"div", "td", "tr", "li", "table", "article"}:
                continue
            candidate = parent.get_text(" ", strip=True)
            links = {
                _post_url(_unwrap_url(link["href"]))
                for link in parent.find_all("a", href=True)
            }
            links.discard(None)
            if len(candidate) > 1500 or len(links) > 1:
                break
            if len(candidate) > len(context):
                context = candidate
        if _published_within_24h(context) is False:
            continue
        post = _post_from_result({
            "url": href,
            "title": anchor.get_text(" ", strip=True),
            "description": context[:1500],
        }, now)
        if post:
            post["source"] = "Google Alertes (posts)"
            results[post["external_id"]] = post
    # Certaines alertes n'ont qu'une partie texte.
    for match in re.finditer(r"https?://[^\s<>\"']+", plain):
        href = _unwrap_url(match.group(0).rstrip(".,);]"))
        if not _post_url(href):
            continue
        context = " ".join(plain[max(0, match.start()-350):min(len(plain), match.end()+500)].split())
        if _published_within_24h(context) is False:
            continue
        post = _post_from_result({"url": href, "title": context[:180], "description": context[:1200]}, now)
        if post:
            post["source"] = "Google Alertes (posts)"
            results[post["external_id"]] = post
    return list(results.values())
