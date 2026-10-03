from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./jobhunter.db"

    # Sources internationales facultatives. Elles sont désactivées par défaut
    # pour privilégier les offres réellement accessibles depuis la France.
    enable_arbeitnow: bool = False
    enable_remotive: bool = False

    # API officielle France Travail (Offres d'emploi v2).
    france_travail_enabled: bool = False
    france_travail_client_id: str = ""
    france_travail_client_secret: str = ""
    france_travail_auth_url: str = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
    france_travail_api_url: str = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    france_travail_keywords: str = "développeur logiciel,développeur python,data analyst,data engineer,power bi,power platform"

    # Lecture des alertes officielles LinkedIn/APEC/Indeed/HelloWork reçues
    # dans Gmail. Utiliser uniquement un mot de passe d'application Google.
    imap_enabled: bool = False
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_lookback_days: int = 7
    imap_max_messages: int = 1000
    max_job_age_hours: int = 24

    # Recherche Web des posts LinkedIn publics indexés (API Brave Search).
    public_posts_enabled: bool = False
    brave_search_api_key: str = ""
    public_posts_interval_hours: int = 6

    email_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_destination: str = ""
    search_interval_minutes: int = 60
    min_daily_score: int = 86
    min_instant_score: int = 86
    email_all_new_eligible: bool = False
    base_url: str = "http://localhost:8000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
