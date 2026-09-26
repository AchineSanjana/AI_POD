"""Tests for transactional interactions extraction and GenericConfigAdapter dispatch."""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.schema import CustomerSchema, FeatureSpec, InteractionSchema, ProductSchema
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.data.interaction_extraction import (
    build_transactional_interactions,
    derive_products_from_transactional,
)
from src.models.content_based import ContentBasedRecommender
from src.models.ranking_model import LearnedRankingRecommender
from src.utils.config import (
    DataSourceConfig,
    TenantConfig,
    TenantCustomersConfig,
    TenantInteractionsConfig,
    TenantProductsConfig,
    TransactionalInteractionsConfig,
    get_tenant_config,
    load_config,
)
from scripts.prepare_online_retail import prepare_online_retail


@pytest.fixture
def synthetic_transactional_df() -> pd.DataFrame:
    """Small synthetic transactional fixture with repeated purchases, cancellations, and missing values."""
    return pd.DataFrame(
        [
            # Repeated purchases by CUST_1 for PROD_A across two invoices
            {"InvoiceNo": "INV001", "CustomerID": "CUST_1", "StockCode": "PROD_A", "Description": "Product A", "Quantity": 2},
            {"InvoiceNo": "INV002", "CustomerID": "CUST_1", "StockCode": "PROD_A", "Description": "Product A", "Quantity": 3},
            # CUST_1 purchase of PROD_B
            {"InvoiceNo": "INV001", "CustomerID": "CUST_1", "StockCode": "PROD_B", "Description": "Product B", "Quantity": 1},
            # CUST_2 purchase of PROD_A
            {"InvoiceNo": "INV003", "CustomerID": "CUST_2", "StockCode": "PROD_A", "Description": "Product A", "Quantity": 5},
            # Cancelled invoice starting with uppercase "C"
            {"InvoiceNo": "C0001", "CustomerID": "CUST_3", "StockCode": "PROD_C", "Description": "Product C", "Quantity": -1},
            # Cancelled invoice starting with lowercase "c"
            {"InvoiceNo": "c0002", "CustomerID": "CUST_3", "StockCode": "PROD_C", "Description": "Product C", "Quantity": -2},
            # Missing invoice (None / NaN)
            {"InvoiceNo": None, "CustomerID": "CUST_4", "StockCode": "PROD_D", "Description": "Product D", "Quantity": 1},
            # Missing customer ID
            {"InvoiceNo": "INV004", "CustomerID": None, "StockCode": "PROD_E", "Description": "Product E", "Quantity": 1},
            # Missing product ID
            {"InvoiceNo": "INV005", "CustomerID": "CUST_5", "StockCode": None, "Description": "Product F", "Quantity": 1},
        ]
    )


@pytest.fixture
def transactional_config() -> TransactionalInteractionsConfig:
    return TransactionalInteractionsConfig(
        customer_id_column="CustomerID",
        product_id_column="StockCode",
        product_name_column="Description",
        quantity_column="Quantity",
        transaction_id_column="InvoiceNo",
        exclude_invoice_prefix="C",
    )


