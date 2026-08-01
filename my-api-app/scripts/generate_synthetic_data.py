from __future__ import annotations

import argparse
import json
from pathlib import Path
from random import Random


DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "processed" / "recommendations.json"


TITLES = [
    "Improve onboarding flow",
    "Add recommendation caching",
    "Validate incoming payloads",
    "Prioritize high-value users",
    "Reduce API response time",
    "Track recommendation click-through",
    "Refresh stale training data",
    "Tune ranking thresholds",
]

CATEGORIES = ["api", "data", "ml", "product", "ops"]

DESCRIPTIONS = [
    "Helps the system deliver a better user experience.",
    "Supports local testing with deterministic synthetic data.",
    "Provides a practical next step for the demo API.",
    "Improves repeatability during endpoint validation.",
    "Adds useful coverage for integration checks.",
]


def build_records(count: int = 10, seed: int = 42) -> list[dict[str, object]]:
    rng = Random(seed)
    records: list[dict[str, object]] = []

    for index in range(1, count + 1):
        records.append(
            {
                "id": index,
                "title": TITLES[(index - 1) % len(TITLES)],
                "description": DESCRIPTIONS[(index - 1) % len(DESCRIPTIONS)],
                "category": CATEGORIES[rng.randrange(len(CATEGORIES))],
                "score": round(0.95 - (index - 1) * 0.03, 2),
            }
        )

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic recommendation data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON file path")
    parser.add_argument("--count", type=int, default=10, help="Number of recommendation records to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic output")
    args = parser.parse_args()

    records = build_records(count=args.count, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} recommendations to {args.output}")


if __name__ == "__main__":
    main()
