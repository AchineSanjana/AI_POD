"""Integration test verifying GenericConfigAdapter with telco_default tenant config matches TelcoAdapter.run()."""

import pandas as pd

# pyrefly: ignore [missing-import]
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
# pyrefly: ignore [missing-import]
from src.data.adapters.telco_adapter import TelcoAdapter
# pyrefly: ignore [missing-import]
from src.utils.config import get_tenant_config, load_config


def test_generic_config_adapter_matches_telco_adapter_run():
    """Confirm GenericConfigAdapter(telco_default) produces identical tables to TelcoAdapter().run()."""
    cfg = load_config()

    # 1. Run TelcoAdapter
    telco_adapter = TelcoAdapter(config=cfg)
    telco_customers, telco_products, telco_interactions = telco_adapter.run()

    # 2. Run GenericConfigAdapter with telco_default tenant config
    tenant_cfg = get_tenant_config(cfg, "telco_default")
    generic_adapter = GenericConfigAdapter(tenant_cfg)
    gen_customers, gen_products, gen_interactions = generic_adapter.run()

    # 3. Assert all three tables match bit-for-bit
    pd.testing.assert_frame_equal(gen_customers, telco_customers, obj="customers")
    pd.testing.assert_frame_equal(gen_products, telco_products, obj="products")
    pd.testing.assert_frame_equal(gen_interactions, telco_interactions, obj="interactions")