class TestBuildTransactionalInteractions:
    def test_grouping_weight_attachment_and_cancellation_filtering(
        self,
        synthetic_transactional_df: pd.DataFrame,
        transactional_config: TransactionalInteractionsConfig,
    ) -> None:
        """Verify grouping sums weight, drops cancelled/missing invoices, and conforms to InteractionSchema."""
        result = build_transactional_interactions(
            raw_df=synthetic_transactional_df,
            config=transactional_config,
        )

        # 1. Output shape & schema checks
        schema = InteractionSchema()
        schema.validate(result)
        schema.validate_values(result)

        assert list(result.columns) == ["customer_id", "product_id", "weight"]
        assert len(result) == 3

        # Convert to dict lookup for easy assertions: (customer_id, product_id) -> weight
        pair_weights = {
            (row["customer_id"], row["product_id"]): row["weight"]
            for _, row in result.iterrows()
        }

        # CUST_1 purchased PROD_A across two invoices with quantities 2 and 3 -> total weight 5.0
        assert ("CUST_1", "PROD_A") in pair_weights
        assert pair_weights[("CUST_1", "PROD_A")] == 5.0

        # CUST_1 purchased PROD_B with quantity 1 -> weight 1.0
        assert ("CUST_1", "PROD_B") in pair_weights
        assert pair_weights[("CUST_1", "PROD_B")] == 1.0

        # CUST_2 purchased PROD_A with quantity 5 -> weight 5.0
        assert ("CUST_2", "PROD_A") in pair_weights
        assert pair_weights[("CUST_2", "PROD_A")] == 5.0

        # 2. Filtered out records verification
        # C0001, c0002 should be filtered out
        assert ("CUST_3", "PROD_C") not in pair_weights
        # Missing invoice row should be filtered out
        assert ("CUST_4", "PROD_D") not in pair_weights
        # Missing customer / product should be filtered out
        assert "None" not in result["customer_id"].values
        assert "None" not in result["product_id"].values

    def test_no_weight_column_when_quantity_omitted(
        self,
        synthetic_transactional_df: pd.DataFrame,
    ) -> None:
        """Verify that omitting quantity_column results in [customer_id, product_id] without weight."""
        cfg = TransactionalInteractionsConfig(
            customer_id_column="CustomerID",
            product_id_column="StockCode",
            transaction_id_column="InvoiceNo",
            exclude_invoice_prefix="C",
        )
        result = build_transactional_interactions(
            raw_df=synthetic_transactional_df,
            config=cfg,
        )

        schema = InteractionSchema()
        schema.validate(result)
        schema.validate_values(result)

        assert list(result.columns) == ["customer_id", "product_id"]
        assert len(result) == 3

    def test_dict_config_support(
        self,
        synthetic_transactional_df: pd.DataFrame,
    ) -> None:
        """Verify dict config can be passed directly."""
        cfg = {
            "source": "transactional",
            "customer_id_column": "CustomerID",
            "product_id_column": "StockCode",
            "quantity_column": "Quantity",
            "transaction_id_column": "InvoiceNo",
            "exclude_invoice_prefix": "C",
        }
        result = build_transactional_interactions(
            raw_df=synthetic_transactional_df,
            config=cfg,
        )
        assert len(result) == 3
        assert "weight" in result.columns

    def test_missing_column_raises_value_error(
        self,
        synthetic_transactional_df: pd.DataFrame,
    ) -> None:
        """Missing customer_id or product_id column raises ValueError."""
        cfg = TransactionalInteractionsConfig(
            customer_id_column="NonExistentUser",
            product_id_column="StockCode",
        )
        with pytest.raises(ValueError, match="customer_id_column not found in raw data"):
            build_transactional_interactions(synthetic_transactional_df, cfg)

    def test_empty_raw_df_returns_empty_schema(self) -> None:
        """Empty input DataFrame returns empty DataFrame with correct column names."""
        cfg = TransactionalInteractionsConfig(
            customer_id_column="CustomerID",
            product_id_column="StockCode",
            quantity_column="Quantity",
        )
        empty_raw = pd.DataFrame(columns=["CustomerID", "StockCode", "Quantity", "InvoiceNo"])
        result = build_transactional_interactions(empty_raw, cfg)
        assert list(result.columns) == ["customer_id", "product_id", "weight"]
        assert len(result) == 0

    def test_float_customer_id_normalized(self) -> None:
        """Verify float customer IDs like 17850.0 from CSVs are normalized to '17850'."""
        df = pd.DataFrame(
            [
                {"InvoiceNo": "INV1", "CustomerID": 17850.0, "StockCode": "85123A", "Quantity": 2},
                {"InvoiceNo": "INV2", "CustomerID": 17850.0, "StockCode": "85123A", "Quantity": 4},
            ]
        )
        cfg = TransactionalInteractionsConfig(
            customer_id_column="CustomerID",
            product_id_column="StockCode",
            quantity_column="Quantity",
            transaction_id_column="InvoiceNo",
        )
        result = build_transactional_interactions(df, cfg)
        assert len(result) == 1
        assert result.loc[0, "customer_id"] == "17850"
        assert result.loc[0, "weight"] == 6.0


