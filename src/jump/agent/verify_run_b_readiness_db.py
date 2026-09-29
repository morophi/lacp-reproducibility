#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Verify Run B readiness DB evidence in lacp_db_final."""

from __future__ import annotations

import json
import os
import sys

import pymysql


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_run_b_readiness_db.py RUN_ID")
    run_id = sys.argv[1]
    if os.environ.get("LACP_DB_NAME") != "lacp_db_final":
        raise SystemExit(f"refusing DB check outside lacp_db_final: {os.environ.get('LACP_DB_NAME')!r}")
    conn = pymysql.connect(
        host=os.environ.get("LACP_DB_HOST", "dblog"),
        user=os.environ.get("LACP_DB_USER", "morophi"),
        password=os.environ["LACP_DB_PASSWORD"],
        database=os.environ["LACP_DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, run_id, condition_name, run_mode FROM experiment_runs WHERE run_id=%s", (run_id,))
            run = cur.fetchone()
            if not run:
                raise SystemExit(f"missing experiment_run row: {run_id}")
            run_pk = run["id"]
            queries = {
                "turn_node_logs": "SELECT COUNT(*) AS n FROM turn_node_logs WHERE experiment_run_id=%s",
                "intervention_logs": "SELECT COUNT(*) AS n FROM intervention_logs i JOIN turn_node_logs t ON t.id=i.turn_node_log_id WHERE t.experiment_run_id=%s",
                "metric_logs": "SELECT COUNT(*) AS n FROM metric_logs m JOIN turn_node_logs t ON t.id=m.turn_node_log_id WHERE t.experiment_run_id=%s",
                "payload_audit_logs": "SELECT COUNT(*) AS n FROM payload_audit_logs p JOIN turn_node_logs t ON t.id=p.turn_node_log_id WHERE t.experiment_run_id=%s",
                "rag_retrieval_logs": "SELECT COUNT(*) AS n FROM rag_retrieval_logs g JOIN turn_node_logs t ON t.id=g.turn_node_log_id WHERE t.experiment_run_id=%s",
            }
            counts = {}
            for name, query in queries.items():
                cur.execute(query, (run_pk,))
                counts[name] = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT t.node, COUNT(*) AS n
                FROM rag_retrieval_logs g
                JOIN turn_node_logs t ON t.id = g.turn_node_log_id
                WHERE t.experiment_run_id=%s
                GROUP BY t.node
                ORDER BY t.node
                """,
                (run_pk,),
            )
            rag_by_node = {row["node"]: int(row["n"]) for row in cur.fetchall()}
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM rag_retrieval_logs g
                JOIN turn_node_logs t ON t.id = g.turn_node_log_id
                WHERE t.experiment_run_id=%s
                  AND g.returned_count = 3
                  AND JSON_LENGTH(g.retrieved_chunk_ids) = 3
                """,
                (run_pk,),
            )
            rag_topk3_rows = int(cur.fetchone()["n"])
    finally:
        conn.close()

    expected = {
        "turn_node_logs": 90,
        "intervention_logs": 90,
        "metric_logs": 90,
        "payload_audit_logs": 90,
        "rag_retrieval_logs": 60,
    }
    ok = counts == expected and rag_by_node == {"A": 30, "B": 30} and rag_topk3_rows == 60
    result = {
        "run_id": run_id,
        "run": run,
        "counts": counts,
        "expected": expected,
        "rag_by_node": rag_by_node,
        "rag_topk3_rows": rag_topk3_rows,
        "ok": ok,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
