"""Client stub for the company's site API.

STATUS: NOT ACTIVE. Nothing in this file is called from the pipeline yet.
This exists so the integration point is ready the moment API access and
scope are confirmed with the supervisor -- see docs/project_proposal.md,
"Risks & Open Items".

Once ready:
    1. Set COMPANY_API_BASE_URL and COMPANY_API_KEY in .env
    2. Set integrations.company_api.enabled: true in config/config.yaml
    3. Swap the relevant call in src/data/... to use this client instead
       of (or alongside) the Telco CSV loader
"""

import os

import requests
from dotenv import load_dotenv

from src.utils.config import load_config
from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


class CompanyAPIClient:
    """Thin wrapper around the company site API.

    Endpoints below are best-guess placeholders based on the project scope
    (customer profile, usage, billing, product catalog) -- confirm exact
    paths and auth scheme against the real API docs once access is granted.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.base_url = os.getenv("COMPANY_API_BASE_URL")
        self.api_key = os.getenv("COMPANY_API_KEY")
        self.timeout = self.config["integrations"]["company_api"]["timeout_seconds"]
        self.enabled = self.config["integrations"]["company_api"]["enabled"]

    def _check_ready(self):
        if not self.enabled:
            raise RuntimeError(
                "CompanyAPIClient is not enabled yet. Set "
                "integrations.company_api.enabled: true in config/config.yaml "
                "once access is confirmed."
            )
        if not self.base_url or not self.api_key:
            raise RuntimeError(
                "COMPANY_API_BASE_URL / COMPANY_API_KEY are not set in .env"
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def get_customers(self, params: dict | None = None) -> dict:
        """Fetch customer profile/usage/billing data. Placeholder endpoint."""
        self._check_ready()
        resp = requests.get(
            f"{self.base_url}/customers", headers=self._headers(),
            params=params, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_products(self, params: dict | None = None) -> dict:
        """Fetch the live product/plan catalog. Placeholder endpoint."""
        self._check_ready()
        resp = requests.get(
            f"{self.base_url}/products", headers=self._headers(),
            params=params, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_customer_usage(self, customer_id: str) -> dict:
        """Fetch usage history for a single customer. Placeholder endpoint."""
        self._check_ready()
        resp = requests.get(
            f"{self.base_url}/customers/{customer_id}/usage",
            headers=self._headers(), timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    logger.info(
        "CompanyAPIClient is a placeholder and is not active. "
        "See module docstring for activation steps."
    )