class TestGenericConfigAdapterTransactionalDispatch:
    def test_to_interactions_dispatches_transactional(
        self,
        synthetic_transactional_df: pd.DataFrame,
        transactional_config: TransactionalInteractionsConfig,
    ) -> None:
        """Verify GenericConfigAdapter.to_interactions() dispatches when source == 'transactional'."""
        tenant_cfg = TenantConfig(
            tenant_id="retail_test",
            data_source=DataSourceConfig(type="csv", path="dummy.csv"),
            customers=TenantCustomersConfig(
                id_column="CustomerID",
                features=[FeatureSpec(name="Quantity", dtype="numeric")],
            ),
            products=TenantProductsConfig(
                derived_from="none",
                category_column="category",
            ),
            interactions=TenantInteractionsConfig(
                source="transactional",
                transactional=transactional_config,
            ),
        )

        adapter = GenericConfigAdapter(tenant_cfg)
        # Inject raw data directly to avoid filesystem reads
        adapter._raw = synthetic_transactional_df

        interactions = adapter.to_interactions()

        assert isinstance(interactions, pd.DataFrame)
        assert list(interactions.columns) == ["customer_id", "product_id", "weight"]
        assert len(interactions) == 3

        adapter.interaction_schema.validate_values(interactions)


class TestTenantConfigTransactionalParsing:
    def test_get_tenant_config_parses_transactional_block(self) -> None:
        """Verify get_tenant_config successfully parses transactional interactions block."""
        cfg_dict = {
            "tenants": {
                "online_retail": {
                    "data_source": {
                        "type": "csv",
                        "path": "data/raw/online_retail.csv",
                    },
                    "customers": {
                        "id_column": "CustomerID",
                        "features": [
                            {"name": "Country", "dtype": "categorical"},
                        ],
                    },
                    "products": {
                        "derived_from": "none",
                        "category_column": "category",
                    },
                    "interactions": {
                        "source": "transactional",
                        "customer_id_column": "CustomerID",
                        "product_id_column": "StockCode",
                        "product_name_column": "Description",
                        "quantity_column": "Quantity",
                        "transaction_id_column": "InvoiceNo",
                        "exclude_invoice_prefix": "C",
                    },
                }
            }
        }

        tenant_cfg = get_tenant_config(cfg_dict, "online_retail")
        assert tenant_cfg.interactions.source == "transactional"
        assert tenant_cfg.interactions.customer_id_column == "CustomerID"
        assert tenant_cfg.interactions.product_id_column == "StockCode"
        assert tenant_cfg.interactions.product_name_column == "Description"
        assert tenant_cfg.interactions.quantity_column == "Quantity"
        assert tenant_cfg.interactions.transaction_id_column == "InvoiceNo"
        assert tenant_cfg.interactions.exclude_invoice_prefix == "C"

        assert isinstance(tenant_cfg.interactions.transactional, TransactionalInteractionsConfig)
        assert tenant_cfg.interactions.transactional.customer_id_column == "CustomerID"

    def test_get_tenant_config_missing_required_transactional_field(self) -> None:
        """Verify KeyError is raised if required customer_id_column or product_id_column is missing."""
        cfg_dict = {
            "tenants": {
                "bad_retail": {
                    "data_source": {"type": "csv", "path": "test.csv"},
                    "customers": {"id_column": "CustomerID", "features": []},
                    "products": {"derived_from": "none", "category_column": "category"},
                    "interactions": {
                        "source": "transactional",
                        # customer_id_column missing
                        "product_id_column": "StockCode",
                    },
                }
            }
        }
        with pytest.raises(KeyError, match="missing required field 'customer_id_column'"):
            get_tenant_config(cfg_dict, "bad_retail")

    def test_get_tenant_config_parses_transactional_products_block(self) -> None:
        """Verify get_tenant_config successfully parses transactional products block without category_column."""
        cfg_dict = {
            "tenants": {
                "retail_products": {
                    "data_source": {"type": "csv", "path": "data.csv"},
                    "customers": {"id_column": "CustomerID", "features": []},
                    "products": {
                        "derived_from": "transactional",
                        "id_column": "StockCode",
                        "name_column": "Description",
                    },
                    "interactions": {
                        "source": "transactional",
                        "customer_id_column": "CustomerID",
                        "product_id_column": "StockCode",
                    },
                }
            }
        }
        tenant_cfg = get_tenant_config(cfg_dict, "retail_products")
        assert tenant_cfg.products.derived_from == "transactional"
        assert tenant_cfg.products.id_column == "StockCode"
        assert tenant_cfg.products.name_column == "Description"
        assert tenant_cfg.products.category_column is None


