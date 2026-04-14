"""
Data ingestion adapters.

Accepts:
  - a list of dicts (native Python)
  - a JSON file on disk
  - an HTML-like string with a very small, well-defined mock schema

The HTML adapter exists only to show that swapping in a real scraper
would be a matter of wiring up a different parser — the rest of the
pipeline consumes `Supplier` dataclasses either way.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schema import Product, Supplier


def load_suppliers_from_dicts(items: list[dict]) -> list[Supplier]:
    return [Supplier.from_dict(item) for item in items]


def load_suppliers_from_json(path: str | Path) -> list[Supplier]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "suppliers" in data:
        data = data["suppliers"]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of suppliers, or an object with a 'suppliers' key")
    return load_suppliers_from_dicts(data)


# ---------------------------------------------------------------------------
# Minimal HTML-like adapter (illustrative)
# ---------------------------------------------------------------------------
# Expected structure (one supplier per block):
#
# <supplier id="s-001" name="Acme Chem">
#   <location>Jiangsu, CN</location>
#   <about>We provide fine chemicals ...</about>
#   <payment>T/T, Western Union</payment>
#   <shipping>DHL, discreet packaging</shipping>
#   <product cas="67-64-1">Acetone</product>
#   <product>Pharmaceutical Intermediate</product>
# </supplier>
#
# We parse this with regex (good enough for the prototype; a production
# system would use a real HTML parser).

_SUPPLIER_RE = re.compile(r"<supplier\s+([^>]+)>(.*?)</supplier>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_TAG_RE = re.compile(r"<(\w+)([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)


def _parse_attrs(s: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) for m in _ATTR_RE.finditer(s)}


def load_suppliers_from_html(html: str) -> list[Supplier]:
    suppliers: list[Supplier] = []
    for m in _SUPPLIER_RE.finditer(html):
        header_attrs = _parse_attrs(m.group(1))
        body = m.group(2)

        location = None
        about = ""
        payment = ""
        shipping = ""
        products: list[Product] = []

        for tag_match in _TAG_RE.finditer(body):
            tag = tag_match.group(1).lower()
            attrs = _parse_attrs(tag_match.group(2))
            inner = tag_match.group(3).strip()
            if tag == "location":
                location = inner
            elif tag == "about":
                about = inner
            elif tag == "payment":
                payment = inner
            elif tag == "shipping":
                shipping = inner
            elif tag == "product":
                products.append(
                    Product(
                        name=inner,
                        description=attrs.get("desc", ""),
                        cas=attrs.get("cas") or None,
                    )
                )

        suppliers.append(
            Supplier(
                supplier_id=header_attrs.get("id", f"supplier-{len(suppliers)}"),
                name=header_attrs.get("name", "UNKNOWN"),
                location=location,
                products=products,
                payment_terms=payment,
                shipping_terms=shipping,
                about_text=about,
            )
        )
    return suppliers
