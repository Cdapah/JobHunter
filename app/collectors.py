import base64
import binascii
import hashlib
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .config import settings

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "JobHunter/2.0 personal-job-alert"}


def _dt(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except (TypeError, ValueError):
        return None


def collect_arbeitnow():
    response = httpx.get(
        "https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=20
    )
    response.raise_for_status()
    return [
        {
            "source": "Arbeitnow",
            "external_id": str(item.get("slug") or item["url"]),
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", "Remote/Europe"),
            "contract_type": "CDI" if "full-time" in str(item.get("job_types", [])).lower() else "Non précisé",
            "remote": bool(item.get("remote")),
            "url": item["url"],
            "description": item.get("description", ""),
            "published_at": _dt(item.get("created_at")),
        }
        for item in response.json().get("data", [])
    ]


def collect_remotive():
    response = httpx.get(
        "https://remotive.com/api/remote-jobs", headers=HEADERS, timeout=20
    )
    response.raise_for_status()
    return [
        {
            "source": "Remotive",
            "external_id": str(item["id"]),
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("candidate_required_location", "Remote"),
            "contract_type": item.get("job_type", "Non précisé"),
            "remote": True,
            "salary": item.get("salary", ""),
            "url": item["url"],
            "description": item.get("description", ""),
            "published_at": _dt(item.get("publication_date")),
        }
        for item in response.json().get("jobs", [])
    ]


def _france_travail_token() -> str:
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.france_travail_client_id,
        "client_secret": settings.france_travail_client_secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }
    urls = [settings.france_travail_auth_url]
    legacy = "https://entreprise.pole-emploi.fr/connexion/oauth2/access_token?realm=/partenaire"
    if legacy not in urls:
        urls.append(legacy)
    last_error = None
    for url in urls:
        try:
            response = httpx.post(url, data=data, timeout=20)
            response.raise_for_status()
            return response.json()["access_token"]
        except Exception as exc:  # pragma: no cover - dépend du service externe
            last_error = exc
    raise RuntimeError(f"Authentification France Travail impossible : {last_error}")


def _france_travail_location(item: dict) -> str:
    place = item.get("lieuTravail") or {}
    return place.get("libelle") or place.get("commune") or "France"


def _france_travail_url(item: dict) -> str:
    origin = item.get("origineOffre") or {}
    return origin.get("urlOrigine") or f"https://candidat.francetravail.fr/offres/recherche/detail/{item.get('id', '')}"


def collect_france_travail():
    if not settings.france_travail_client_id or not settings.france_travail_client_secret:
        raise RuntimeError("FRANCE_TRAVAIL_CLIENT_ID et FRANCE_TRAVAIL_CLIENT_SECRET sont manquants")
    token = _france_travail_token()
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    results = {}
    keywords = [word.strip() for word in settings.france_travail_keywords.split(",") if word.strip()]
    for keyword in keywords:
        response = httpx.get(
            settings.france_travail_api_url,
            headers=headers,
            params={"motsCles": keyword, "typeContrat": "CDI", "range": "0-99", "sort": "1"},
            timeout=30,
        )
        if response.status_code == 204:
            continue
        response.raise_for_status()
        for item in response.json().get("resultats", []):
            identifier = str(item.get("id", ""))
            if not identifier:
                continue
            company = (item.get("entreprise") or {}).get("nom") or "Entreprise non précisée"
            salary = (item.get("salaire") or {}).get("libelle", "")
            experience = item.get("experienceLibelle", "")
            description = " ".join(part for part in (item.get("description", ""), experience) if part)
            results[identifier] = {
                "source": "France Travail",
                "external_id": identifier,
                "title": item.get("intitule", ""),
                "company": company,
                "location": _france_travail_location(item),
                "contract_type": item.get("typeContratLibelle") or item.get("typeContrat") or "CDI",
                "remote": "télétravail" in description.lower() or "teletravail" in description.lower(),
                "salary": salary,
                "url": _france_travail_url(item),
                "description": description,
                "published_at": _dt(item.get("dateCreation")),
            }
    return list(results.values())