class TestDeriveProductsFromTransactional:
    def test_most_frequent_description_resolved(self) -> None:
        """Verify that minor Description variants resolve to the most frequent description."""
        raw_df = pd.DataFrame(
            [
                # StockCode 85123A has:
                # "WHITE HANGING HEART T-LIGHT HOLDER" x 3
                # "white hanging heart t-light holder" x 1
                # "  WHITE HANGING HEART T-LIGHT HOLDER  " x 1 (strips to same uppercase)
                {"StockCode": "85123A", "Description": "WHITE HANGING HEART T-LIGHT HOLDER"},
                {"StockCode": "85123A", "Description": "WHITE HANGING HEART T-LIGHT HOLDER"},
                {"StockCode": "85123A", "Description": "WHITE HANGING HEART T-LIGHT HOLDER"},
                {"StockCode": "85123A", "Description": "white hanging heart t-light holder"},
                {"StockCode": "85123A", "Description": "  WHITE HANGING HEART T-LIGHT HOLDER  "},
                # StockCode 71053 has "WHITE METAL LANTERN" x 2 and "White Lantern" x 1
                {"StockCode": "71053", "Description": "WHITE METAL LANTERN"},
                {"StockCode": "71053", "Description": "WHITE METAL LANTERN"},
                {"StockCode": "71053", "Description": "White Lantern"},
                # StockCode POST has None and empty descriptions
                {"StockCode": "POST", "Description": None},
                {"StockCode": "POST", "Description": "   "},
                # Missing StockCode row should be excluded
                {"StockCode": None, "Description": "IGNORED"},
            ]
        )

        products = derive_products_from_transactional(
            raw_df=raw_df,
            id_column="StockCode",
            name_column="Description",
        )

        schema = ProductSchema()
        schema.validate(products)
        schema.validate_values(products)

        assert list(products.columns) == ["product_id", "product_name"]
        assert len(products) == 3

        product_map = dict(zip(products["product_id"], products["product_name"]))
        assert product_map["85123A"] == "WHITE HANGING HEART T-LIGHT HOLDER"
        assert product_map["71053"] == "WHITE METAL LANTERN"
        # POST had no valid description, so falls back to product_id
        assert product_map["POST"] == "POST"

    def test_missing_id_column_raises_value_error(self) -> None:
        raw_df = pd.DataFrame([{"StockCode": "A"}])
        with pytest.raises(ValueError, match="products.id_column not found in raw data"):
            derive_products_from_transactional(raw_df, id_column="NonExistent")

    def test_empty_raw_df_returns_empty_schema(self) -> None:
        raw_df = pd.DataFrame(columns=["StockCode", "Description"])
        products = derive_products_from_transactional(raw_df, id_column="StockCode", name_column="Description")
        assert list(products.columns) == ["product_id", "product_name"]
        assert len(products) == 0


