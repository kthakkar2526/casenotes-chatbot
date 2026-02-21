"""
database.py — SQLAlchemy async engine, session factory, and base class.

WHY ASYNC?
  FastAPI is an async framework.  Using an async SQLAlchemy engine lets
  database queries yield control back to the event loop while waiting for
  network I/O, so the server can handle other requests in parallel without
  threads.

ASYNCPG vs PSYCOPG2 URL DIFFERENCES:
  Neon's connection string uses psycopg2/libpq conventions:
    ?sslmode=require&channel_binding=require
  asyncpg does NOT accept these as URL query params — it raises:
    TypeError: connect() got an unexpected keyword argument 'sslmode'
  The fix: strip those params from the URL and pass ssl=True via
  connect_args instead.  _prepare_asyncpg_url() handles this automatically
  so the DATABASE_URL in .env can be copied straight from Neon's dashboard.

HOW IT FLOWS:
  1. `engine`           – single async engine backed by asyncpg.
  2. `AsyncSessionLocal`– session factory; each HTTP request gets its own
                          short-lived session via the `get_db` dependency.
  3. `Base`             – declarative base that all ORM models inherit from.
  4. `get_db()`         – FastAPI dependency that opens a session, yields it,
                          then commits (or rolls back on error) and closes it.
"""

from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ------------------------------------------------------------------ #
# URL normalisation for asyncpg
# ------------------------------------------------------------------ #
def _prepare_asyncpg_url(url: str) -> tuple[str, dict]:
    """
    Convert a Neon/psycopg2-style DATABASE_URL to one asyncpg accepts.

    Specifically:
      - Removes `sslmode` and `channel_binding` query params (asyncpg
        does not understand libpq keywords passed as URL params).
      - Returns a `connect_args` dict with `ssl=True` when sslmode was
        'require', 'verify-ca', or 'verify-full'.

    Args:
        url: Raw DATABASE_URL from .env (postgresql+asyncpg://...).

    Returns:
        (clean_url, connect_args) — pass both to create_async_engine().
    """
    parsed = urlparse(url)

    # parse_qs returns {key: [value, ...]} — we only ever have one value
    params = parse_qs(parsed.query, keep_blank_values=True)

    # Pull out the libpq-specific params that asyncpg can't handle
    sslmode_values = params.pop("sslmode", ["disable"])
    params.pop("channel_binding", None)

    sslmode = sslmode_values[0] if sslmode_values else "disable"

    # Rebuild the URL without those params
    new_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=new_query))

    # For asyncpg, SSL is enabled by passing ssl=True (or an ssl.SSLContext)
    # in connect_args rather than as a URL keyword.
    connect_args: dict = {}
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True

    return clean_url, connect_args


_db_url, _connect_args = _prepare_asyncpg_url(settings.DATABASE_URL)


# ------------------------------------------------------------------ #
# Engine
# ------------------------------------------------------------------ #
# echo=False in production — flip to True locally to see SQL statements.
# pool_pre_ping=True tests stale connections before use, preventing
# "server closed the connection unexpectedly" errors on long-idle Neon
# serverless instances.
engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
)

# ------------------------------------------------------------------ #
# Session factory
# ------------------------------------------------------------------ #
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit
    autoflush=False,
    autocommit=False,
)


# ------------------------------------------------------------------ #
# Declarative base
# ------------------------------------------------------------------ #
class Base(DeclarativeBase):
    """All ORM models inherit from this class."""
    pass


# ------------------------------------------------------------------ #
# FastAPI dependency
# ------------------------------------------------------------------ #
async def get_db():
    """
    Yield an async SQLAlchemy session for the duration of one HTTP request.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...

    The `async with` block ensures the session is always closed, even if
    the route raises an exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()   # auto-commit on clean exit
        except Exception:
            await session.rollback() # roll back on any error
            raise
