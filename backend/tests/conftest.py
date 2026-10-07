import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from sqlalchemy import create_engine
from core.models import Base
from core.service import Workbench
from core.support import Actor, load_config, init_db

OP, AP, AP2, ADMIN = Actor("olivia", "operator"), Actor("alan", "approver"), Actor("amy", "approver"), Actor("root", "admin")


import os, uuid


def new_db_url(tmp_path, name="t.db"):
    """SQLite by default; set TEST_PG_URI (admin URI of a PostgreSQL server) to run the same tests on PostgreSQL."""
    admin = os.environ.get("TEST_PG_URI")
    if not admin:
        return f"sqlite:///{tmp_path/name}"
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    db = "t_" + uuid.uuid4().hex[:12]
    u = make_url(admin).set(drivername="postgresql+psycopg2")
    e = create_engine(u, isolation_level="AUTOCOMMIT")
    with e.connect() as conn: conn.execute(text(f'CREATE DATABASE "{db}"'))
    e.dispose()
    return u.set(database=db).render_as_string(hide_password=False)


@pytest.fixture
def wb(tmp_path):
    from core.support import make_engine
    eng = make_engine(new_db_url(tmp_path))
    init_db(eng)
    return Workbench(eng, load_config(), str(tmp_path / "mock"))


def make(wb, scenario="clean", src_faults=None, tgt_faults=None, **settings):
    p = wb.create_demo(OP, scenario)
    if src_faults or tgt_faults or settings:
        with wb.session() as s:
            pr = wb._project(s, p.id)
            if src_faults: pr.source = {**pr.source, "faults": src_faults}
            if tgt_faults: pr.target = {**pr.target, "faults": tgt_faults}
        if settings: wb.update_settings(OP, p.id, **settings)
        wb.run_connectivity(OP, p.id); wb.collect_inventory(OP, p.id); wb.assess(OP, p.id)
    return p.id
