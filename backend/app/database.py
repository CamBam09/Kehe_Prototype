"""
Database connection setup.

Defaults to a local SQLite file so the tool runs with zero external
dependencies out of the box. Point DATABASE_URL at a real Postgres
instance for production use, e.g.:

    export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/kehe_trends"

Postgres is the recommended production target because the search layer
(see search.py) is designed to grow into pgvector for embedding-based
semantic search once BGE-M3 is wired in.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/kehe_trends.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
