"""Bulk product import from CSV: parsing and validation, with no database.

Columns (header names are case-insensitive, extra columns are ignored):

    sku, name, category, price_pkr, sale_price_pkr, sizes, colors, stock, image_url

- `sku` is the key: a row whose SKU already exists updates that product, any other row creates one. A row
  without a SKU always creates.
- On an update an empty cell means "leave as it is". To remove a sale price write `none`.
- `sizes` are separated by `|` (`S|M|L`), `colors` are `Name:#hex` separated by `|`
  (`Ivory:#efe6d2|Black:#000000`).
- A new product needs `name`, `category`, `price_pkr` and `image_url`.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.models.product import ProductCategory
from app.schemas.product import ColorOption

MAX_ROWS = 1000
MAX_BYTES = 1024 * 1024
KNOWN_COLUMNS = (
    "sku",
    "name",
    "category",
    "price_pkr",
    "sale_price_pkr",
    "sizes",
    "colors",
    "stock",
    "image_url",
)
CLEAR_WORDS = {"none", "null", "-"}
_LIST_SPLIT = re.compile(r"[|;]")


class CsvError(ValueError):
    """The file as a whole cannot be read (bad encoding, no header, too big)."""


@dataclass
class Row:
    line: int  # 1-based line in the file; the header is line 1
    sku: str | None
    # Fields given in this row, named as on `Product`; absent keys mean "not given".
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _int(raw: str, name: str) -> int:
    try:
        n = int(raw.replace(",", "").strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number of rupees, got {raw!r}") from None
    if n < 0:
        raise ValueError(f"{name} cannot be negative")
    return n


def _colors(raw: str) -> list[dict]:
    out = []
    for part in filter(None, (p.strip() for p in _LIST_SPLIT.split(raw))):
        name, sep, hex_ = part.rpartition(":")
        if not sep or not name.strip():
            raise ValueError(f"colour {part!r} must look like Name:#rrggbb")
        try:
            out.append(ColorOption(name=name.strip(), hex=hex_.strip()).model_dump())
        except ValidationError:
            raise ValueError(f"colour {part!r} must look like Name:#rrggbb") from None
    return out


def _row_values(cells: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if cells.get("name"):
        values["name"] = cells["name"]
    if cells.get("category"):
        try:
            values["category"] = ProductCategory(cells["category"].lower())
        except ValueError:
            allowed = ", ".join(c.value for c in ProductCategory)
            raise ValueError(f"category {cells['category']!r} is not one of: {allowed}") from None
    if cells.get("price_pkr"):
        values["price_pkr"] = _int(cells["price_pkr"], "price_pkr")
    if cells.get("sale_price_pkr"):
        raw = cells["sale_price_pkr"]
        values["sale_price_pkr"] = None if raw.lower() in CLEAR_WORDS else _int(raw, "sale_price_pkr")
    if cells.get("stock"):
        values["stock"] = _int(cells["stock"], "stock")
    if cells.get("sizes"):
        raw = cells["sizes"]
        values["sizes"] = (
            [] if raw.lower() in CLEAR_WORDS else [s.strip() for s in _LIST_SPLIT.split(raw) if s.strip()]
        )
    if cells.get("colors"):
        raw = cells["colors"]
        values["colors"] = [] if raw.lower() in CLEAR_WORDS else _colors(raw)
    if cells.get("image_url"):
        url = cells["image_url"]
        if not re.match(r"^https?://\S+$", url):
            raise ValueError("image_url must be an http(s) address")
        values["garment_image_url"] = url
    return values


def parse_csv(data: bytes) -> list[Row]:
    """Read the file into rows.

    Problems in one row go in that row's `errors`; problems with the file as a whole raise `CsvError`.
    """
    if len(data) > MAX_BYTES:
        raise CsvError(f"The file is larger than {MAX_BYTES // 1024} KB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvError("The file must be UTF-8 text (in Excel: Save As, CSV UTF-8)") from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvError("The file is empty") from None
    names = [h.strip().lower() for h in header]
    if not any(n in KNOWN_COLUMNS for n in names):
        raise CsvError(f"No known columns in the header. Expected: {', '.join(KNOWN_COLUMNS)}")
    if len(set(names)) != len(names):
        raise CsvError("The header has a repeated column name")

    rows: list[Row] = []
    for line, record in enumerate(reader, start=2):
        if not any(cell.strip() for cell in record):
            continue  # blank line
        if len(rows) >= MAX_ROWS:
            raise CsvError(f"More than {MAX_ROWS} rows: split the file")
        cells = {
            n: (record[i].strip() if i < len(record) else "")
            for i, n in enumerate(names)
            if n in KNOWN_COLUMNS
        }
        row = Row(line=line, sku=cells.get("sku") or None)
        if row.sku and len(row.sku) > 64:
            row.errors.append("sku is longer than 64 characters")
        try:
            row.values = _row_values(cells)
        except ValueError as e:
            row.errors.append(str(e))
        rows.append(row)
    return rows