ALERT_SENDERS = {
    "linkedin": "LinkedIn Alerte",
    "apec": "APEC Alerte",
    "indeed": "Indeed Alerte",
    "hellowork": "HelloWork Alerte",
    "cadremploi": "Cadremploi Alerte",
    "cadre emploi": "Cadremploi Alerte",
}
IGNORED_LINK_WORDS = (
    "unsubscribe", "désabonner", "se désabonner", "preferences", "préférences",
    "privacy", "confidentialité", "help", "aide", "view in browser", "voir en ligne",
    "logo", "facebook", "instagram", "twitter", "gérer les alertes",
    "gerer les alertes", "manage alerts",
)
CLOSED_WORDS = (
    "les candidatures ne sont plus acceptées", "candidatures clôturées",
    "offre expirée", "offre n'est plus disponible", "poste pourvu",
    "recrutement terminé", "no longer accepting applications",
    "job is no longer available",
)


def _decode(value: str | None) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _alert_source(message) -> str | None:
    haystack = f"{_decode(message.get('From'))} {_decode(message.get('Subject'))}".lower()
    return next((label for marker, label in ALERT_SENDERS.items() if marker in haystack), None)


def _unwrap_url(href: str) -> str:
    """Déplie les redirections d'e-mail sans effectuer de requête réseau."""
    value = href.replace("&amp;", "&").strip()
    for _ in range(3):
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        # Les alertes APEC utilisent un lien de suivi dont le paramètre « e »
        # contient p1=www.apec.fr&p2=<identifiant offre> en base64url.
        if parsed.hostname == "neomarket.diffusion.apec.fr" and query.get("e"):
            try:
                encoded = query["e"][0]
                decoded = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                ).decode("utf-8")
                fields = parse_qs(decoded, keep_blank_values=True)
                offer_id = fields.get("p2", [""])[0]
                if fields.get("p1", [""])[0].lower() == "www.apec.fr" and re.fullmatch(r"\d{8,12}[A-Z]", offer_id):
                    return f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{offer_id}"
            except (ValueError, UnicodeDecodeError, binascii.Error):
                pass
            break
        # HelloWork place le destinataire puis l'URL de l'offre dans le
        # dernier segment base64url de /clic/. On ne conserve jamais le préfixe
        # personnel : seule l'adresse publique de l'offre est retournée.
        if parsed.hostname == "emails.hellowork.com" and parsed.path.startswith("/clic/"):
            try:
                encoded = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                decoded = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                ).decode("utf-8")
                match = re.search(r"https://(?:www\.)?hellowork\.com/fr-fr/emplois/\d+\.html(?:\?[^\s]*)?", decoded)
                if match:
                    return match.group(0)
            except (ValueError, UnicodeDecodeError, binascii.Error):
                pass
            break
        candidate = next((query[key][0] for key in (
            "url", "target", "redirect", "redirect_url", "destination", "dest", "u"
        ) if query.get(key) and query[key][0].startswith("http")), None)
        if not candidate:
            break
        value = unquote(candidate)
    return value


def canonical_job_url(href: str, source: str) -> str:
    """Supprime les paramètres de tracking et conserve l'identifiant de l'offre."""
    href = _unwrap_url(href)
    parsed = urlparse(href)
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    query = parse_qs(parsed.query)
    if source == "LinkedIn Alerte":
        match = re.search(r"/jobs/(?:view|collections/[^/]+)/(?:[^/?]*-)?(\d+)", path)
        if not match:
            match = re.search(r"/(\d{6,})(?:/|$)", path)
        if match:
            return f"https://www.linkedin.com/jobs/view/{match.group(1)}"
    if source == "Indeed Alerte":
        key = (query.get("jk") or query.get("vjk") or [None])[0]
        if key:
            return f"https://fr.indeed.com/viewjob?jk={key}"
    keep = {}
    for key in ("offreId", "id", "reference", "ref"):
        if query.get(key):
            keep[key] = query[key][0]
    return urlunparse(("https", host, path, "", urlencode(keep), ""))


