import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

DATA_DIR = Path(os.getenv("FIRM_MANAGER_DATA_DIR", Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLALCHEMY_DATABASE_URL = os.getenv(
    "FIRM_MANAGER_DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'db.sqlite').as_posix()}"
)

_is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
if _is_sqlite:
    # SQLite has a single writer.  Give short transactions enough time to
    # queue under normal office concurrency instead of failing at the default
    # five-second busy timeout.
    _connect_args["timeout"] = float(os.getenv("FIRM_MANAGER_SQLITE_TIMEOUT", "30"))

_engine_options = {
    "connect_args": _connect_args,
    "pool_pre_ping": True,
}
if _is_sqlite and ":memory:" not in SQLALCHEMY_DATABASE_URL:
    # A SQLite file has one writer but can serve many readers.  NullPool keeps
    # each request from occupying one of SQLAlchemy's small default pool, which
    # otherwise becomes a bottleneck when many authenticated requests overlap.
    _engine_options["poolclass"] = NullPool

engine = create_engine(SQLALCHEMY_DATABASE_URL, **_engine_options)


if _is_sqlite and engine.url.database != ":memory:":
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            busy_timeout_ms = int(float(os.getenv("FIRM_MANAGER_SQLITE_TIMEOUT", "30")) * 1000)
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
