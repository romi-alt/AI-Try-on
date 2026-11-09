import pytest
from sqlalchemy import select

from app.models import ProcessingStatus, Product
from app.services import csv_import
from tests.helpers import ADMIN_HEADERS, make_product

HEADER = "sku,name,category,price_pkr,sale_price_pkr,sizes,colors,stock,image_url\n"
IMG = "http://example.test/a.png"


def csv_bytes(*lines: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(lines) + "\n").encode()


async def post(api, body: bytes, **params):
    return await api.post(
        "/products/import",
        content=body,
        params=params,
        headers={**ADMIN_HEADERS, "Content-Type": "text/csv"},
    )


# --- the parser (no database) ----------------------------------------------------------------


def test_parser_reads_every_column():
    rows = csv_import.parse_csv(
        csv_bytes(f"K1,Linen Shirt,TOP,4500,3500,S|M|L,Ivory:#efe6d2|Black:#000000,12,{IMG}")
    )
    assert len(rows) == 1
    r = rows[0]
    assert (r.line, r.sku, r.errors) == (2, "K1", [])
    assert r.values["category"].value == "top"
    assert r.values["sizes"] == ["S", "M", "L"]
    assert r.values["colors"] == [{"name": "Ivory", "hex": "#efe6d2"}, {"name": "Black", "hex": "#000000"}]
    assert (r.values["price_pkr"], r.values["sale_price_pkr"], r.values["stock"]) == (4500, 3500, 12)


def test_parser_accepts_a_bom_blank_lines_and_thousands_separators():
    data = b"\xef\xbb\xbf" + csv_bytes('K1,Shirt,top,"4,500",,S,,1,' + IMG, ",,,,,,,,", "K2,B,bag,10,,,,,")
    rows = csv_import.parse_csv(data)
    assert [r.line for r in rows] == [2, 4]  # the blank line is skipped, numbering is the file's
    assert rows[0].values["price_pkr"] == 4500


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("K1,Shirt,jacket,100,,,,,", "category 'jacket' is not one of"),
        ("K1,Shirt,top,12.5,,,,,", "price_pkr must be a whole number"),
        ("K1,Shirt,top,-5,,,,,", "price_pkr cannot be negative"),
        ("K1,Shirt,top,100,,,Red,,", "must look like Name:#rrggbb"),
        ("K1,Shirt,top,100,,,Red:red,,", "must look like Name:#rrggbb"),
        ("K1,Shirt,top,100,,,,,ftp://x/y.png", "image_url must be an http(s) address"),
        ("K1,Shirt,top,100,,,,many,", "stock must be a whole number"),
    ],
)
def test_parser_reports_cell_problems_on_the_row(line, message):
    (row,) = csv_import.parse_csv(csv_bytes(line))
    assert any(message in e for e in row.errors), row.errors


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"foo,bar\n1,2\n", "No known columns"),
        (b"sku,sku\nA,B\n", "repeated column"),
        (b"\xff\xfe\x00bad", "UTF-8"),
        (b"sku,name\n" + b"x,y\n" * (csv_import.MAX_ROWS + 1), "More than"),
        (b"sku,name\n" + b"x" * (csv_import.MAX_BYTES + 1), "larger than"),
    ],
)
def test_parser_refuses_unusable_files(data, message):
    with pytest.raises(csv_import.CsvError, match=message):
        csv_import.parse_csv(data)


# --- the route ---------------------------------------------------------------------------------


async def test_import_requires_the_admin_key(api):
    r = await api.post("/products/import", content=csv_bytes(f"K1,A,top,1,,,,,{IMG}"))
    assert r.status_code == 401


async def test_creates_and_updates_by_sku(api, adb, monkeypatch):
    queued = []
    monkeypatch.setattr(
        "app.api.products.enqueue_embeddings",
        lambda ids, only_missing: queued.append((ids, only_missing)) or "job-1",
    )
    old = await make_product(adb, sku="IMP-OLD", name="Old name", price_pkr=2000, stock=5)

    r = await post(
        api,
        csv_bytes(
            f"IMP-NEW,New shirt,top,3000,2500,S|M,Ivory:#efe6d2,7,{IMG}",
            "IMP-OLD,,,2200,,,,9,",  # empty cells keep what is there
        ),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["applied"], body["created"], body["updated"], body["error_count"]) == (True, 1, 1, 0)
    assert [x["action"] for x in body["rows"]] == ["create", "update"]
    await adb.refresh(old)
    assert (old.name, old.price_pkr, old.stock) == ("Old name", 2200, 9)
    new = await adb.scalar(select(Product).where(Product.sku == "IMP-NEW"))
    assert (new.name, new.sale_price_pkr, new.sizes, new.stock) == ("New shirt", 2500, ["S", "M"], 7)
    assert body["embedding_job_id"] == "job-1"
    assert queued == [([new.id], False)]  # the new product only: the update did not touch the picture


