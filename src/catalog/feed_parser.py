"""Product catalog feed parser supporting Google Shopping XML (RSS 2.0 / Atom) and JSON feeds.

Parses e-commerce product feeds into canonical product records:
(product_id, product_name, price, category)
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


def _clean_price(raw_price: Any) -> float | None:
    """Extract numeric float value from currency string (e.g. '$19.99', '19.99 USD')."""
    if raw_price is None:
        return None
    if isinstance(raw_price, (int, float)):
        return float(raw_price)
    text = str(raw_price).strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _local_tag(elem: ET.Element) -> str:
    """Strip XML namespace prefix from tag name for agnostic tag comparison."""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _parse_xml_feed(root: ET.Element) -> list[dict[str, Any]]:
    """Parse Google Shopping RSS 2.0 or Atom XML feed into product records."""
    items: list[ET.Element] = []

    # 1. Locate all product elements (supports RSS <item> and Atom <entry>)
    for elem in root.iter():
        tag = _local_tag(elem)
        if tag in ("item", "entry"):
            items.append(elem)

    products: list[dict[str, Any]] = []

    for item in items:
        prod_id: str | None = None
        title: str | None = None
        price_val: Any = None
        category: str | None = None

        for child in item:
            ltag = _local_tag(child)
            text = child.text.strip() if child.text else None
            if not text:
                continue

            # Product ID
            if ltag in ("id", "product_id", "sku", "g:id") and not prod_id:
                prod_id = text
            # Title / Name
            elif ltag in ("title", "product_name", "name", "g:title") and not title:
                title = text
            # Price
            elif ltag in ("price", "sale_price", "regular_price", "g:price") and price_val is None:
                price_val = text
            # Category
            elif ltag in ("product_type", "google_product_category", "category", "g:product_type") and not category:
                category = text

        if prod_id:
            products.append(
                {
                    "product_id": str(prod_id).strip(),
                    "product_name": str(title).strip() if title else str(prod_id).strip(),
                    "price": _clean_price(price_val),
                    "category": str(category).strip() if category else None,
                }
            )

    return products


def _parse_json_feed(data: Any) -> list[dict[str, Any]]:
    """Parse JSON product feed (list or object with products/items key)."""
    raw_list: list[Any] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for candidate in ("products", "items", "feed", "catalog", "data"):
            if candidate in data and isinstance(data[candidate], list):
                raw_list = data[candidate]
                break

    products: list[dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue

        prod_id = (
            item.get("product_id")
            or item.get("id")
            or item.get("sku")
            or item.get("g:id")
        )
        if not prod_id:
            continue

        title = (
            item.get("product_name")
            or item.get("title")
            or item.get("name")
            or item.get("g:title")
        )
        price_val = (
            item.get("price")
            or item.get("sale_price")
            or item.get("regular_price")
            or item.get("g:price")
        )
        category = (
            item.get("category")
            or item.get("product_type")
            or item.get("google_product_category")
            or item.get("g:product_type")
        )

        products.append(
            {
                "product_id": str(prod_id).strip(),
                "product_name": str(title).strip() if title else str(prod_id).strip(),
                "price": _clean_price(price_val),
                "category": str(category).strip() if category else None,
            }
        )

    return products


def parse_catalog_feed(
    content: bytes | str,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    """Parse product catalog feed content (XML or JSON) into product records.

    Args:
        content: Raw bytes or string content of the feed.
        content_type: Optional MIME type (e.g. application/json, text/xml).

    Returns:
        List of dicts with keys: product_id, product_name, price, category.
    """
    if isinstance(content, str):
        text = content.strip()
        raw_bytes = content.encode("utf-8")
    else:
        raw_bytes = content
        try:
            text = content.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = content.decode("latin-1").strip()

    if not text:
        return []

    # 1. Attempt JSON parsing if content_type matches or text begins with [ or {
    is_json = (
        (content_type and "json" in content_type.lower())
        or text.startswith("{")
        or text.startswith("[")
    )
    if is_json:
        try:
            data = json.loads(text)
            parsed = _parse_json_feed(data)
            if parsed:
                return parsed
        except Exception as exc:
            logger.debug("Failed parsing as JSON, attempting XML: %s", exc)

    # 2. Attempt XML parsing
    try:
        root = ET.fromstring(raw_bytes)
        return _parse_xml_feed(root)
    except Exception as exc:
        # If XML also fails and it looks like JSON, try JSON as fallback
        if not is_json:
            try:
                data = json.loads(text)
                return _parse_json_feed(data)
            except Exception:
                pass
        logger.error("Failed to parse catalog feed as either XML or JSON: %s", exc)
        raise ValueError(f"Unable to parse catalog feed content: {exc}") from exc


def fetch_catalog_feed(url: str, timeout: int = 30) -> tuple[bytes, str | None]:
    """Fetch catalog feed bytes from URL (supporting http://, https://, and local file://).

    Args:
        url: Remote URL or local file path/URI.
        timeout: Request timeout in seconds.

    Returns:
        tuple of (raw_bytes, content_type)
    """
    cleaned = url.strip()

    # Handle file:// or local path
    if cleaned.startswith("file://") or Path(cleaned).exists():
        if cleaned.startswith("file://"):
            local_path = urllib.request.url2pathname(cleaned[7:])
        else:
            local_path = cleaned
        path_obj = Path(local_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Local catalog feed file not found at: {local_path}")
        content = path_obj.read_bytes()
        ct = "application/json" if path_obj.suffix.lower() == ".json" else "text/xml"
        return content, ct

    # Handle HTTP/HTTPS requests
    req = urllib.request.Request(
        cleaned,
        headers={"User-Agent": "AI_POD-CatalogFeedSync/1.0", "Accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()
        content_type = resp.headers.get_content_type()
        return content, content_type