class TestGenericConfigAdapterTransactionalProducts:
    def test_to_products_dispatches_transactional(self) -> None:
        raw_df = pd.DataFrame(
            [
                {"StockCode": "P1", "Description": "Product One", "CustomerID": "C1", "InvoiceNo": "INV1"},
                {"StockCode": "P1", "Description": "Product One", "CustomerID": "C1", "InvoiceNo": "INV2"},
                {"StockCode": "P1", "Description": "product one (alt)", "CustomerID": "C2", "InvoiceNo": "INV3"},
                {"StockCode": "P2", "Description": "Product Two", "CustomerID": "C1", "InvoiceNo": "INV1"},
            ]
        )
        tenant_cfg = TenantConfig(
            tenant_id="retail_adapter_test",
            data_source=DataSourceConfig(type="csv", path="dummy.csv"),
            customers=TenantCustomersConfig(
                id_column="CustomerID",
                features=[],
            ),
            products=TenantProductsConfig(
                derived_from="transactional",
                id_column="StockCode",
                name_column="Description",
            ),
            interactions=TenantInteractionsConfig(
                source="transactional",
                customer_id_column="CustomerID",
                product_id_column="StockCode",
            ),
        )

        adapter = GenericConfigAdapter(tenant_cfg)
        adapter._raw = raw_df

        products = adapter.to_products()
        assert isinstance(products, pd.DataFrame)
        assert list(products.columns) == ["product_id", "product_name"]
        assert len(products) == 2

        prod_dict = dict(zip(products["product_id"], products["product_name"]))
        assert prod_dict["P1"] == "Product One"
        assert prod_dict["P2"] == "Product Two"

        adapter.product_schema.validate_values(products)


class TestDownstreamModelCompatibilityWithCategoryFreeProducts:
    def test_content_based_and_ranking_models_work_without_category(self) -> None:
        """Verify models train and recommend without requiring a category column on products."""
        customers_df = pd.DataFrame(
            [
                {"customer_id": "C1", "age": 25.0, "region": "North"},
                {"customer_id": "C2", "age": 40.0, "region": "South"},
                {"customer_id": "C3", "age": 35.0, "region": "North"},
            ]
        )
        products_df = pd.DataFrame(
            [
                {"product_id": "P1", "product_name": "Product 1"},
                {"product_id": "P2", "product_name": "Product 2"},
            ]
        )
        interactions_df = pd.DataFrame(
            [
                {"customer_id": "C1", "product_id": "P1", "weight": 2.0},
                {"customer_id": "C2", "product_id": "P2", "weight": 1.0},
                {"customer_id": "C3", "product_id": "P1", "weight": 3.0},
            ]
        )

        # 1. Content-based recommender
        cb_model = ContentBasedRecommender()
        cb_model.fit(
            customers=customers_df,
            interactions=interactions_df,
            feature_columns=["age", "region"],
        )
        recs = cb_model.recommend(customers_df.iloc[0], top_k=2)
        assert len(recs) > 0
        assert all(isinstance(p, str) for p in recs)

        # 2. Learned ranking recommender
        ranking_model = LearnedRankingRecommender(
            customer_specs=[
                FeatureSpec(name="age", dtype="numeric"),
                FeatureSpec(name="region", dtype="categorical"),
            ]
        )
        ranking_model.fit(
            customers=customers_df,
            interactions=interactions_df,
            products=products_df,
        )
        rank_recs = ranking_model.recommend(customer_id="C1", top_k=2)
        assert isinstance(rank_recs, list)


