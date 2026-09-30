"""Admin CLI script for issuing both private and public API keys for a tenant.

Every tenant requires:
1. A private key ('sk-...'): Used for backend-to-backend calls (onboarding, training, full API access).
2. A public key ('pk-...'): Restricted server-side to POST /v1/track and GET /v1/recommendations.

Usage:
    python scripts/issue_tenant_keys.py --tenant-id acme_corp
    python scripts/issue_tenant_keys.py --tenant-id acme_corp --private-key sk-acme-secret --public-key pk-acme-pub
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python scripts/issue_tenant_keys.py` from project root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.key_manager import issue_tenant_keys  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Issue both private and public API keys for a tenant."
    )
    parser.add_argument(
        "--tenant-id",
        "--tenant_id",
        required=True,
        help="Unique tenant identifier (e.g. 'telco_default', 'acme_corp')",
    )
    parser.add_argument(
        "--private-key",
        "--private_key",
        default=None,
        help="Optional custom private key (default: auto-generated 'sk-{tenant_id}-{token}')",
    )
    parser.add_argument(
        "--public-key",
        "--public_key",
        default=None,
        help="Optional custom public key (default: auto-generated 'pk-{tenant_id}-{token}')",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results strictly as JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = issue_tenant_keys(
            tenant_id=args.tenant_id,
            private_key=args.private_key,
            public_key=args.public_key,
        )
    except Exception as exc:
        print(f"Error issuing keys for tenant '{args.tenant_id}': {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Successfully issued API keys for tenant: {result['tenant_id']}")
        print("=" * 60)
        print(f"  Private Key (Backend / Onboarding): {result['private_key']['key']}")
        print(f"    - Type:       {result['private_key']['key_type']}")
        print(f"    - Created At: {result['private_key']['created_at']}")
        print(f"  Public Key (Frontend / Tracking):   {result['public_key']['key']}")
        print(f"    - Type:       {result['public_key']['key_type']}")
        print(f"    - Created At: {result['public_key']['created_at']}")
        print("=" * 60)
        print("Note: Public keys are restricted server-side to POST /v1/track and GET /v1/recommendations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
