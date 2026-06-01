#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

from logger import AsyncMariaDBLogger, CompositeLogger, JSONLLogger


class FakeDBLogger:
    def __init__(self):
        self.rows = []
        self.closed = False

    def log_turn(self, run_id, row):
        time.sleep(0.01)
        self.rows.append((run_id, row))

    def close(self):
        self.closed = True


def test_async_logger_flush_waits_for_queued_rows():
    fake = FakeDBLogger()
    logger = AsyncMariaDBLogger(fake, queue_maxsize=10, flush_timeout_s=1.0)
    try:
        logger.log_turn("run-1", {"run_id": "run-1", "turn_no": 1})
        logger.log_turn("run-1", {"run_id": "run-1", "turn_no": 2})
        logger.flush()
        assert [row["turn_no"] for _run_id, row in fake.rows] == [1, 2]
    finally:
        logger.close()


def test_composite_close_closes_async_db_logger(tmp_path):
    fake = FakeDBLogger()
    async_db = AsyncMariaDBLogger(fake, queue_maxsize=10, flush_timeout_s=1.0)
    logger = CompositeLogger(JSONLLogger(str(tmp_path)), async_db)
    logger.log_turn("run-2", {"run_id": "run-2", "turn_no": 1})
    logger.close()
    assert fake.closed is True
    assert fake.rows[0][1]["turn_no"] == 1
