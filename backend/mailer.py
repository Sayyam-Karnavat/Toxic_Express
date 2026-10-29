"""Transactional email via Resend. In dev/test (no API key) emails are logged and kept in OUTBOX."""

import html
import logging
from dataclasses import dataclass

from config import settings
from http_client import get_http_client
from retry import http_retry, raise_for_retryable

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


@dataclass
class Email:
    to: str
    subject: str
    html: str
    text: str


OUTBOX: list[Email] = []  # populated when no provider is configured (dev/test)


def _layout(title: str, body_html: str, cta_text: str, cta_url: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#0a0d3a;font-family:Inter,Arial,sans-serif;color:#ffffff">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px">
<table width="560" cellpadding="0" cellspacing="0" style="background:#1e2353;border-radius:16px;padding:32px">
<tr><td style="font-size:22px;font-weight:800;letter-spacing:0.5px">TOXIC-EXPRESS</td></tr>
<tr><td style="padding-top:24px;font-size:20px;font-weight:700">{html.escape(title)}</td></tr>
<tr><td style="padding-top:12px;font-size:16px;line-height:1.5">{body_html}</td></tr>
<tr><td style="padding-top:24px"><a href="{html.escape(cta_url, quote=True)}" style="display:inline-block;background:#5865f2;color:#ffffff;text-decoration:none;font-weight:600;padding:14px 24px;border-radius:12px">{html.escape(cta_text)}</a></td></tr>
<tr><td style="padding-top:24px;font-size:13px;color:#c9cbe8">If you didn't request this, you can ignore this email.</td></tr>
</table></td></tr></table></body></html>"""


def verification_email(to: str, name: str, token: str) -> Email:
    url = f"{settings.frontend_url}/verify-email?token={token}"
    body = f"Hey {html.escape(name)}, confirm your email so you can post media and get the full experience."
    return Email(
        to=to,
        subject="Confirm your Toxic-Express email",
        html=_layout("Confirm your email", body, "Confirm email", url),
        text=f"Confirm your email: {url}",
    )


def password_reset_email(to: str, name: str, token: str) -> Email:
    url = f"{settings.frontend_url}/reset-password?token={token}"
    minutes = settings.password_reset_ttl_minutes
    body = f"Hey {html.escape(name)}, use the button below to choose a new password. The link expires in {minutes} minutes."
    return Email(
        to=to,
        subject="Reset your Toxic-Express password",
        html=_layout("Reset your password", body, "Reset password", url),
        text=f"Reset your password: {url}",
    )


def account_deletion_email(to: str, name: str) -> Email:
    url = f"{settings.frontend_url}/login"
    body = (
        f"Hey {html.escape(name)}, your account is scheduled for deletion in 30 days. "
        "Log in before then to cancel."
    )
    return Email(
        to=to,
        subject="Your Toxic-Express account will be deleted",
        html=_layout("Account deletion scheduled", body, "Log in to cancel", url),
        text=f"Your account will be deleted in 30 days. Log in to cancel: {url}",
    )


async def deliver(email: Email) -> None:
    api_key = settings.resend_api_key.get_secret_value()
    if not api_key:
        OUTBOX.append(email)
        logger.info("[dev email] to=%s subject=%r text=%s", email.to, email.subject, email.text)
        return
    payload = {
        "from": settings.email_from,
        "to": [email.to],
        "subject": email.subject,
        "html": email.html,
        "text": email.text,
    }
    async for attempt in http_retry(attempts=4, max_seconds=20):
        with attempt:
            response = await get_http_client().post(
                RESEND_URL, json=payload, headers={"Authorization": f"Bearer {api_key}"}
            )
            raise_for_retryable(response)
