"""Alembic environment. SQLite needs batch mode for schema changes."""

from alembic import context
from sqlalchemy import create_engine

from app.core.db import Base
from app.models import entities  # noqa: F401 - registers the tables on Base.metadata

target_metadata = Base.metadata
url = context.config.get_main_option("sqlalchemy.url")


def run_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
