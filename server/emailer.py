"""
CHISEL OTP email delivery via Brevo's HTTPS API.

Why HTTPS and not SMTP: free hosting tiers (Render, Railway Hobby) block
outbound SMTP ports, but ordinary HTTPS calls are allowed.

Behaviour:
  - BREVO_API_KEY set     → the OTP is emailed through Brevo.
  - BREVO_API_KEY not set → development only: the OTP is printed to the
                            server log so you can test without an account.
                            (Production refuses to boot without a key.)
"""

import logging

import httpx

from .config import settings

log = logging.getLogger("chisel.email")

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

# Tests can swap this for httpx.MockTransport to avoid real network calls.
_transport: httpx.AsyncBaseTransport | None = None


class EmailDeliveryError(Exception):
    """Raised when the email provider rejects or fails to accept the message."""


def _bodies(code: str) -> tuple[str, str]:
    minutes = settings.OTP_EXPIRE_SECONDS // 60
    text = (
        f"Your CHISEL verification code is {code}\n\n"
        f"It expires in {minutes} minutes. If you did not request it, ignore this email.\n"
        "CHISEL staff will never ask you for this code."
    )
    html = f"""\
<!doctype html>
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#1f2328;background:#ffffff;margin:0;padding:24px">
  <p style="margin:0 0 12px">Your CHISEL verification code is</p>
  <p style="font-size:28px;font-weight:bold;letter-spacing:6px;margin:0 0 16px">{code}</p>
  <p style="margin:0 0 8px">It expires in {minutes} minutes.</p>
  <p style="margin:0;color:#59636e;font-size:13px">If you did not request this code, you can ignore this email.
  CHISEL staff will never ask you for it.</p>
</body></html>"""
    return text, html


async def send_otp_email(to_email: str, code: str) -> None:
    """Deliver an OTP. Raises EmailDeliveryError if Brevo does not accept it."""
    if not settings.BREVO_API_KEY:
        # Dev fallback — production config refuses to start without a key.
        log.warning("[DEV] No BREVO_API_KEY set. OTP for %s: %s", to_email, code)
        return

    text, html = _bodies(code)
    payload = {
        "sender": {"name": settings.EMAIL_SENDER_NAME, "email": settings.EMAIL_SENDER_ADDRESS},
        "to": [{"email": to_email}],
        "subject": f"{code} is your CHISEL verification code",
        "textContent": text,
        "htmlContent": html,
        "tags": ["chisel-otp"],
    }
    headers = {
        "api-key": settings.BREVO_API_KEY,
        "accept": "application/json",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
            resp = await client.post(BREVO_SEND_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise EmailDeliveryError(f"Could not reach Brevo: {e}") from e

    if resp.status_code not in (200, 201, 202):
        # Brevo returns {"code": "...", "message": "..."} on errors; never log the API key
        try:
            detail = resp.json().get("message", resp.text[:200])
        except ValueError:
            detail = resp.text[:200]
        raise EmailDeliveryError(f"Brevo returned {resp.status_code}: {detail}")

    log.info("[Email] OTP sent to %s (Brevo id=%s)", to_email, resp.json().get("messageId", "?"))
