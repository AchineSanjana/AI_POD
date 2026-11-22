"""Parser for catalogue product specifications and numeric attributes.

Extracts numeric specs from:
1. Formatted 'specs' text columns (e.g. 'ram_gb=8; storage_gb=256; screen_in=6.6').
2. Extra numeric columns present in the product catalogue.
"""

from __future__ import annotations

import re
from typing import Any

# Reserved standard catalogue columns to exclude from extra numeric spec extraction
RESERVED_SPEC_EXCLUSIONS = {
    "product_id",
    "item_id",
    "id",
    "product_name",
    "title",
    "name",
    "category",
    "product_type",
    "brand",
    "price",
    "in_stock",
    "description",
    "image_url",
    "product_url",
    "status",
    "created_at",
    "updated_at",
    "tags",
    "specs",
}


def parse_specs_string(specs_str: str | Any) -> dict[str, float]:
    """Parse a specs text string formatted like 'ram_gb=8; storage_gb=256; screen_in=6.6'.

    Ignores malformed pairs and non-numeric values.
    Returns mapping of spec_name -> float value.
    """
    if not specs_str or not isinstance(specs_str, str):
        return {}

    parsed: dict[str, float] = {}
    tokens = specs_str.split(";")
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            parts = token.split("=", 1)
        elif ":" in token:
            parts = token.split(":", 1)
        else:
            continue

        k = parts[0].strip().lower()
        v_str = parts[1].strip()
        if not k or not v_str:
            continue

        try:
            val = float(v_str)
            parsed[k] = val
        except ValueError:
            # Handle trailing units (e.g. '8GB', '256GB', '6.6in')
            m = re.match(r"^[-+]?([0-9]*\.[0-9]+|[0-9]+)", v_str)
            if m:
                try:
                    parsed[k] = float(m.group(0))
                except ValueError:
                    pass

    return parsed


def extract_numeric_specs(row: dict[str, Any]) -> dict[str, float]:
    """Extract all numeric specs from a product dictionary.

    Combines values parsed from the 'specs' text column and any additional numeric
    columns that are not part of the standard catalogue schema.
    """
    specs: dict[str, float] = {}

    # 1. Parse text specs column if present
    raw_specs = row.get("specs")
    if raw_specs is not None:
        specs.update(parse_specs_string(str(raw_specs)))

    # 2. Check any other columns in the row
    for col, val in row.items():
        clean_col = str(col).strip().lower()
        if clean_col in RESERVED_SPEC_EXCLUSIONS or clean_col in specs:
            continue
        if val is None:
            continue
        try:
            specs[clean_col] = float(val)
        except (ValueError, TypeError):
            continue

    return specs


SPEC_NAME_MAPPINGS = {
    "ram_gb": "RAM (GB)",
    "ram": "RAM (GB)",
    "storage_gb": "Storage (GB)",
    "storage": "Storage (GB)",
    "rom_gb": "Storage (GB)",
    "screen_in": "Screen (in)",
    "screen_size": "Screen (in)",
    "display_in": "Screen (in)",
    "battery_mah": "Battery (mAh)",
    "battery": "Battery (mAh)",
    "camera_mp": "Camera (MP)",
    "camera": "Camera (MP)",
    "cpu_cores": "CPU (Cores)",
    "cores": "CPU (Cores)",
    "weight_g": "Weight (g)",
    "weight": "Weight (g)",
    "refresh_rate_hz": "Refresh Rate (Hz)",
}


def format_human_readable_specs(row: dict[str, Any], max_specs: int = 8) -> dict[str, Any]:
    """Format extracted product specs into up to 8 human-readable key-value pairs.

    Example:
        {'ram_gb': 8.0, 'storage_gb': 256.0} -> {'RAM (GB)': 8, 'Storage (GB)': 256}
    """
    raw_specs = extract_numeric_specs(row)
    formatted: dict[str, Any] = {}

    for k, v in raw_specs.items():
        if len(formatted) >= max_specs:
            break
        label = SPEC_NAME_MAPPINGS.get(k.lower())
        if not label:
            label = k.replace("_", " ").title()

        if isinstance(v, (int, float)):
            val = int(v) if float(v).is_integer() else round(float(v), 2)
        else:
            val = v

        formatted[label] = val

    return formatted