def _message_bodies(message) -> tuple[str, str]:
    html_parts, text_parts = [], []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (html_parts if content_type == "text/html" else text_parts).append(str(content))
    return "\n".join(html_parts), "\n".join(text_parts)


def is_valid_alert_job_link(href: str, label: str, source: str) -> bool:
    href = _unwrap_url(href)
    text = f"{href} {label}".lower()
    if not href.startswith("http") or any(word in text for word in IGNORED_LINK_WORDS):
        return False
    parsed = urlparse(href)
    host, path = parsed.netloc.lower(), parsed.path.lower()
    if source == "LinkedIn Alerte":
        return "linkedin.com" in host and ("/jobs/view/" in path or "/comm/jobs/view/" in path)
    if source == "APEC Alerte":
        return "apec.fr" in host and any(part in text for part in ("detail-offre", "offres-emploi-cadres"))
    if source == "Indeed Alerte":
        return any(domain in host for domain in ("indeed.com", "indeed.fr")) and any(part in text for part in ("viewjob", "/rc/clk", "jk="))
    if source == "HelloWork Alerte":
        return "hellowork.com" in host and any(part in path for part in ("/emplois/", "/fr-fr/emplois/", "/offre-emploi/"))
    if source == "Cadremploi Alerte":
        if host == "r.emails4.alertes.cadremploi.fr" and path.startswith("/tr/cl/"):
            return label.lower().strip() not in {"voir toutes les offres", "toutes les offres"}
        return "cadremploi.fr" in host and any(part in text for part in (
            "offre", "emploi", "job", "poste", "offreid="
        ))
    return False


def _job_context(anchor) -> str:
    """Texte du bloc d'une offre, sans mélanger toutes les annonces du mail."""
    best = anchor.get_text(" ", strip=True)
    for parent in anchor.parents:
        if getattr(parent, "name", None) not in {"td", "tr", "li", "article", "div"}:
            continue
        text = " ".join(parent.get_text(" ", strip=True).split())
        if len(best) < len(text) <= 1500:
            best = text
        if len(text) >= 250:
            break
    return best


GENERIC_TITLES = {
    "voir l'offre", "voir l’offre", "postuler", "voir le poste", "en savoir plus",
    "view job", "apply", "découvrir l'offre", "decouvrir l'offre",
}


def _job_title(anchor, context: str) -> str:
    candidates = [
        anchor.get("aria-label", ""), anchor.get("title", ""),
        anchor.get_text(" ", strip=True),
    ]
    for tag in anchor.find_all_previous(["h1", "h2", "h3", "h4", "strong", "b"], limit=8):
        candidates.append(tag.get_text(" ", strip=True))
    candidates.extend(re.split(r"[\n\r|•·]+", context))
    role_words = (
        "dévelop", "develop", "ingénieur", "engineer", "analyst", "analyste",
        "data", "logiciel", "software", "power bi", "power apps", "business intelligence",
        "reporting", "etl", "backend", "full stack", "consultant",
    )
    cleaned = []
    for candidate in candidates:
        candidate = " ".join(str(candidate).split()).strip(" -–—:|")
        low = candidate.lower()
        if 4 <= len(candidate) <= 220 and low not in GENERIC_TITLES:
            cleaned.append(candidate)
    return next((c for c in cleaned if any(word in c.lower() for word in role_words)), cleaned[0] if cleaned else "Offre d'emploi")


def _job_company(anchor, context: str, title: str) -> str:
    for tag in anchor.find_all_previous(["strong", "b"], limit=8):
        value = " ".join(tag.get_text(" ", strip=True).split())
        low = value.lower()
        if 2 < len(value) <= 120 and value != title and low not in GENERIC_TITLES:
            if not any(word in low for word in ("dévelop", "engineer", "analyst", "data", "logiciel")):
                return value
    return "Entreprise à vérifier"


