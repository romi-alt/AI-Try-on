"""The worker's table definitions must match what the API's Alembic migrations create.

Runs against the real (migrated) database and skips when it is not available.
"""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from worker import db
from worker.config import settings


@pytest.fixture(scope="module")
def real_db():
    engine = create_engine(settings.database_url)
    try:
        names = inspect(engine).get_table_names()
    except OperationalError:
        pytest.skip("Postgres not reachable")
    if "tryon_jobs" not in names or "products" not in names:
        pytest.skip("database not migrated (run `make migrate`)")
    yield engine
    engine.dispose()


@pytest.mark.parametrize("table", [db.tryon_jobs, db.products], ids=lambda t: t.name)
def test_every_column_the_worker_uses_exists_with_a_compatible_type(real_db, table):
    pg = postgresql.dialect()
    actual = {c["name"]: c for c in inspect(real_db).get_columns(table.name)}
    for column in table.columns:
        assert column.name in actual, f"{table.name}.{column.name} is missing from the migrated schema"
        ours = column.type.compile(dialect=pg)
        theirs = actual[column.name]["type"].compile(dialect=pg)
        assert ours == theirs, f"{table.name}.{column.name}: worker declares {ours}, database has {theirs}"
        if not column.nullable:
            assert not actual[column.name]["nullable"], f"{table.name}.{column.name} should be NOT NULL"


def test_enum_values_match_the_database(real_db):
    with real_db.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
            "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid GROUP BY t.typname"
        ).all()
    enums = {name: tuple(labels) for name, labels in rows}
    assert enums["job_status"] == db.JOB_STATUSES
    assert enums["product_category"] == db.PRODUCT_CATEGORIES


def test_the_embedding_column_the_worker_writes_is_a_512_dimension_vector(real_db):
    with real_db.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
            "WHERE a.attrelid = 'products'::regclass AND a.attname = 'embedding'"
        ).first()
    assert row is not None and row[0] == "vector(512)"


def test_processing_status_values_match_the_database(real_db):
    with real_db.connect() as conn:
        labels = conn.exec_driver_sql(
            "SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder) FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typname = 'processing_status'"
        ).scalar()
    assert tuple(labels) == db.PROCESSING_STATUSES
