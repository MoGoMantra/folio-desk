"""Command line: folio-desk serve | run <job> | init"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="folio-desk", description="Research and portfolio desk for individual investors.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="start the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    rn = sub.add_parser("run", help="run one job now and store the result")
    rn.add_argument("job", choices=["signals", "rotation", "drawdowns", "equity", "decisions"])
    rn.add_argument("ticker", nargs="?")
    rn.add_argument("--peers", default="", help="comma-separated peer tickers for an equity run")
    rn.add_argument("--print", action="store_true", help="print the JSON result")
    sub.add_parser("init", help="write folio-desk.toml from the example")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        src = Path(__file__).resolve().parent.parent / "folio-desk.example.toml"
        dst = Path("folio-desk.toml")
        if dst.exists():
            print("folio-desk.toml already exists; not overwriting.")
            return 1
        if src.exists():
            shutil.copy(src, dst)
        else:
            dst.write_text('[sec]\nuser_agent = ""   # "Your Name you@example.com"\n')
        print("Wrote folio-desk.toml. Set [sec] user_agent before running equity jobs.")
        return 0

    from . import db
    from .config import get_settings
    db.init_db(get_settings().db_file)

    if a.cmd == "serve":
        import uvicorn
        print(f"folio-desk on http://{a.host}:{a.port}  (research output, not investment advice)")
        uvicorn.run("folio_desk.api.app:app", host=a.host, port=a.port)
        return 0

    from .api import jobs
    if a.job == "equity":
        if not a.ticker:
            print("equity needs a ticker", file=sys.stderr)
            return 2
        peers = [p.strip().upper() for p in a.peers.split(",") if p.strip()] or None
        coll, did, doc = jobs.job_equity(a.ticker, peers)
    else:
        coll, did, doc = {"signals": jobs.job_signals, "rotation": jobs.job_rotation, "drawdowns": jobs.job_drawdowns,
                          "decisions": jobs.job_decisions}[a.job]()
    db.put_doc(coll, did, doc)
    print(f"stored {coll}/{did}")
    if a.print:
        print(json.dumps(doc, indent=1, default=str)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