def _cadremploi_details(context: str, title: str) -> tuple[str, str]:
    """Récupère entreprise et ville dans une carte « titre / entreprise • ville • CDI »."""
    if not title or title == "Offre d'emploi":
        return "Entreprise à vérifier", "France (alerte configurée)"
    match = re.search(
        re.escape(title) + r"\s+([^•·|\n]{2,100}?)\s*[•·|]\s*([^•·|\n]{2,100}?)\s*[•·|]\s*CDI\b",
        context, re.IGNORECASE,
    )
    if not match:
        return "Entreprise à vérifier", "France (alerte configurée)"
    return match.group(1).strip(), match.group(2).strip()


def _alert_external_id(source: str, href: str, title: str, company: str, location: str, context: str = "") -> str:
    if source == "Cadremploi Alerte" and urlparse(href).hostname == "r.emails4.alertes.cadremploi.fr":
        # L'URL Cadremploi est opaque et change selon le mail. La carte d'offre
        # fournit une identité stable ; ne jamais inclure le jeton de suivi.
        identity = "|".join(re.sub(r"\W+", " ", value.casefold()).strip()
                            for value in (title, company, location))
        if company == "Entreprise à vérifier":
            identity += "|" + re.sub(r"\W+", " ", context.casefold()).strip()
        return hashlib.sha256(f"cadremploi:{identity}".encode()).hexdigest()
    return hashlib.sha256(href.encode()).hexdigest()


def _published_within_24h(text: str) -> bool | None:
    value = text.lower()
    if any(word in value for word in ("aujourd'hui", "aujourd’hui", "today", "nouveau", "new")):
        return True
    if re.search(r"il y a\s*\d+\s*(?:min(?:ute)?s?|heures?)", value) or re.search(r"\d+\s*(?:minutes?|hours?|hrs?)\s+ago", value):
        return True
    if re.search(r"il y a\s*\d+\s*(?:jours?|semaines?|mois)", value) or re.search(r"\d+\s*(?:days?|weeks?|months?)\s+ago", value):
        return False
    return None


def parse_alert_email(message) -> list[dict]:
    source = _alert_source(message)
    if not source:
        return []
    subject = _decode(message.get("Subject"))
    html, plain = _message_bodies(message)
    soup = BeautifulSoup(html, "html.parser")
    published_at = None
    try:
        published_at = parsedate_to_datetime(message.get("Date")) if message.get("Date") else None
    except (TypeError, ValueError):
        pass
    jobs = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = anchor["href"].strip()
        label = " ".join(anchor.get_text(" ", strip=True).split())
        if not is_valid_alert_job_link(raw_href, label, source):
            continue
        context = _job_context(anchor)
        title = _job_title(anchor, context)
        href = canonical_job_url(raw_href, source)
        if href in seen:
            continue
        context_lower = context.lower()
        if any(word in context_lower for word in CLOSED_WORDS):
            continue
        if _published_within_24h(context) is False:
            continue
        seen.add(href)
        company = _job_company(anchor, context, title)
        location = "France (alerte configurée)"
        if source == "Cadremploi Alerte":
            parsed_company, parsed_location = _cadremploi_details(context, title)
            if parsed_company != "Entreprise à vérifier":
                company, location = parsed_company, parsed_location
        identifier = _alert_external_id(source, href, title, company, location, context)
        jobs.append({
            "source": source,
            "external_id": identifier,
            "title": title,
            "company": company,
            "location": location,
            "contract_type": "CDI à vérifier",
            "remote": "télétravail" in context_lower or "remote" in context_lower,
            "url": href,
            "description": f"{subject}. {context[:1500]}",
            "published_at": published_at,
        })
    # Certaines alertes (ou leur version texte) ne contiennent pas de balises
    # HTML exploitables. On récupère aussi les URL présentes en texte brut.
    for match in re.finditer(r"https?://[^\s<>\"']+", plain):
        raw_href = match.group(0).rstrip(".,);]")
        start, end = max(0, match.start() - 300), min(len(plain), match.end() + 300)
        context = " ".join(plain[start:end].split())
        if not is_valid_alert_job_link(raw_href, context, source):
            continue
        href = canonical_job_url(raw_href, source)
        if href in seen or any(word in context.lower() for word in CLOSED_WORDS):
            continue
        if _published_within_24h(context) is False:
            continue
        synthetic = BeautifulSoup(f"<a>{context}</a>", "html.parser").a
        title = _job_title(synthetic, context)
        company, location = _cadremploi_details(context, title) if source == "Cadremploi Alerte" else ("Entreprise à vérifier", "France (alerte configurée)")
        seen.add(href)
        jobs.append({
            "source": source,
            "external_id": _alert_external_id(source, href, title, company, location, context),
            "title": title,
            "company": company,
            "location": location,
            "contract_type": "CDI à vérifier",
            "remote": "télétravail" in context.lower() or "remote" in context.lower(),
            "url": href,
            "description": f"{subject}. {context[:1500]}",
            "published_at": published_at,
        })
    return jobs


