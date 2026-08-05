import pandas as pd

from src.utils.config import (
    build_customer_schema_from_config,
    build_product_schema_from_config,
    load_config,
    resolve_path,
)


def test_schemas_from_config_match_processed_csv_columns():
    config = load_config()
    customer_schema = build_customer_schema_from_config(config)
    product_schema = build_product_schema_from_config(config)

    processed_dir = resolve_path(config["paths"]["processed_dir"])
    customers_path = processed_dir / config["paths"]["customers_out"]
    products_path = processed_dir / config["paths"]["products_out"]

    customers = pd.read_csv(customers_path)
    products = pd.read_csv(products_path)

    assert set(customer_schema.required_columns()) == set(customers.columns)

    product_required = set(product_schema.required_columns())
    assert product_required <= set(products.columns)
    assert set(products.columns) == product_required | {product_schema.DISPLAY_NAME_COLUMN}

    customer_schema.validate(customers)
    product_schema.validate(products)
