"""Settings: folio-desk.toml (git-ignored) overlaid with FOLIO_<SECTION>_<KEY> environment variables.

Lookup order for the file: $FOLIO_CONFIG, ./folio-desk.toml, ~/.folio-desk/folio-desk.toml.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass
class SecSettings:
    user_agent: str = ""


@dataclass
class DataSettings:
    price_providers: list[str] = field(default_factory=lambda: ["yahoo"])
    polygon_api_key: str = ""
    fmp_api_key: str = ""
    tiingo_api_key: str = ""
    allow_unofficial: bool = False


@dataclass
class StorageSettings:
    db_path: str = "~/.folio-desk/folio.db"


@dataclass
class WatchlistSettings:
    symbols: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "JNJ", "XOM", "JPM"])


@dataclass
class ThemeSettings:
    name: str = "AI leaders"
    symbols: list[str] = field(default_factory=lambda: ["NVDA", "AVGO", "AMD", "TSM", "MSFT", "META"])
    bellwether: str = ""


@dataclass
class ScheduleSettings:
    enabled: bool = False
    timezone: str = "America/New_York"
    signals_at: str = "17:15"
    prices_at: str = "18:15"


@dataclass
class Settings:
    sec: SecSettings = field(default_factory=SecSettings)
    data: DataSettings = field(default_factory=DataSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    watchlist: WatchlistSettings = field(default_factory=WatchlistSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)

    @property
    def db_file(self) -> Path:
        return Path(os.path.expanduser(self.storage.db_path))

    def public(self) -> dict:
        """Settings safe to show in the UI: keys are reported as set / not set, never echoed."""
        out = {}
        for sec in fields(self):
            obj = getattr(self, sec.name)
            out[sec.name] = {}
            for f in fields(obj):
                v = getattr(obj, f.name)
                if f.name.endswith("_api_key"):
                    v = bool(v)
                out[sec.name][f.name] = v
        return out


def _coerce(value: str, current):
    if isinstance(current, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, list):
        v = value.strip()
        if v.startswith("["):
            return json.loads(v)
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(current, int):
        return int(value)
    return value


def _apply(obj, data: dict):
    for f in fields(obj):
        if f.name in data:
            cur = getattr(obj, f.name)
            if is_dataclass(cur):
                _apply(cur, data[f.name])
            else:
                setattr(obj, f.name, data[f.name])


def config_path() -> Path | None:
    cands = [os.environ.get("FOLIO_CONFIG"), "folio-desk.toml", "~/.folio-desk/folio-desk.toml"]
    for c in cands:
        if c and Path(os.path.expanduser(c)).is_file():
            return Path(os.path.expanduser(c))
    return None


def load_settings(path: str | Path | None = None, env: dict | None = None) -> Settings:
    s = Settings()
    p = Path(path) if path else config_path()
    if p and p.is_file():
        with open(p, "rb") as fh:
            _apply(s, tomllib.load(fh))
    env = os.environ if env is None else env
    for sec in fields(s):
        obj = getattr(s, sec.name)
        for f in fields(obj):
            key = f"FOLIO_{sec.name}_{f.name}".upper()
            if key in env:
                setattr(obj, f.name, _coerce(env[key], getattr(obj, f.name)))
    return s


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(s: Settings) -> None:
    """Used by tests and the CLI."""
    global _settings
    _settings = s