async def test_none_clears_a_sale_price(api, adb):
    p = await make_product(adb, sku="IMP-SALE", price_pkr=2000, sale_price_pkr=1500)
    r = await post(api, csv_bytes("IMP-SALE,,,,none,,,,"), embed="false")
    assert r.json()["applied"] is True
    await adb.refresh(p)
    assert p.sale_price_pkr is None


async def test_a_new_picture_resets_the_cutout_and_requeues_the_embedding(api, adb, monkeypatch):
    queued = []
    monkeypatch.setattr(
        "app.api.products.enqueue_embeddings", lambda ids, only_missing: queued.append(ids) or "j"
    )
    p = await make_product(
        adb,
        sku="IMP-PIC",
        garment_mask_url="http://example.test/mask.png",
        garment_original_url="http://example.test/orig.png",
        processing_status=ProcessingStatus.done,
    )
    r = await post(api, csv_bytes(f"IMP-PIC,,,,,,,,{IMG}"))
    assert r.json()["applied"] is True
    await adb.refresh(p)
    assert p.garment_image_url == IMG
    assert (p.garment_mask_url, p.garment_original_url, p.processing_status) == (
        None,
        None,
        ProcessingStatus.idle,
    )
    assert queued == [[p.id]]


async def test_one_bad_row_saves_nothing_and_every_row_is_reported(api, adb):
    before = await adb.scalar(select(Product.id).where(Product.sku == "IMP-GOOD"))
    r = await post(
        api,
        csv_bytes(
            f"IMP-GOOD,Good,top,100,,,,,{IMG}",
            f"IMP-BAD,Bad,top,100,500,,,,{IMG}",  # sale above price
            "IMP-NOIMG,No image,top,100,,,,,",  # a new product needs an image
            "IMP-NOPRICE,,top,,,,,,",  # and a name and a price
        ),
    )

    assert r.status_code == 200
    body = r.json()
    assert (body["applied"], body["error_count"], body["created"]) == (False, 3, 1)
    assert [x["action"] for x in body["rows"]] == ["create", "error", "error", "error"]
    assert "sale_price_pkr cannot exceed price_pkr" in body["rows"][1]["errors"][0]
    assert any("garment_image_url" in e for e in body["rows"][2]["errors"])
    assert {"name", "price_pkr"} <= {e.split()[0] for e in body["rows"][3]["errors"]}
    assert await adb.scalar(select(Product.id).where(Product.sku == "IMP-GOOD")) == before  # not created


async def test_dry_run_reports_without_saving(api, adb, monkeypatch):
    monkeypatch.setattr("app.api.products.enqueue_embeddings", lambda *a, **k: pytest.fail("queued"))
    r = await post(api, csv_bytes(f"IMP-DRY,Dry,top,100,,,,,{IMG}"), dry_run="true")
    body = r.json()
    assert (body["dry_run"], body["applied"], body["created"]) == (True, False, 1)
    assert await adb.scalar(select(Product.id).where(Product.sku == "IMP-DRY")) is None


async def test_a_sku_twice_in_the_file_is_an_error(api):
    r = await post(
        api, csv_bytes(f"IMP-TWICE,A,top,1,,,,,{IMG}", f"IMP-TWICE,B,top,2,,,,,{IMG}"), dry_run="true"
    )
    body = r.json()
    assert body["error_count"] == 1
    assert "more than once" in body["rows"][1]["errors"][0]


async def test_rows_without_a_sku_always_create(api, adb):
    r = await post(api, csv_bytes(f",One,top,1,,,,,{IMG}", f",One,top,1,,,,,{IMG}"), embed="false")
    assert r.json()["created"] == 2


async def test_an_unreadable_file_is_422(api):
    r = await post(api, b"")
    assert r.status_code == 422
    assert "empty" in r.json()["detail"]


async def test_an_oversize_file_is_413(api):
    r = await post(api, b"sku\n" + b"x\n" * csv_import.MAX_BYTES)
    assert r.status_code == 413


async def test_embedding_queue_trouble_does_not_undo_the_import(api, adb, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.api.products.enqueue_embeddings", boom)
    r = await post(api, csv_bytes(f"IMP-Q,Q,top,1,,,,,{IMG}"))
    assert r.status_code == 200
    assert r.json()["applied"] is True and r.json()["embedding_job_id"] is None
    assert await adb.scalar(select(Product.id).where(Product.sku == "IMP-Q")) is not None
