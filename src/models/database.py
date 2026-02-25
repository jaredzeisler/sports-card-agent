"""Database setup and session management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config.settings import get_settings


class Base(DeclarativeBase):
    pass


def get_engine(url: str | None = None):
    db_url = url or get_settings().database_url
    return create_engine(db_url, echo=False)


def get_session(url: str | None = None):
    engine = get_engine(url)
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(url: str | None = None):
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine
