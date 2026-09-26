"""One-off script to prepare and clean the Online Retail II dataset.

Usage:
    python scripts/prepare_online_retail.py path/to/online_retail_II.csv --mode year
    python scripts/prepare_online_retail.py path/to/online_retail_II.csv --mode sample
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd


def prepare_online_retail(
    input_path: str | Path,
    mode: str = "year",
    year: int = 2011,
    sample_size: int = 75000,
    output_path: str | Path = "data/raw/online_retail.csv",
    random_seed: int = 42,
) -> pd.DataFrame:
    """Read, filter, clean, and write Online Retail dataset."""
    in_path = Path(input_path)
    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found at: {in_path}")

    print(f"Reading raw data from: {in_path}...")
    if in_path.suffix.lower() in [".xlsx", ".xls"]:
        # If excel, check sheet names. For UCI Online Retail II, sheets are 'Year 2009-2010' and 'Year 2010-2011'.
        xl = pd.ExcelFile(in_path)
        sheet_names = xl.sheet_names
        print(f"Detected Excel file with sheets: {sheet_names}")
        if mode.lower().strip() in ("year", "2011") and "Year 2010-2011" in sheet_names:
            print("Reading sheet 'Year 2010-2011'...")
            df = xl.parse("Year 2010-2011")
        else:
            dfs = [xl.parse(sn) for sn in sheet_names]
            df = pd.concat(dfs, ignore_index=True)
    else:
        # Try default utf-8, fallback to ISO-8859-1 (frequently needed for UCI Online Retail)
        try:
            df = pd.read_csv(in_path, encoding="utf-8")
        except UnicodeDecodeError:
            print("UTF-8 decoding failed, falling back to ISO-8859-1 encoding...")
            df = pd.read_csv(in_path, encoding="ISO-8859-1")

    initial_row_count = len(df)
    print(f"Loaded {initial_row_count:,} raw rows.")

    # 1. Standardize column names
    col_mapping = {
        "Customer ID": "CustomerID",
        "Customer_ID": "CustomerID",
        "customer_id": "CustomerID",
        "customerID": "CustomerID",
        "Invoice": "InvoiceNo",
        "invoice": "InvoiceNo",
        "invoice_no": "InvoiceNo",
        "StockCode": "StockCode",
        "stock_code": "StockCode",
        "Description": "Description",
        "description": "Description",
        "Quantity": "Quantity",
        "quantity": "Quantity",
        "Price": "UnitPrice",
        "price": "UnitPrice",
        "Country": "Country",
        "country": "Country",
        "InvoiceDate": "InvoiceDate",
        "invoice_date": "InvoiceDate",
    }
    df = df.rename(columns={c: col_mapping[c] for c in df.columns if c in col_mapping})

    if "CustomerID" not in df.columns:
        raise ValueError(
            f"CustomerID column not found in raw data. Columns found: {list(df.columns)}"
        )

    # 2. Drop rows with missing CustomerID
    cust_mask = (
        df["CustomerID"].notna()
        & ~df["CustomerID"].astype(str).str.strip().str.lower().isin(["", "nan", "none", "null"])
    )
    df = df[cust_mask].copy()

    # Format customer IDs to clean integer strings (e.g. 17850.0 -> "17850")
    def _clean_id(val: object) -> str:
        if pd.isna(val):
            return ""
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        s = str(val).strip()
        if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
            return s[:-2]
        return s

    df["CustomerID"] = df["CustomerID"].apply(_clean_id)
    df = df[df["CustomerID"] != ""]
    valid_cust_count = len(df)
    print(f"Retained {valid_cust_count:,} rows with valid CustomerID (dropped {initial_row_count - valid_cust_count:,}).")

    # 3. Filter by mode (year or random sample)
    mode_normalized = mode.lower().strip()
    if mode_normalized in ("year", "2011"):
        if "InvoiceDate" not in df.columns:
            raise ValueError("InvoiceDate column is required when filtering by year.")
        print(f"Filtering to year {year}...")
        parsed_dates = pd.to_datetime(df["InvoiceDate"], errors="coerce")
        year_mask = parsed_dates.dt.year == year
        df = df[year_mask].copy()
        print(f"Retained {len(df):,} rows from year {year}.")
    elif mode_normalized in ("sample", "75k", "sample_75k"):
        target_sample = min(sample_size, len(df))
        print(f"Sampling {target_sample:,} rows randomly (seed={random_seed})...")
        df = df.sample(n=target_sample, random_state=random_seed).copy()
    else:
        raise ValueError(
            f"Unknown mode '{mode}'. Expected 'year' or 'sample'."
        )

    # 4. Write cleaned CSV
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Successfully saved {len(df):,} rows to: {out_path.resolve()}")

    prod_col = "StockCode" if "StockCode" in df.columns else None
    if prod_col:
        unique_prods = df[prod_col].nunique()
        print(f"Unique products: {unique_prods:,}")
    unique_custs = df["CustomerID"].nunique()
    print(f"Unique customers: {unique_custs:,}")

    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean and prepare Online Retail II dataset for AI_POD tenant onboarding."
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="Path to raw Online Retail II CSV file.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["year", "sample", "2011", "75k"],
        default="year",
        help="Filter mode: 'year' (filters to 2011) or 'sample' (random sample of ~75k rows). Default: year.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2011,
        help="Year to filter when mode is 'year'. Default: 2011.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=75000,
        help="Sample size when mode is 'sample'. Default: 75000.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/raw/online_retail.csv",
        help="Target output CSV path. Default: data/raw/online_retail.csv.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for sampling. Default: 42.",
    )

    args = parser.parse_args()

    try:
        prepare_online_retail(
            input_path=args.input_path,
            mode=args.mode,
            year=args.year,
            sample_size=args.sample_size,
            output_path=args.output,
            random_seed=args.random_seed,
        )
    except Exception as e:
        print(f"Error preparing dataset: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
