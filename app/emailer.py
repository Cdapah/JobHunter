import smtplib
from email.message import EmailMessage
from .config import settings

def _send_message(msg: EmailMessage):
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls(); smtp.login(settings.smtp_user, settings.smtp_password); smtp.send_message(msg)

def send_jobs(jobs, subject="Nouvelles offres correspondant à ton profil"):
    if not settings.email_enabled or not jobs: return False
    lines = []
    for j in jobs:
        lines += [f"{j.title} — {j.company}", f"📍 {j.location} | 🎯 {j.match.score:.0f}%", f"Compétences: {j.match.matched_skills}", f"Pourquoi: {j.match.explanation}", f"Postuler: {j.url}", ""]
        # Compétence constatée dans le projet JobHunter mais absente des CV
        # fournis : ne conseiller son ajout que si l'annonce la mentionne.
        if "docker" in (j.description or "").lower():
            lines.insert(len(lines) - 1, "Conseil CV : si tu décris ton projet JobHunter, tu peux mentionner Docker Compose (déploiement sur ton serveur Oracle).")
    msg = EmailMessage(); msg["Subject"] = f"🚀 {len(jobs)} {subject}"; msg["From"] = settings.smtp_user; msg["To"] = settings.email_destination; msg.set_content("\n".join(lines))
    _send_message(msg)
    return True

def send_test_email():
    if not settings.email_enabled:
        return False, "EMAIL_ENABLED est désactivé dans .env"
    if not all((settings.smtp_user, settings.smtp_password, settings.email_destination)):
        return False, "Configuration SMTP incomplète dans .env"
    msg = EmailMessage()
    msg["Subject"] = "✅ Test JobHunter réussi"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.email_destination
    msg.set_content("JobHunter peut bien envoyer ses alertes sur cette adresse.")
    try:
        _send_message(msg)
        return True, f"E-mail de test envoyé à {settings.email_destination}"
    except Exception as exc:
        return False, f"Échec SMTP : {exc}"