def _alert_mailbox(mailbox, configured: str, host: str) -> str:
    """Gmail : lire Tous les messages, y compris les alertes archivées."""
    if host.lower() != "imap.gmail.com" or configured.upper() != "INBOX":
        return configured
    status, folders = mailbox.list()
    if status != "OK":
        return configured
    for row in folders or []:
        if not row or b"\\All" not in row.split(b")", 1)[0].split():
            continue
        match = re.search(rb'\)\s+"[^"]+"\s+(?:"([^"]+)"|(\S+))$', row)
        if match:
            return '"' + (match.group(1) or match.group(2)).decode("ascii") + '"'
    return configured


def collect_email_alerts():
    from .public_posts import parse_google_alert_posts
    username = settings.imap_user or settings.smtp_user
    password = settings.imap_password or settings.smtp_password
    if not username or not password:
        raise RuntimeError("IMAP_USER/IMAP_PASSWORD (ou les identifiants SMTP) sont manquants")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_job_age_hours)
    since = cutoff.strftime("%d-%b-%Y")
    jobs = []
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as mailbox:
        mailbox.login(username, password)
        selected = _alert_mailbox(mailbox, settings.imap_mailbox, settings.imap_host)
        status, _ = mailbox.select(selected, readonly=True)
        if status != "OK" and selected != settings.imap_mailbox:
            selected = settings.imap_mailbox
            status, _ = mailbox.select(selected, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Impossible d'ouvrir le dossier IMAP {selected}")
        log.info("Dossier IMAP utilisé pour les alertes : %s", selected)
        status, data = mailbox.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("Recherche IMAP impossible")
        for message_id in data[0].split()[-settings.imap_max_messages:]:
            status, raw = mailbox.fetch(message_id, "(RFC822)")
            if status != "OK" or not raw or not raw[0]:
                continue
            message = message_from_bytes(raw[0][1], policy=policy.default)
            try:
                message_date = parsedate_to_datetime(message.get("Date"))
                if message_date and message_date.astimezone(timezone.utc) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            jobs.extend(parse_alert_email(message))
            jobs.extend(parse_google_alert_posts(message))
    unique = {job["external_id"]: job for job in jobs}
    return list(unique.values())


def get_collectors():
    collectors = []
    if settings.public_posts_enabled:
        from .public_posts import collect_public_posts
        collectors.append(collect_public_posts)
    if settings.france_travail_enabled:
        collectors.append(collect_france_travail)
    if settings.imap_enabled:
        collectors.append(collect_email_alerts)
    if settings.enable_arbeitnow:
        collectors.append(collect_arbeitnow)
    if settings.enable_remotive:
        collectors.append(collect_remotive)
    return collectors


def enabled_source_names():
    names = []
    if settings.public_posts_enabled:
        names.append("Posts LinkedIn publics (recherche Web)")
    if settings.france_travail_enabled:
        names.append("France Travail")
    if settings.imap_enabled:
        names.append("Alertes e-mail LinkedIn/APEC/Indeed/HelloWork/Cadremploi")
        names.append("Google Alertes : posts LinkedIn publics")
    if settings.enable_arbeitnow:
        names.append("Arbeitnow (filtré France)")
    if settings.enable_remotive:
        names.append("Remotive (filtré France)")
    return names
