"""
CHISEL — cover-pool buffer test (no real image generation)
==========================================================
Runs the real FastAPI app in-process against a throwaway SQLite DB, with
Pollinations replaced by a fake that returns a 512×512 PNG after a short delay.

Checks the buffer rule: keep 5 covers; when a sender takes one and only 2 are
left, the SERVER generates 3 more to get back to 5. Also: refills are
single-flight, an empty pool returns 503 and triggers a refill, and a
Pollinations outage doesn't crash anything.
"""

import asyncio
import io
import os
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="chisel_pool_test_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/pool.db"
os.environ["POOL_TARGET_SIZE"] = "5"
os.environ["POOL_REFILL_THRESHOLD"] = "2"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from server import pool  # noqa: E402
from server.auth import create_token  # noqa: E402
from server.database import async_session, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.models import User  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))


class FakePollinations:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.delay = 0.05

    async def __call__(self, api_key):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise httpx.ConnectError("simulated Pollinations outage")
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), (self.calls * 20 % 256, 90, 140)).save(buf, format="PNG")
        return buf.getvalue()


async def unused():
    async with async_session() as db:
        return await pool.get_unused_count(db)


async def settle():
    """Wait for any background refill triggered by a request to finish."""
    for _ in range(200):
        await asyncio.sleep(0.02)
        if not pool.refill_in_progress() and not pool._background:
            return


async def main():
    t0 = time.perf_counter()
    await init_db()
    fake = FakePollinations()
    pool.fetch_cover_from_pollinations = fake  # refill_pool looks it up at call time

    async with async_session() as db:
        user = User(email="sender@example.com")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    h = {"Authorization": f"Bearer {create_token(user.id, user.email)}"}
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    print("\n── 1. Startup fill ──────────────────────────────────────")
    added = await pool.ensure_pool()
    check("empty pool at startup → server generates 5", added == 5 and await unused() == 5, f"added={added}")
    calls = fake.calls

    print("\n── 2. Taking covers: 5 → 4 → 3 → 2 → refill to 5 ───────")
    sizes = []
    for _ in range(3):
        r = await api.get("/api/cover-image", headers=h)
        assert r.status_code == 200, r.text
        await settle()
        sizes.append(await unused())
    check("taking 1st cover leaves 4 (no refill)", sizes[0] == 4, str(sizes))
    check("taking 2nd cover leaves 3 (no refill)", sizes[1] == 3, str(sizes))
    check("taking 3rd cover hits 2 → refilled back to 5", sizes[2] == 5, str(sizes))
    check("exactly 3 new images generated for that refill", fake.calls - calls == 3, f"{fake.calls - calls}")

    r = await api.get("/api/pool-status", headers=h)
    d = r.json()
    check("pool-status reports target 5 / threshold 2",
          d.get("target_size") == 5 and d.get("refill_threshold") == 2 and "refilling" in d, str(d))

    print("\n── 3. Single-flight ─────────────────────────────────────")
    async with async_session() as db:      # drain to 1 directly
        while await pool.get_unused_count(db) > 1:
            await pool.pop_cover(db)
    calls = fake.calls
    fake.delay = 0.2
    pool.trigger_refill(); pool.trigger_refill(); pool.trigger_refill()
    await settle()
    check("3 simultaneous triggers → one refill of 4, not 12", fake.calls - calls == 4 and await unused() == 5,
          f"calls={fake.calls - calls}, unused={await unused()}")
    fake.delay = 0.05

    print("\n── 4. Empty pool and outages ────────────────────────────")
    fake.fail = True
    async with async_session() as db:
        while await pool.pop_cover(db):
            pass
    r = await api.get("/api/cover-image", headers=h)
    check("empty pool → 503 with a 'try again' message", r.status_code == 503 and "try again" in r.text, r.text)
    await settle()
    check("Pollinations outage → no crash, pool stays empty", await unused() == 0)
    fake.fail = False
    r = await api.get("/api/cover-image", headers=h)   # still empty, but triggers refill
    await settle()
    check("next request triggers a refill once Pollinations is back", await unused() == 5, str(await unused()))
    r = await api.get("/api/cover-image", headers=h)
    check("…and covers are served again", r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (512, 512))

    await api.aclose()
    passed = sum(results)
    print(f"\n  {passed}/{len(results)} passed in {(time.perf_counter() - t0) * 1000:.0f} ms")
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
