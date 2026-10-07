import os, sys
from pathlib import Path
from alembic import context
from sqlalchemy import create_engine
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL") or \
    f"sqlite:///{Path(__file__).resolve().parent.parent / 'epm_workbench.db'}"


def run():
    eng = create_engine(url)
    with eng.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True, render_as_batch=url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


run()
