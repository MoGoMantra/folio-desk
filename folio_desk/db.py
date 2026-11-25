"""SQLite storage via SQLAlchemy.

Phase 1 keeps analysis runs as JSON documents (one table, keyed by collection + id), which is how the
pipelines already think: one signals doc per session, one rotation doc per session, one report per ticker.
Portfolios and the fund list are typed tables because the UI edits them row by row. The trading register
(Phase 2) gets its own typed tables.
"""
from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import JSON, DateTime, Float, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Document(Base):
    """A JSON document in a named collection, e.g. ("signals", "2026-11-24")."""
    __tablename__ = "documents"
    collection: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Fund(Base):
    __tablename__ = "funds"
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(64), default="US Total Market")
    index: Mapped[str] = mapped_column(String(200), default="")
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    type: Mapped[str] = mapped_column(String(32), default="ETF")
    proxy: Mapped[str] = mapped_column(String(16), default="")


class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    rows: Mapped[list] = mapped_column(JSON)          # [{"t": "VTI", "a": "T", "w": 30.0}, ...]
    accounts: Mapped[dict] = mapped_column(JSON)      # {"T": 100000, "I": 0, "R": 0}
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


_engine = None
_Session: sessionmaker | None = None


def init_db(path: str | Path) -> None:
    global _engine, _Session
    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{Path(path)}"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    kw = {"connect_args": {"check_same_thread": False}}
    if str(path) == ":memory:":
        from sqlalchemy.pool import StaticPool
        kw["poolclass"] = StaticPool
    _engine = create_engine(url, **kw)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)


@contextmanager
def session() -> Session:
    if _Session is None:
        raise RuntimeError("database not initialised: call init_db() first")
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------- document helpers

def _clean(data):
    """Round-trip through JSON so numpy scalars and NaN never reach SQLite."""
    return json.loads(json.dumps(data, default=lambda o: o.item() if hasattr(o, "item") else str(o)).replace("NaN", "null"))


def put_doc(collection: str, id: str, data: dict) -> None:
    with session() as s:
        doc = s.get(Document, (collection, id))
        if doc:
            doc.data = _clean(data)
        else:
            s.add(Document(collection=collection, id=id, data=_clean(data)))


def get_doc(collection: str, id: str) -> dict | None:
    with session() as s:
        doc = s.get(Document, (collection, id))
        return doc.data if doc else None


def latest_doc(collection: str) -> dict | None:
    """Newest by id (ids are ISO dates or tickers; for dated collections the max id is the latest)."""
    with session() as s:
        doc = s.scalars(select(Document).where(Document.collection == collection).order_by(Document.id.desc()).limit(1)).first()
        return doc.data if doc else None


def list_docs(collection: str, limit: int = 500) -> list[dict]:
    with session() as s:
        rows = s.scalars(select(Document).where(Document.collection == collection).order_by(Document.id.desc()).limit(limit)).all()
        return [{"id": r.id, "updatedAt": r.updated_at.isoformat() if r.updated_at else None, **(r.data or {})} for r in rows]
