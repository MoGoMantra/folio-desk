"""Background jobs: long runs (a market-signal run, a rotation run, an equity run) execute in a thread pool and
store their result as a document; the page polls /api/jobs/{id} for status."""
from __future__ import annotations

import datetime as dt
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .. import db
from ..config import get_settings

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def submit(kind: str, fn: Callable[[], tuple[str, str, dict]], label: str = "") -> dict:
    """fn returns (collection, id, document); the job stores it and records where it went."""
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "kind": kind, "label": label, "status": "queued", "message": "", "createdAt": _now(), "result": None}
    with _lock:
        _jobs[jid] = job

    def work():
        job["status"] = "running"
        try:
            coll, did, doc = fn()
            db.put_doc(coll, did, doc)
            job.update(status="done", result={"collection": coll, "id": did}, finishedAt=_now())
        except Exception as e:
            log.exception("job %s failed", kind)
            job.update(status="error", message=str(e), trace=traceback.format_exc()[-2000:], finishedAt=_now())
    _pool.submit(work)
    return job


def get(jid: str) -> dict | None:
    return _jobs.get(jid)


def recent(n: int = 30) -> list[dict]:
    return sorted(_jobs.values(), key=lambda j: j["createdAt"], reverse=True)[:n]


# ---------------------------------------------------------------- job bodies

def job_signals():
    from ..signals import market
    prev = db.latest_doc("signals")
    doc = market.run(get_settings(), prev=prev)
    if prev and prev.get("asOf") == doc["asOf"]:  # re-run of the same session: compare against the one before
        older = [d for d in db.list_docs("signals", 5) if d["id"] < doc["asOf"]]
        doc = market.run(get_settings(), prev=older[0] if older else None)
    return "signals", doc["asOf"], doc


def job_rotation():
    from ..sectors import rotation
    doc = rotation.run(get_settings(), signals_doc=db.latest_doc("signals"))
    return "rotation", doc["asOf"], doc


def job_drawdowns():
    from ..sectors import drawdown
    doc = drawdown.run(get_settings())
    return "drawdowns", doc["asOf"], doc


def job_equity(ticker: str, peers: list[str] | None):
    from .. import equity
    rep = equity.run(ticker, peers)
    return "equity", ticker.upper(), rep


def job_decisions():
    from ..decision.run import run
    doc = run()
    return "decisions", doc["asOf"], doc


# ---------------------------------------------------------------- schedule

_scheduler = None


def start_scheduler():
    global _scheduler
    s = get_settings().schedule
    if not s.enabled or _scheduler:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _scheduler = BackgroundScheduler(timezone=s.timezone)
    h, m = map(int, s.signals_at.split(":"))
    _scheduler.add_job(lambda: submit("signals", job_signals, "scheduled"), CronTrigger(day_of_week="mon-fri", hour=h, minute=m))
    _scheduler.add_job(lambda: submit("rotation", job_rotation, "scheduled"), CronTrigger(day_of_week="mon-fri", hour=h, minute=(m + 10) % 60))
    _scheduler.add_job(lambda: submit("drawdowns", job_drawdowns, "scheduled"), CronTrigger(day_of_week="mon-fri", hour=h, minute=(m + 20) % 60))
    _scheduler.add_job(lambda: submit("decisions", job_decisions, "scheduled"), CronTrigger(day_of_week="mon-fri", hour=h, minute=(m + 40) % 60))
    _scheduler.start()
    log.info("scheduler started (%s)", s.timezone)
