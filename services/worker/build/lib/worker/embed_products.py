"""Compute FashionCLIP embeddings for the catalog.

    python -m worker.embed_products                 # every product
    python -m worker.embed_products --missing       # only products with no embedding yet
    python -m worker.embed_products --ids ID [ID ...]

Needs the `assets` extra (`pip install -e ".[assets]"`) and a migrated database. The first run downloads
the model.
"""

import argparse
import sys
import uuid

from worker.config import settings
from worker.embeddings import embed_products
from worker.logging_setup import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--missing", action="store_true", help="only products that have no embedding yet")
    parser.add_argument("--ids", nargs="+", type=uuid.UUID, metavar="ID", help="only these products")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args(argv)

    configure_logging(settings.log_level)
    report = embed_products(
        args.ids,
        only_missing=args.missing,
        batch_size=args.batch_size,
        progress=lambda done, total: print(f"\r{done}/{total}", end="", file=sys.stderr, flush=True),
    )
    print(file=sys.stderr)
    print(report)
    for pid, why in report.failed.items():
        print(f"  {pid}: {why}", file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
