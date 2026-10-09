from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .core.config import settings
from .core.db import init_db, session_scope
from .core.timeutil import TZ, now_local
from .inference.engine import generate_insights, infer_day
from .services.calendar_sync import sync_calendars

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kizashi")

WEB_DIR = Path(__file__).parent / "web"


def job_prepare_evening() -> None:
    """Runs every evening: pull calendar, infer today, so cards are ready when the user opens the app."""
    with session_scope() as s:
        try:
            if settings.calendar_ics_urls:
                sync_calendars(s)
        except Exception:  # noqa: BLE001
            log.exception("calendar sync failed")
        infer_day(s, now_local().date())


def job_weekly_insights() -> None:
    with session_scope() as s:
        generate_insights(s, end=now_local().date(), days=28)


def job_calendar() -> None:
    if not settings.calendar_ics_urls:
        return
    with session_scope() as s:
        try:
            sync_calendars(s)
        except Exception:  # noqa: BLE001
            log.exception("calendar sync failed")


def job_demo_reseed() -> None:
    """Demo deployments: keep the synthetic world anchored to 'today'."""
    import subprocess
    import sys

    subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "seed_demo.py"), "--days", "21", "--answer", "--reset"], check=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.demo_mode:
        from sqlmodel import select

        from .core.models import RawEvent

        with session_scope() as s:
            if s.exec(select(RawEvent.id).limit(1)).first() is None:
                log.info("demo mode: seeding synthetic data")
                job_demo_reseed()
    scheduler = BackgroundScheduler(timezone=TZ)
    if settings.demo_mode:
        scheduler.add_job(job_demo_reseed, CronTrigger(hour=3, minute=0))
    scheduler.add_job(job_prepare_evening, CronTrigger(hour=settings.evening_prepare_hour, minute=0))
    scheduler.add_job(job_weekly_insights, CronTrigger(day_of_week="sun", hour=20, minute=30))
    scheduler.add_job(job_calendar, "interval", hours=3)
    scheduler.start()
    log.info("kizashi started (backend=%s, demo=%s)", settings.inference_backend, settings.demo_mode)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Kizashi", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")
