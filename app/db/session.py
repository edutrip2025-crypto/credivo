from sqlalchemy import create_engine
from fastapi import HTTPException, status
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

DATABASE_CONFIG_ERROR: str | None = None
try:
    database_url = settings.resolved_database_url
except RuntimeError as exc:
    # Keep serverless import/static routes alive. DB-backed API routes fail explicitly via get_db().
    DATABASE_CONFIG_ERROR = str(exc)
    database_url = "sqlite:///:memory:"

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    if DATABASE_CONFIG_ERROR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DATABASE_CONFIG_ERROR,
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
