"""Client stub for the company's existing customer-facing "agent".

STATUS: NOT ACTIVE. Nothing in this file is called from the pipeline yet.

The exact relationship between this recommendation engine and the existing
agent is still an open item (replace it / feed it / sit alongside it -- see
docs/project_proposal.md, "Risks & Open Items"). The methods below cover the
two most likely integration shapes so this is ready to adapt quickly once
scope is confirmed:

    1. push_recommendations()  -- engine feeds ranked recommendations to the
       agent, which decides how/when to surface them to the customer
    2. get_agent_context()     -- engine pulls context/state from the agent
       (e.g. current conversation, customer intent) to personalize output

Once ready:
    1. Set AGENT_API_BASE_URL and AGENT_API_KEY in .env
    2. Set integrations.agent.enabled: true in config/config.yaml
    3. Confirm actual endpoint paths/payload shape against the agent's docs
"""

import os

import requests
from dotenv import load_dotenv

from src.utils.config import load_config
from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


class AgentClient:
    """Thin wrapper around the existing customer agent's API.

    Placeholder only -- confirm real endpoints once integration scope
    (replace / feed / sit alongside) is clarified with the supervisor.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.base_url = os.getenv("AGENT_API_BASE_URL")
        self.api_key = os.getenv("AGENT_API_KEY")
        self.timeout = self.config["integrations"]["agent"]["timeout_seconds"]
        self.enabled = self.config["integrations"]["agent"]["enabled"]

    def _check_ready(self):
        if not self.enabled:
            raise RuntimeError(
                "AgentClient is not enabled yet. Set integrations.agent.enabled: "
                "true in config/config.yaml once integration scope is confirmed."
            )
        if not self.base_url or not self.api_key:
            raise RuntimeError(
                "AGENT_API_BASE_URL / AGENT_API_KEY are not set in .env"
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def push_recommendations(self, customer_id: str, recommendations: list[dict]) -> dict:
        """Send ranked recommendations to the agent for a given customer.
        Placeholder endpoint/payload shape -- confirm against real agent docs.
        """
        self._check_ready()
        resp = requests.post(
            f"{self.base_url}/agent/recommendations",
            headers=self._headers(),
            json={"customer_id": customer_id, "recommendations": recommendations},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_agent_context(self, customer_id: str) -> dict:
        """Pull current context/state from the agent for a given customer.
        Placeholder endpoint -- confirm against real agent docs.
        """
        self._check_ready()
        resp = requests.get(
            f"{self.base_url}/agent/context/{customer_id}",
            headers=self._headers(), timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    logger.info(
        "AgentClient is a placeholder and is not active. "
        "See module docstring for activation steps."
    )
