import base64
from email.message import EmailMessage

from app.collectors import _alert_mailbox, canonical_job_url, is_valid_alert_job_link, parse_alert_email


def test_linkedin_alert_parser_extracts_job_link():
    message = EmailMessage()
    message["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    message["Subject"] = "Alerte Développeur Python junior en France"
    message["Date"] = "Sun, 20 Sep 2026 12:00:00 +0000"
    message.set_content("Une offre est disponible")
    message.add_alternative(
        '<html><body><a href="https://www.linkedin.com/jobs/view/123">Développeur Python junior</a>'
        '<a href="https://www.linkedin.com/help">Aide</a></body></html>',
        subtype="html",
    )
    jobs = parse_alert_email(message)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "LinkedIn Alerte"
    assert jobs[0]["title"] == "Développeur Python junior"


def test_linkedin_search_and_manage_links_are_rejected():
    assert not is_valid_alert_job_link(
        "https://www.linkedin.com/comm/jobs/search-results/?keywords=python",
        "Offres d'emploi Python",
        "LinkedIn Alerte",
    )
    assert not is_valid_alert_job_link(
        "https://www.linkedin.com/jobs/alerts/",
        "Gérer les alertes",
        "LinkedIn Alerte",
    )


def test_old_or_closed_alert_job_is_rejected():
    message = EmailMessage()
    message["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    message["Subject"] = "Alerte emploi"
    message["Date"] = "Sun, 20 Sep 2026 12:00:00 +0000"
    message.set_content("Alerte")
    message.add_alternative(
        '<html><body><div><a href="https://www.linkedin.com/jobs/view/456">Data Analyst junior</a>'
        "<span>Paris · il y a 5 jours</span></div>"
        '<div><a href="https://www.linkedin.com/jobs/view/789">Développeur Python junior</a>'
        "<span>Les candidatures ne sont plus acceptées</span></div></body></html>",
        subtype="html",
    )
    assert parse_alert_email(message) == []


def test_linkedin_comm_link_and_tracking_are_canonicalized():
    first = "https://www.linkedin.com/comm/jobs/view/data-analyst-1234567890?trackingId=aaa"
    second = "https://www.linkedin.com/jobs/view/1234567890?trk=email_job_alert"
    assert is_valid_alert_job_link(first, "Voir l'offre", "LinkedIn Alerte")
    assert canonical_job_url(first, "LinkedIn Alerte") == canonical_job_url(second, "LinkedIn Alerte")


def test_generic_button_uses_nearby_title():
    message = EmailMessage()
    message["From"] = "Cadremploi <alertes@cadremploi.fr>"
    message["Subject"] = "Votre alerte emploi"
    message["Date"] = "Sun, 20 Sep 2026 12:00:00 +0000"
    message.set_content("Alerte")
    message.add_alternative(
        '<html><body><div><h2>Data Analyst Junior H/F</h2><b>Entreprise Exemple</b>'
        '<span>Paris · aujourd\'hui</span><a href="https://www.cadremploi.fr/emploi/detail_offre?offreId=42">Voir l\'offre</a>'
        '</div></body></html>', subtype="html",
    )
    jobs = parse_alert_email(message)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "Cadremploi Alerte"
    assert jobs[0]["title"] == "Data Analyst Junior H/F"


def test_indeed_tracking_parameters_do_not_create_duplicates():
    a = "https://fr.indeed.com/rc/clk?jk=abc123&utm_source=alert"
    b = "https://fr.indeed.com/viewjob?jk=abc123&from=jobi2a"
    assert canonical_job_url(a, "Indeed Alerte") == canonical_job_url(b, "Indeed Alerte")


def test_apec_email_tracking_link_yields_real_offer_and_deduplicates():
    tracked = (
        "https://neomarket.diffusion.apec.fr/r/?id=example-test"
        "&e=cDE9d3d3LmFwZWMuZnImcDI9MTc5NDcwODQ0VyZwMz0meHRvcj1FUFItNDEtW3B1c2hfYXZlY19jb21wdGVd"
        "&s=example-test-signature"
    )
    direct = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/179470844W?xtor=mail"
    assert is_valid_alert_job_link(tracked, "Premier Data Engineer", "APEC Alerte")
    assert canonical_job_url(tracked, "APEC Alerte") == canonical_job_url(direct, "APEC Alerte")
    message = EmailMessage()
    message["From"] = "APEC <offres@diffusion.apec.fr>"
    message["Subject"] = "458 offres Apec du 24/09/2026"
    message["Date"] = "Thu, 24 Sep 2026 07:18:00 +0200"
    message.set_content("Offres APEC")
    message.add_alternative(
        f'<html><body><div><a href="{tracked.replace("&", "&amp;")}">Premier Data Engineer</a>'
        '<span>CDI · Paris · Aujourd’hui</span></div></body></html>', subtype="html"
    )
    jobs = parse_alert_email(message)
    assert len(jobs) == 1
    assert jobs[0]["url"] == canonical_job_url(direct, "APEC Alerte")


def test_apec_tracking_link_only_accepts_official_redirect_host():
    suspicious = "https://example.com/r/?e=cDE9d3d3LmFwZWMuZnImcDI9MTc5NDcwODQ0Vw=="
    assert not is_valid_alert_job_link(suspicious, "Data Engineer", "APEC Alerte")


def test_hellowork_email_tracking_link_extracts_public_job_only():
    offer = "https://www.hellowork.com/fr-fr/emplois/83682506.html?utm_source=jobalert&utm_medium=email"
    encoded = base64.urlsafe_b64encode(f"test@example.com🪢{offer}".encode()).decode().rstrip("=")
    tracked = f"https://emails.hellowork.com/clic/00000000-0000-0000-0000-000000000000/12/hash/{encoded}"
    direct = "https://www.hellowork.com/fr-fr/emplois/83682506.html"
    assert is_valid_alert_job_link(tracked, "Ingénieur Développement Logiciel Python", "HelloWork Alerte")
    assert canonical_job_url(tracked, "HelloWork Alerte") == canonical_job_url(direct, "HelloWork Alerte")
    message = EmailMessage()
    message["From"] = "HelloWork Alert <alertes@hellowork.com>"
    message["Subject"] = "Carole, HelloWork a trouvé des offres"
    message["Date"] = "Thu, 24 Sep 2026 08:32:00 +0200"
    message.set_content("Alerte emploi")
    message.add_alternative(
        f'<div><a href="{tracked}">Ingénieur Développement Logiciel Python H/F</a>'
        '<span>Scalian · Toulouse · CDI</span></div>', subtype="html"
    )
    jobs = parse_alert_email(message)
    assert len(jobs) == 1
    assert jobs[0]["url"] == canonical_job_url(direct, "HelloWork Alerte")
    assert "test@example.com" not in str(jobs)


def test_hellowork_tracking_link_rejects_other_host():
    encoded = base64.urlsafe_b64encode(b"https://www.hellowork.com/fr-fr/emplois/83682506.html").decode()
    assert not is_valid_alert_job_link(
        f"https://other.example/clic/1/2/{encoded}", "Ingénieur Python", "HelloWork Alerte"
    )


def test_cadremploi_opaque_alert_links_keep_job_and_deduplicate_by_card():
    def alert(token, company="LHH"):
        message = EmailMessage()
        message["From"] = "Votre alerte Cadremploi <alertes@cadremploi.fr>"
        message["Subject"] = "Une offre à ne pas rater"
        message["Date"] = "Thu, 24 Sep 2026 07:00:00 +0200"
        message.set_content("Offre")
        message.add_alternative(
            f'<div><a href="https://r.emails4.alertes.cadremploi.fr/tr/cl/{token}">'
            f'Data Analyst (h/f)</a><span>{company} • Boulogne-Billancourt • CDI</span></div>'
            '<a href="https://r.emails4.alertes.cadremploi.fr/tr/cl/all">Voir toutes les offres</a>',
            subtype="html",
        )
        return parse_alert_email(message)

    first, second = alert("opaque-one"), alert("opaque-two")
    assert len(first) == len(second) == 1
    assert first[0]["company"] == "LHH"
    assert first[0]["location"] == "Boulogne-Billancourt"
    assert first[0]["external_id"] == second[0]["external_id"]
    assert first[0]["external_id"] != alert("opaque-one", company="Other")[0]["external_id"]
    assert first[0]["url"].endswith("opaque-one")


def test_cadremploi_tracker_must_be_on_official_domain():
    assert not is_valid_alert_job_link(
        "https://other.example/tr/cl/random", "Data Analyst", "Cadremploi Alerte"
    )


def test_gmail_uses_all_mail_to_read_archived_alerts():
    class Mailbox:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
            ]

    assert _alert_mailbox(Mailbox(), "INBOX", "imap.gmail.com") == '"[Gmail]/All Mail"'
    assert _alert_mailbox(Mailbox(), "INBOX", "imap.other.com") == "INBOX"
    assert _alert_mailbox(Mailbox(), "Alerts", "imap.gmail.com") == "Alerts"


def test_gmail_localized_all_mail_folder_is_selected_by_flag():
    class Mailbox:
        def list(self):
            return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/Tous les messages"']

    assert _alert_mailbox(Mailbox(), "INBOX", "imap.gmail.com") == '"[Gmail]/Tous les messages"'
