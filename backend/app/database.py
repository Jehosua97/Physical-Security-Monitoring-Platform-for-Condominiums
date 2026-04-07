import os
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://security_ops:security_ops@postgres:5432/security_ops",
)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
