import logging
import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.core.config import settings

logger = logging.getLogger("reelsearch.database")

_db_pool: pool.ThreadedConnectionPool = None


def get_connection_params():
    return {
        "host": settings.PG_HOST,
        "port": settings.PG_PORT,
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "dbname": settings.PG_DATABASE,
        "connect_timeout": 5,
    }


def init_db_pool(minconn=4, maxconn=20):
    global _db_pool
    if _db_pool is None:
        try:
            if settings.DATABASE_URL:
                _db_pool = pool.ThreadedConnectionPool(minconn, maxconn, dsn=settings.DATABASE_URL)
            else:
                params = get_connection_params()
                _db_pool = pool.ThreadedConnectionPool(minconn, maxconn, **params)
            logger.info(f"PostgreSQL connection pool initialized with minconn={minconn}, maxconn={maxconn}.")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL connection pool: {e}")
            raise e
    return _db_pool


def close_db_pool():
    global _db_pool
    if _db_pool is not None:
        _db_pool.closeall()
        _db_pool = None
        logger.info("PostgreSQL connection pool closed.")


@contextmanager
def get_db_connection():
    global _db_pool
    if _db_pool is None:
        init_db_pool()

    conn = None
    try:
        conn = _db_pool.getconn()
        # Verify connection is still open (Neon auto-suspends compute when idle)
        if conn.closed != 0:
            _db_pool.putconn(conn, close=True)
            conn = _db_pool.getconn()
    except Exception as e:
        logger.warning(f"Connection pool acquisition issue: {e}. Attempting pool recovery...")
        try:
            close_db_pool()
            init_db_pool()
            conn = _db_pool.getconn()
        except Exception as retry_err:
            logger.error(f"Failed to recover PostgreSQL connection pool: {retry_err}")
            raise retry_err

    is_broken = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as conn_err:
        is_broken = True
        logger.warning(f"PostgreSQL connection error during operation: {conn_err}")
        raise
    finally:
        if conn is not None and _db_pool is not None:
            try:
                _db_pool.putconn(conn, close=is_broken)
            except Exception as put_err:
                logger.debug(f"Error returning connection to pool: {put_err}")


@contextmanager
def get_db_cursor(commit=False):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            if not conn.closed:
                try:
                    conn.rollback()
                except Exception as rb_err:
                    logger.debug(f"Database rollback error: {rb_err}")
            raise
        finally:
            if not cursor.closed:
                try:
                    cursor.close()
                except Exception:
                    pass


def run_migrations():
    """Initializes schema if not already present."""
    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "migrations", "schema.sql"
    )
    if not os.path.exists(migration_path):
        logger.warning(f"Migration file not found at {migration_path}")
        return

    logger.info("Running database schema migrations...")
    with open(migration_path, "r", encoding="utf-8") as f:
        sql = f.read()

    with get_db_cursor(commit=True) as cursor:
        cursor.execute(sql)
    logger.info("Database schema migrations executed successfully.")
