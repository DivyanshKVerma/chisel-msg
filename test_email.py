"""
CHISEL — OTP email delivery test (no real emails are sent)
==========================================================
Runs the real FastAPI app in-process against a throwaway SQLite DB and a
fake Brevo endpoint (httpx.MockTransport). Checks that:
  1. The OTP arrives only by "email" (not in the API response) and works.
  2. A Brevo rejection returns 502, and the user can retry at once.
  3. A network failure returns 502.
  4. Without BREVO_API_KEY (dev), the OTP is logged and registration works.
  5. Production config refuses to boot without Brevo settings.
"""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time

_tmpdir = tempfile.mkdtemp(prefix="chisel_email_test_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmpdir}/test.db"
os.environ["DEMO_RETURN_OTP"] = "false"
os.environ["OTP_RESEND_COOLDOWN_SECONDS"] = "30"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from server import emailer  # noqa: E402
from server.config import Settings, settings  # noqa: E402
from server.database import init_db  # noqa: E402
from server.main import app  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(ok)
    mark = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {mark}  {label}" + (f"  — {detail}" if detail and not ok else ""))


class FakeBrevo:
    """Records requests and replies with a configurable status."""

    def __init__(self):
        self.requests = []
        self.status = 201
        self.fail_network = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail_network:
            raise httpx.ConnectError("simulated outage", request=request)
        self.requests.append(request)
        if self.status in (200, 201, 202):
            return httpx.Response(self.status, json={"messageId": "<fake-123@brevo>"})
        return httpx.Response(self.status, json={"code": "unauthorized", "message": "Key not found"})


async def main():
    t0 = time.perf_counter()
    await init_db()
    fake = FakeBrevo()
    emailer._transport = httpx.MockTransport(fake.handler)
    settings.BREVO_API_KEY = "xkeysib-test-not-real"
    settings.EMAIL_SENDER_ADDRESS = "noreply@example.com"
    settings.DEMO_RETURN_OTP = False

    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    print("\n── 1. OTP delivered by email only ───────────────────────")
    r = await api.post("/api/register", json={"email": "dana@example.com"})
    check("register → 200", r.status_code == 200, r.text)
    check("OTP not exposed in API response", "otp_for_demo" not in r.json(), r.text)
    check("exactly one Brevo call made", len(fake.requests) == 1, str(len(fake.requests)))

    req = fake.requests[-1]
    body = json.loads(req.content)
    check("Brevo URL is the transactional endpoint", str(req.url) == emailer.BREVO_SEND_URL)
    check("api-key header sent", req.headers.get("api-key") == "xkeysib-test-not-real")
    check("addressed to the registering user", body["to"] == [{"email": "dana@example.com"}])
    check("sender is the configured address", body["sender"]["email"] == "noreply@example.com")
    m = re.search(r"\b(\d{6})\b", body["textContent"])
    code = m.group(1) if m else None
    check("6-digit code present in email body", code is not None)
    check("same code in HTML body and subject", code in body["htmlContent"] and code in body["subject"])

    r = await api.post("/api/verify-otp", json={"email": "dana@example.com", "code": code})
    check("code from the email verifies → JWT", r.status_code == 200 and "token" in r.json(), r.text)

    print("\n── 2. Brevo rejects the request ─────────────────────────")
    fake.status = 401
    r = await api.post("/api/register", json={"email": "erin@example.com"})
    check("register → 502 when Brevo refuses", r.status_code == 502, f"{r.status_code} {r.text}")
    check("API key not leaked in error", "xkeysib" not in r.text)
    fake.status = 201
    r = await api.post("/api/register", json={"email": "erin@example.com"})
    check("immediate retry allowed (no cooldown for failed send)", r.status_code == 200, f"{r.status_code} {r.text}")

    print("\n── 3. Brevo unreachable ─────────────────────────────────")
    fake.fail_network = True
    r = await api.post("/api/register", json={"email": "faye@example.com"})
    check("register → 502 on network failure", r.status_code == 502, f"{r.status_code} {r.text}")
    fake.fail_network = False

    print("\n── 4. Dev mode without a Brevo key ──────────────────────")
    settings.BREVO_API_KEY = ""
    captured = []

    class Grab(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    grab = Grab()
    logging.getLogger("chisel.email").addHandler(grab)
    calls_before = len(fake.requests)
    r = await api.post("/api/register", json={"email": "gus@example.com"})
    logging.getLogger("chisel.email").removeHandler(grab)
    check("register → 200 without a key", r.status_code == 200, r.text)
    check("no Brevo call made", len(fake.requests) == calls_before)
    logged = [c for c in captured if "gus@example.com" in c and re.search(r"\b\d{6}\b", c)]
    check("OTP printed to server log for local testing", bool(logged), str(captured))

    print("\n── 5. Production config ─────────────────────────────────")
    prod = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DEMO_RETURN_OTP=False,
        CORS_ORIGINS="https://chisel.example",
    )
    try:
        prod.check_production_safety()
        check("refuses to boot without Brevo settings", False, "booted")
    except RuntimeError as e:
        check("refuses to boot without Brevo settings", "BREVO_API_KEY" in str(e), str(e))
    prod_ok = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        DEMO_RETURN_OTP=False,
        CORS_ORIGINS="https://chisel.example",
        BREVO_API_KEY="k",
        EMAIL_SENDER_ADDRESS="noreply@example.com",
    )
    try:
        prod_ok.check_production_safety()
        check("boots with complete production settings", True)
    except RuntimeError as e:
        check("boots with complete production settings", False, str(e))

    await api.aclose()
    passed = sum(results)
    print(f"\n  {passed}/{len(results)} passed in {(time.perf_counter() - t0) * 1000:.0f} ms")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
