from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.services.proctor_retention import run_proctor_retention_cleanup


def main() -> None:
    parser = argparse.ArgumentParser(description="Run proctor evidence/session retention cleanup.")
    parser.add_argument("--days", type=int, default=30, help="Retention window in days (min 7).")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        out = run_proctor_retention_cleanup(db, days=int(args.days))
        print(
            json.dumps(
                {
                    "status": "ok",
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "days": out.days,
                    "cutoff": out.cutoff_iso,
                    "sessions_deleted": out.sessions_deleted,
                    "evidence_rows_deleted": out.evidence_rows_deleted,
                    "local_files_deleted": out.local_files_deleted,
                },
                indent=2,
            ),
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