def test_online_retail_config_yaml_parses_correctly() -> None:
    """Verify that online_retail tenant block in config.yaml parses into a valid TenantConfig."""
    cfg = load_config()
    tenant_cfg = get_tenant_config(cfg, "online_retail")

    assert tenant_cfg.tenant_id == "online_retail"
    assert tenant_cfg.data_source.path == "data/raw/online_retail.csv"
    assert tenant_cfg.customers.id_column == "CustomerID"
    assert len(tenant_cfg.customers.features) == 1
    assert tenant_cfg.customers.features[0].name == "Country"
    assert tenant_cfg.customers.features[0].dtype == "categorical"

    assert tenant_cfg.products.derived_from == "transactional"
    assert tenant_cfg.products.id_column == "StockCode"
    assert tenant_cfg.products.name_column == "Description"

    assert tenant_cfg.interactions.source == "transactional"
    assert tenant_cfg.interactions.customer_id_column == "CustomerID"
    assert tenant_cfg.interactions.product_id_column == "StockCode"
    assert tenant_cfg.interactions.product_name_column == "Description"
    assert tenant_cfg.interactions.quantity_column == "Quantity"
    assert tenant_cfg.interactions.transaction_id_column == "InvoiceNo"
    assert tenant_cfg.interactions.exclude_invoice_prefix == "C"

    assert tenant_cfg.segmentation is not None
    assert tenant_cfg.segmentation.field == "Country"
    assert tenant_cfg.segmentation.split == "categorical"


def test_prepare_online_retail_script(tmp_path: pytest.TempPathFactory) -> None:
    """Verify scripts/prepare_online_retail.py correctly filters, cleans, and outputs data."""
    raw_csv = tmp_path / "raw_retail_II.csv"
    output_year_csv = tmp_path / "out_year.csv"
    output_sample_csv = tmp_path / "out_sample.csv"

    test_data = pd.DataFrame(
        [
            # 2011 rows with valid customer
            {"Invoice": "536365", "StockCode": "85123A", "Description": "HEART", "Quantity": 6, "InvoiceDate": "2011-01-01 10:00", "Price": 2.55, "Customer ID": 17850.0, "Country": "United Kingdom"},
            {"Invoice": "536366", "StockCode": "71053", "Description": "LANTERN", "Quantity": 2, "InvoiceDate": "2011-02-15 12:00", "Price": 3.39, "Customer ID": 17850.0, "Country": "United Kingdom"},
            {"Invoice": "536367", "StockCode": "84879", "Description": "BIRD", "Quantity": 10, "InvoiceDate": "2011-06-20 14:00", "Price": 1.69, "Customer ID": 13047.0, "Country": "Germany"},
            # 2010 row (should be filtered out in mode='year')
            {"Invoice": "489434", "StockCode": "21232", "Description": "CHERRY", "Quantity": 24, "InvoiceDate": "2010-12-01 07:45", "Price": 1.25, "Customer ID": 13085.0, "Country": "United Kingdom"},
            # Missing customer ID (should be dropped in both modes)
            {"Invoice": "536368", "StockCode": "22960", "Description": "JAM", "Quantity": 6, "InvoiceDate": "2011-03-01 08:00", "Price": 4.25, "Customer ID": None, "Country": "United Kingdom"},
            {"Invoice": "536369", "StockCode": "22961", "Description": "MUG", "Quantity": 12, "InvoiceDate": "2011-03-02 09:00", "Price": 1.95, "Customer ID": "nan", "Country": "United Kingdom"},
        ]
    )
    test_data.to_csv(raw_csv, index=False)

    # 1. Mode == 'year'
    df_year = prepare_online_retail(
        input_path=raw_csv,
        mode="year",
        year=2011,
        output_path=output_year_csv,
    )
    assert len(df_year) == 3
    assert set(df_year["CustomerID"]) == {"17850", "13047"}
    assert "CustomerID" in df_year.columns
    assert "InvoiceNo" in df_year.columns
    assert output_year_csv.exists()

    # 2. Mode == 'sample'
    df_sample = prepare_online_retail(
        input_path=raw_csv,
        mode="sample",
        sample_size=2,
        output_path=output_sample_csv,
        random_seed=42,
    )
    assert len(df_sample) == 2
    assert None not in df_sample["CustomerID"].values
    assert output_sample_csv.exists()


