import threading
import time
from contextlib import contextmanager

from mysql.connector import Error as MySQLError, pooling
from mysql.connector.errors import PoolError

import config
from errors import ApiError

_pool, _lock = None, threading.Lock()


def get_connection():
    global _pool
    with _lock:
        if _pool is None:
            _pool = pooling.MySQLConnectionPool(pool_name="abc", pool_size=32, pool_reset_session=True,
                                                charset="utf8mb4", collation="utf8mb4_unicode_ci",
                                                autocommit=True, **config.DB)
    deadline = time.monotonic() + 30
    while True:
        try:
            conn = _pool.get_connection()
            break
        except PoolError:  # the pool never blocks: wait for a free connection when concurrency > pool size
            if time.monotonic() > deadline:
                raise
            time.sleep(0.005)
    cur = conn.cursor()
    cur.execute("SET time_zone='+00:00', SESSION transaction_isolation='READ-COMMITTED'")
    cur.close()
    return conn


@contextmanager
def _cursor():
    conn = get_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def transaction():
    with _cursor() as (conn, cur):
        cur.execute("START TRANSACTION")
        try:
            yield cur
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


def run_transaction(fn, retries=3):
    """Run fn(cur) in one transaction; whole fn is retried on deadlock (1213) / lock timeout (1205).
    `retries` = total attempts; sleeps 0.05, 0.10, ... between them (§8.7)."""
    for attempt in range(retries):
        try:
            with transaction() as cur:
                return fn(cur)
        except MySQLError as e:
            if getattr(e, "errno", None) not in (1213, 1205):
                raise
            if attempt < retries - 1:
                time.sleep(0.05 * 2 ** attempt)
    raise ApiError("TXN_RETRY_EXHAUSTED", "Could not complete the transaction due to contention. Please retry.")


def fetch_all(sql, params=None):
    with _cursor() as (_, cur):
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql, params=None):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    with _cursor() as (_, cur):
        cur.execute(sql, params)
        return cur.lastrowid
