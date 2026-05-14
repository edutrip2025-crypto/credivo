from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base
from app.services.account_rules import sync_existing_accounts


def _build_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _rows_for_table(source_engine: Engine, table) -> list[dict]:
    with source_engine.connect() as conn:
        result = conn.execute(select(table))
        return [dict(row) for row in result.mappings().all()]


def _sanitize_row_for_table(table, row: dict) -> dict:
    out = dict(row)
    for col in table.columns:
        val = out.get(col.name)
        try:
            py_type = col.type.python_type
        except Exception:
            py_type = None

        # Normalize bools from SQLite ints.
        if py_type is bool and isinstance(val, int):
            out[col.name] = bool(val)
            val = out[col.name]

        # Normalize JSON text payloads from SQLite.
        if py_type in (dict, list) and isinstance(val, str):
            try:
                out[col.name] = json.loads(val)
                val = out[col.name]
            except Exception:
                pass

        val = out.get(col.name)
        max_len = getattr(col.type, "length", None)
        if isinstance(val, str) and isinstance(max_len, int) and max_len > 0 and len(val) > max_len:
            if col.name.endswith("_url") and val.startswith("data:image/"):
                out[col.name] = None
            else:
                out[col.name] = val[:max_len]
    return out


def _truncate_target(target_engine: Engine) -> None:
    with target_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))


def _reset_postgres_sequences(target_engine: Engine) -> None:
    if target_engine.dialect.name != "postgresql":
        return
    with target_engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            pk = list(table.primary_key.columns)
            if len(pk) != 1:
                continue
            col = pk[0]
            try:
                py_type = col.type.python_type
            except Exception:
                continue
            if py_type is not int:
                continue
            table_name = table.name
            col_name = col.name
            conn.execute(
                text(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table_name}', '{col_name}'),
                        COALESCE((SELECT MAX({col_name}) FROM {table_name}), 1),
                        true
                    )
                    """
                ),
            )


def migrate(source_url: str, target_url: str, replace: bool, sync_rules: bool) -> dict:
    source_engine = _build_engine(source_url)
    target_engine = _build_engine(target_url)
    Base.metadata.create_all(bind=target_engine)

    if replace:
        _truncate_target(target_engine)

    inserted = {}
    failures = {}
    def _insert_rows_safely(conn, table, rows: list[dict]) -> tuple[int, int]:
        if not rows:
            return 0, 0
        rows = [_sanitize_row_for_table(table, r) for r in rows]
        chunk_size = 100
        inserted = 0
        failed = 0
        first_error = None
        total = len(rows)
        for i in range(0, total, chunk_size):
            chunk = rows[i:i + chunk_size]
            try:
                with conn.begin_nested():
                    conn.execute(table.insert(), chunk)
                inserted += len(chunk)
            except Exception:
                # Fallback to single-row inserts for unstable SSL/network links.
                for row in chunk:
                    try:
                        with conn.begin_nested():
                            conn.execute(table.insert(), row)
                        inserted += 1
                    except Exception as ex:
                        if first_error is None:
                            first_error = ex
                        failed += 1
                        continue
            if (i // chunk_size) % 10 == 0 or inserted == total:
                print(f"  {table.name}: {min(i + chunk_size, total)}/{total}")
        if first_error is not None:
            print(f"  {table.name}: first error -> {first_error}")
        return inserted, failed

    for table in Base.metadata.sorted_tables:
        rows = _rows_for_table(source_engine, table)
        if not rows:
            inserted[table.name] = 0
            failures[table.name] = 0
            continue
        with target_engine.begin() as conn:
            ok, bad = _insert_rows_safely(conn, table, rows)
            inserted[table.name] = ok
            failures[table.name] = bad
        print(f"migrated {table.name}: {inserted[table.name]}")

    _reset_postgres_sequences(target_engine)

    sync_summary = None
    if sync_rules:
        Session = sessionmaker(bind=target_engine, autocommit=False, autoflush=False)
        db = Session()
        try:
            sync_summary = sync_existing_accounts(
                db,
                apply_legacy_student_approval_rollback=True,
                sync_firebase_claims=True,
            )
        finally:
            db.close()

    total_rows = sum(inserted.values())
    return {"tables": inserted, "failures": failures, "total_rows": total_rows, "sync_summary": sync_summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Certora data from local SQLite to target database.")
    parser.add_argument("--source-sqlite", default="certora.db", help="Path to local SQLite DB file (default: certora.db)")
    parser.add_argument(
        "--target-url",
        default=os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="Target SQLAlchemy database URL. Defaults to TARGET_DATABASE_URL or DATABASE_URL.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete target data before inserting migrated rows.",
    )
    parser.add_argument(
        "--sync-rules",
        action="store_true",
        help="Run account rule sync + Firebase claims sync after migration.",
    )
    args = parser.parse_args()

    if not args.target_url:
        raise SystemExit("Missing target DB URL. Pass --target-url or set TARGET_DATABASE_URL.")

    source_path = Path(args.source_sqlite)
    if not source_path.exists():
        raise SystemExit(f"Source SQLite file not found: {source_path}")

    source_url = f"sqlite:///{source_path.resolve().as_posix()}"
    summary = migrate(source_url, args.target_url, replace=args.replace, sync_rules=args.sync_rules)

    print("Migration complete")
    print(f"Total rows migrated: {summary['total_rows']}")
    for table_name, count in summary["tables"].items():
        failed = int(summary.get("failures", {}).get(table_name, 0))
        print(f"  {table_name}: {count} (failed: {failed})")
    if summary["sync_summary"] is not None:
        print("Account sync summary:")
        for key, value in summary["sync_summary"].items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
