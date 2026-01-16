import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

logger = logging.getLogger(__name__)


def send_confirmation_email(
    to_address: str,
    subject: str,
    body: str,
) -> None:
    if not (settings.smtp_host and settings.smtp_from):
        logger.info("email_disabled missing smtp_host or smtp_from")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        logger.warning("email_send_failed to=%s error=%s", to_address, exc)
