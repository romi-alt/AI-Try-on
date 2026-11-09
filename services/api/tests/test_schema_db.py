"""Constraint and cascade checks against a real Postgres.

Needs a migrated database (`make migrate`); skipped automatically when none is reachable.
Every test runs inside a transaction that is rolled back.
"""

import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models import Cart, CartItem, KioskSession, Product, ProductCategory, TryOnJob


@pytest.fixture
def db():
    try:
        conn = engine.connect()
    except OperationalError:
        pytest.skip("Postgres not reachable")
    migrated = "cart_items" in inspect(conn).get_table_names()
    conn.rollback()  # end the transaction autobegun by inspect()
    if not migrated:
        conn.close()
        pytest.skip("database not migrated (run `make migrate`)")
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


def _product(**kw) -> Product:
    base = dict(
        name=f"test-{uuid.uuid4().hex[:8]}",
        category=ProductCategory.top,
        price_pkr=1000,
        stock=1,
        garment_image_url="http://example.test/x.png",
    )
    return Product(**{**base, **kw})


def _expect_violation(db: Session, obj) -> None:
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(obj)
            db.flush()


def test_product_defaults_and_jsonb_roundtrip(db):
    p = _product(sizes=["S", "M"], colors=[{"name": "Ivory", "hex": "#efe6d2"}])
    db.add(p)
    db.flush()
    db.expire(p)
    assert p.sizes == ["S", "M"]
    assert p.colors[0]["name"] == "Ivory"
    assert p.sale_price_pkr is None
    assert p.created_at is not None


def test_product_check_constraints(db):
    _expect_violation(db, _product(price_pkr=1000, sale_price_pkr=1500))
    _expect_violation(db, _product(price_pkr=-1))
    _expect_violation(db, _product(stock=-1))


def test_product_embedding_cosine_search(db):
    near, far = [1.0] + [0.0] * 511, [0.0, 1.0] + [0.0] * 510
    a, b = _product(embedding=near), _product(embedding=far)
    db.add_all([a, b])
    db.flush()
    dist = Product.embedding.cosine_distance(near)
    rows = db.execute(select(Product.id, dist).where(Product.id.in_([a.id, b.id])).order_by(dist)).all()
    assert [r[0] for r in rows] == [a.id, b.id]
    assert rows[0][1] == pytest.approx(0.0, abs=1e-6)


def test_session_defaults_and_job_constraints(db):
    s = KioskSession()
    db.add(s)
    db.flush()
    assert s.consent_given is False

    ok = TryOnJob(session_id=s.id, product_ids=[uuid.uuid4(), uuid.uuid4()], person_image_key="capture/a.jpg")
    db.add(ok)
    db.flush()
    db.expire(ok)
    assert ok.status == "queued" and ok.progress == 0 and len(ok.product_ids) == 2

    _expect_violation(db, TryOnJob(session_id=s.id, product_ids=[], person_image_key="capture/b.jpg"))
    _expect_violation(
        db, TryOnJob(session_id=s.id, product_ids=[uuid.uuid4()], person_image_key="c", progress=101)
    )


def test_cart_rules_and_cascades(db):
    s, p = KioskSession(), _product()
    db.add_all([s, p])
    db.flush()
    cart = Cart(session_id=s.id)
    db.add(cart)
    db.flush()
    item = CartItem(cart_id=cart.id, product_id=p.id, size="M", color="Ivory", quantity=2)
    db.add(item)
    db.flush()

    _expect_violation(db, Cart(session_id=s.id))  # one cart per session
    _expect_violation(db, CartItem(cart_id=cart.id, product_id=p.id, quantity=0))

    with pytest.raises(IntegrityError):  # RESTRICT: product in a cart cannot be deleted
        with db.begin_nested():
            db.delete(p)
            db.flush()

    db.delete(s)  # session -> cart -> items cascade
    db.flush()
    assert db.scalar(select(Cart.id).where(Cart.id == cart.id)) is None
    assert db.scalar(select(CartItem.id).where(CartItem.id == item.id)) is None
