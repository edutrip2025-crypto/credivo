import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send_email(to_email: str, subject: str, body: str) -> dict:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        return {"sent": False, "reason": "SMTP not configured"}

    msg = EmailMessage()
    msg["From"] = settings.smtp_sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
    return {"sent": True}
