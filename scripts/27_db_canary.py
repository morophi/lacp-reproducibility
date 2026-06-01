#!/usr/bin/env python3
import os

import pymysql


password = os.environ["LACP_DB_PASSWORD"]
conn = pymysql.connect(
    host="10.1.1.130",
    user="morophi",
    password=password,
    database="lacp_db",
    charset="utf8mb4",
)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        print(f"db_canary={cur.fetchone()[0]}")
finally:
    conn.close()
