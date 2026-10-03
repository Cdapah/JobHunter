import re
import unicodedata

from .profile import PROFILE

BLOCKED_LEVEL_TITLES = (
    "senior", "sr.", "lead", "tech lead", "staff", "principal", "manager",
    "architect", "head of", "director", "responsable", "chef de projet",
)
BLOCKED_CONTRACTS = (
    "stage", "internship", "alternance", "apprenticeship", "freelance",
    "indépendant", "independent", "part_time", "part-time", "temps partiel",
)
BLOCKED_CLOSED = (
    "les candidatures ne sont plus acceptées", "candidatures clôturées",
    "candidatures fermees", "offre expirée", "offre expiree",
    "offre n'est plus disponible", "poste pourvu", "recrutement terminé",
    "no longer accepting applications", "job is no longer available",
)
JUNIOR = (
    "junior", "débutant", "debutant", "graduate", "entry level",
    "entry-level", "jeune diplômé", "young graduate", "0-2 ans",
    "0-2 years", "1-2 ans", "1-2 years",
)
FRANCE_LOCATIONS = tuple(PROFILE["preferred_locations"] + PROFILE["other_locations"])
EXPERIENCE_3_PLUS = re.compile(
    r"\b(?:[3-9]|[1-9][0-9])\s*(?:\+|minimum|min\.?|au moins)?\s*"
    r"(?:years?|yrs?|ans|annees?)\b(?:\s*(?:(?:d['’]|de|of)\s*)?"
    r"(?:professional\s+)?(?:experience|expérience|exp\.?))?",
    re.IGNORECASE,
)
EXPERIENCE_RANGE_3_PLUS = re.compile(r"\b(?:[3-9]|[1-9][0-9])\s*[-–à]\s*(?:[4-9]|[1-9][0-9])\s*(?:ans|years?)\b", re.IGNORECASE)


def _normalize(value: str | None) -> str:
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


def _has(text: str, variants) -> bool:
    normalized = _normalize(text)
    return any(_normalize(v) in normalized for v in variants)


def eligibility_reason(title: str, description: str = "", location: str = "",
                       contract: str = "", source: str = "") -> tuple[bool, str]:
    """Filtre strict avant insertion en base.

    Les alertes e-mail sont considérées françaises car l'utilisatrice crée les
    alertes avec le filtre France. France Travail ne publie que des offres en
    France. Les sources internationales doivent, elles, mentionner la France.
    """
    title_text = _normalize(title)
    description_text = _normalize(description)
    location_text = _normalize(location)
    contract_text = _normalize(contract)
    source_text = _normalize(source)
    full_text = " ".join((title_text, description_text, location_text, contract_text))

    if _has(title_text, BLOCKED_LEVEL_TITLES):
        return False, "niveau senior/encadrement"
    if _has(contract_text, BLOCKED_CONTRACTS) or _has(title_text, BLOCKED_CONTRACTS):
        return False, "contrat non recherché"
    if _has(full_text, BLOCKED_CLOSED):
        return False, "candidatures fermées"
    if EXPERIENCE_3_PLUS.search(full_text) or EXPERIENCE_RANGE_3_PLUS.search(full_text):
        return False, "au moins 3 ans d'expérience demandés"

    trusted_france_source = source_text in {
        "france travail", "linkedin alerte", "apec alerte",
        "indeed alerte", "hellowork alerte", "cadremploi alerte",
    }
    if not trusted_france_source and not _has(location_text, FRANCE_LOCATIONS):
        return False, "localisation hors France ou non garantie"

    if source_text in {"post linkedin public", "google alertes (posts)"} and not _has(contract_text, ("cdi", "permanent")):
        return False, "contrat CDI non confirmé dans le post"

    # Certains e-mails donnent au lien un libellé générique (« Voir l'offre »),
    # alors que l'intitulé réel se trouve dans le bloc descriptif autour du lien.
    relevant_title = _has(f"{title_text} {description_text}", PROFILE["target_titles"])
    if not relevant_title:
        return False, "intitulé trop éloigné des métiers recherchés"
    return True, "éligible"


def is_eligible_job(title: str, description: str = "", location: str = "",
                    contract: str = "", source: str = "") -> bool:
    return eligibility_reason(title, description, location, contract, source)[0]


def score_job(title: str, description: str, location: str = "", contract: str = "") -> dict:
    text = " ".join((title or "", description or "", location or "", contract or ""))
    matched = [name for name, variants in PROFILE["skills"].items() if _has(text, variants)]
    missing = [name for name in PROFILE["skills"] if name not in matched]
    skill_score = min(30, len(matched) * 5)
    title_score = 25 if _has(title, PROFILE["target_titles"]) else (10 if matched else 0)
    experience_score = 15 if _has(text, JUNIOR) else 10
    contract_score = 15 if _has(contract, ("cdi", "permanent", "full_time", "full-time")) else 8
    location_score = 10 if _has(location, PROFILE["preferred_locations"]) else 7
    education_score = 5 if _has(text, ("bac+5", "master", "engineering degree", "diplôme d'ingénieur")) else 2
    score = min(100, skill_score + title_score + experience_score + contract_score + location_score + education_score)
    level = "Niveau junior identifié." if _has(text, JUNIOR) else "Aucun niveau senior détecté ; expérience à vérifier avant candidature."
    why = f"{len(matched)} compétence(s) concordante(s). {level}"
    return {
        "score": score,
        "matched_skills": ", ".join(matched),
        "missing_skills": ", ".join(missing[:5]),
        "explanation": why,
    }

def canonical_key(title: str, company: str, location: str) -> str:
    clean = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
    return f"{clean(title)}:{clean(company)}:{clean(location)}"
