"""
Send email alerts when a trade opportunity (LONG_ENTRY or SHORT_ENTRY) is detected.
Uses SMTP (e.g. Gmail with an app password).
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings
from app.models import TradeSignal

logger = logging.getLogger(__name__)


def send_trade_alert(signal: TradeSignal) -> None:
    """
    Send a single email with the trade signal details.
    No-op if email is not configured or send fails (logged but not raised).
    """
    settings = get_settings()
    if not settings.email_enabled:
        logger.info("Email skipped: EMAIL_ENABLED is not true")
        return
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("Email skipped: SMTP_USER or SMTP_PASSWORD is missing in .env")
        return
    to_email = settings.notify_email or settings.smtp_user
    if not to_email:
        logger.warning("Email skipped: NOTIFY_EMAIL and SMTP_USER are both empty")
        return

    subject = f"[BTC Signal] {signal.signal.value} @ {signal.price:,.2f}"
    body_plain = (
        f"Trade opportunity detected.\n\n"
        f"Symbol: {signal.symbol}\n"
        f"Timeframe: {signal.timeframe.value}\n"
        f"Signal: {signal.signal.value}\n"
        f"Price: {signal.price:,.2f}\n"
        f"Reason: {signal.reason}\n\n"
        f"Generated at: {signal.generated_at.isoformat()} UTC"
    )
    body_html = (
        f"<p><strong>Trade opportunity detected.</strong></p>"
        f"<p><b>Symbol:</b> {signal.symbol} &nbsp; <b>Timeframe:</b> {signal.timeframe.value}</p>"
        f"<p><b>Signal:</b> {signal.signal.value} &nbsp; <b>Price:</b> {signal.price:,.2f}</p>"
        f"<p><b>Reason:</b> {signal.reason}</p>"
        f"<p><small>Generated at {signal.generated_at.isoformat()} UTC</small></p>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
        logger.info("Trade alert email sent to %s: %s @ %s", to_email, signal.signal.value, signal.price)
    except Exception as e:
        logger.warning("Failed to send trade alert email: %s", e, exc_info=True)


def send_test_email() -> tuple[bool, str]:
    """
    Send one test email to NOTIFY_EMAIL. Returns (success, message).
    """
    settings = get_settings()
    if not settings.email_enabled:
        return False, "EMAIL_ENABLED is not true in .env"
    if not settings.smtp_user or not settings.smtp_password:
        return False, "SMTP_USER or SMTP_PASSWORD is missing in .env"
    to_email = settings.notify_email or settings.smtp_user
    subject = "[BTC Signal] Test email"
    body = "If you see this, email from your BTC Signal app is working."
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, to_email, msg.as_string())
        logger.info("Test email sent to %s", to_email)
        return True, f"Test email sent to {to_email}"
    except Exception as e:
        logger.warning("Test email failed: %s", e, exc_info=True)
        return False, str(e)
