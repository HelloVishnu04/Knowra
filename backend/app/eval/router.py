import argparse
import json
from pathlib import Path
from typing import Any

from app.agents.graph import classify_route

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPO_ROOT / "datasets" / "eval" / "router_golden.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(cases) < 15:
        raise ValueError("The router golden set must contain at least 15 cases")
    return cases


def evaluate(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    rows = []
    for case in load_cases(path):
        route, sources = classify_route(
            case["query"],
            knowledge_base_id=case.get("knowledge_base_id"),
            repository_id=case.get("repository_id"),
        )
        passed = route == case["expected_route"] and sources == case["expected_sources"]
        rows.append(
            {
                "id": case["id"],
                "route": route,
                "sources": sources,
                "expected_route": case["expected_route"],
                "expected_sources": case["expected_sources"],
                "passed": passed,
            }
        )
    passed_count = sum(row["passed"] for row in rows)
    return {
        "summary": {
            "case_count": len(rows),
            "passed": passed_count,
            "route_accuracy": passed_count / len(rows),
        },
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic agent routing."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.dataset), indent=2))


if __name__ == "__main__":
    main()
