#!/usr/bin/env python3
"""Export every table in the LACP MariaDB database to CSV.

This is intended to run on dblog or another node that can reach MariaDB.
It reads credentials from ~/.lacp_db_env and writes a self-describing export
bundle containing CSV files, schema metadata, row counts, and SHA256 hashes.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any


SYSTEM_SCHEMAS = {"information_schema", "mysql", "performance_schema", "sys"}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed = shlex.split(value.strip())[0] if value.strip() else ""
        os.environ.setdefault(key.strip(), parsed)


def import_pymysql():
    vendor = Path.home() / ".local" / "share" / "lacp_python_vendor"
    if vendor.exists():
        sys.path.insert(0, str(vendor))
    import pymysql  # type: ignore

    return pymysql


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def export_relation(conn: Any, db_name: str, relation_name: str, out_path: Path) -> tuple[int, list[str]]:
    query = f"SELECT * FROM {quote_ident(db_name)}.{quote_ident(relation_name)}"
    with conn.cursor() as cur:
        cur.execute(query)
        headers = [item[0] for item in cur.description or []]
        row_count = 0
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    writer.writerow(["" if value is None else value for value in row])
                row_count += len(rows)
    return row_count, headers


def fetch_all_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        headers = [item[0] for item in cur.description or []]
        return [dict(zip(headers, row)) for row in cur.fetchall()]


def json_default(value: Any) -> str:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export all LACP DB tables and views to CSV.")
    parser.add_argument("--database", default=os.environ.get("LACP_DB_NAME", "lacp_db_final"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--include-views", action="store_true")
    args = parser.parse_args()

    load_env_file(Path.home() / ".lacp_db_env")
    pymysql = import_pymysql()
    password = os.environ.get("LACP_DB_PASSWORD") or os.environ.get("MYSQL_PWD")
    if not password:
        raise RuntimeError("Missing LACP_DB_PASSWORD/MYSQL_PWD in ~/.lacp_db_env or environment")

    out_dir = Path(args.out_dir).expanduser().resolve()
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    conn = pymysql.connect(
        host=os.environ.get("LACP_DB_HOST", "dblog"),
        port=int(os.environ.get("LACP_DB_PORT", "3306")),
        user=os.environ.get("LACP_DB_USER", "morophi"),
        password=password,
        database=args.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.SSCursor,
    )
    meta_conn = pymysql.connect(
        host=os.environ.get("LACP_DB_HOST", "dblog"),
        port=int(os.environ.get("LACP_DB_PORT", "3306")),
        user=os.environ.get("LACP_DB_USER", "morophi"),
        password=password,
        database=args.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
    )
    try:
        table_filter = "('BASE TABLE','VIEW')" if args.include_views else "('BASE TABLE')"
        relations = fetch_all_dicts(
            meta_conn,
            f"""
            SELECT table_name, table_type, engine,
                   COALESCE(table_rows, 0) AS approx_rows,
                   COALESCE(data_length + index_length, 0) AS total_bytes,
                   create_time, update_time
            FROM information_schema.tables
            WHERE table_schema=%s
              AND table_schema NOT IN ({",".join(["%s"] * len(SYSTEM_SCHEMAS))})
              AND table_type IN {table_filter}
            ORDER BY table_type, table_name
            """,
            (args.database, *sorted(SYSTEM_SCHEMAS)),
        )
        columns = fetch_all_dicts(
            meta_conn,
            """
            SELECT table_name, column_name, ordinal_position, column_type,
                   is_nullable, column_key, column_default, extra
            FROM information_schema.columns
            WHERE table_schema=%s
            ORDER BY table_name, ordinal_position
            """,
            (args.database,),
        )

        manifest: dict[str, Any] = {
            "exported_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "database": args.database,
            "host": os.environ.get("LACP_DB_HOST", "dblog"),
            "user": os.environ.get("LACP_DB_USER", "morophi"),
            "include_views": args.include_views,
            "relations": [],
        }

        for relation in relations:
            name = relation["table_name"]
            relation_type = relation["table_type"]
            csv_name = f"{name}.csv"
            csv_path = csv_dir / csv_name
            row_count, headers = export_relation(conn, args.database, name, csv_path)
            manifest["relations"].append(
                {
                    "name": name,
                    "type": relation_type,
                    "csv": f"csv/{csv_name}",
                    "row_count": row_count,
                    "columns": headers,
                    "sha256": sha256_file(csv_path),
                    "bytes": csv_path.stat().st_size,
                    "information_schema": relation,
                }
            )

        schema_path = out_dir / "schema_columns.json"
        schema_path.write_text(json.dumps(columns, ensure_ascii=False, default=json_default, indent=2), encoding="utf-8")
        manifest["schema_columns_json"] = {
            "path": "schema_columns.json",
            "sha256": sha256_file(schema_path),
            "bytes": schema_path.stat().st_size,
        }

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, default=json_default, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(manifest, ensure_ascii=False, default=json_default, indent=2, sort_keys=True))
    finally:
        conn.close()
        meta_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
