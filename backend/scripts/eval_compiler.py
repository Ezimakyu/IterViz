#!/usr/bin/env python3
"""Eval harness for the Blind Compiler system prompt.

Loads every JSON contract under `scripts/seed_contracts/` (excluding the
sidecar `_expected.json`), runs `app.llm.call_compiler`, and compares the
emitted violations against expectations.

Usage:
    cd backend
    python scripts/eval_compiler.py [--contract NAME] [--no-llm]

Flags:
    --contract NAME   Only evaluate the named seed contract (e.g. orphaned_node.json).
    --no-llm          Skip the LLM call and report only contract-load + schema validation
                      health. Useful in CI without API keys.

Outputs:
    Per-contract pass/fail and aggregate recall/precision against the seeded
    expectations (see ARCHITECTURE.md §4 and SPEC.md §3).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from app.logger import get_logger  # noqa: E402
from app.schemas import CompilerOutput, Contract, Verdict  # noqa: E402

log = get_logger("eval_compiler")

SEED_DIR = REPO_BACKEND / "scripts" / "seed_contracts"
EXPECTED_FILE = SEED_DIR / "_expected.json"


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

@dataclass
class ContractResult:
    name: str
    verdict_expected: str
    verdict_actual: Optional[str] = None
    expected_total: int = 0
    expected_matched: int = 0  # for recall
    emitted_total: int = 0
    emitted_matched: int = 0  # for precision
    error: Optional[str] = None
    violations_emitted: list[dict[str, Any]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    intent_guess: str = ""

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        if self.verdict_actual != self.verdict_expected:
            return False
        return self.expected_matched == self.expected_total and self.emitted_matched == self.emitted_total


def _violation_matches(emitted: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Return True iff `emitted` satisfies `expected`.

    Optional fields on `expected`:
    - `accept_types`: list of allowed `type` values (defaults to `[type]`).
    - `rule_substr`: case-insensitive substring that must appear in
      `emitted.message`. When set, a positive substring match also satisfies
      the affects requirement (since some LLMs report fine-grained affects
      ids like `node.assumptions[0]` instead of the parent node id).
    - `affects`: list of allowed affect ids; `emitted.affects` must overlap
      it, unless rule_substr already matched or `affects` is empty.
    """
    accept_types = expected.get("accept_types") or [expected["type"]]
    if emitted.get("type") not in accept_types:
        return False

    rule_substr: Optional[str] = expected.get("rule_substr")
    if rule_substr:
        message = (emitted.get("message") or "").lower()
        if rule_substr.lower() not in message:
            return False
        return True

    expected_affects = set(expected.get("affects") or [])
    if not expected_affects:
        return True  # empty expected.affects = match by type alone
    emitted_affects = set(emitted.get("affects") or [])
    return bool(emitted_affects & expected_affects)


def evaluate_contract(
    name: str,
    contract_path: Path,
    expectation: dict[str, Any],
    *,
    run_llm: bool,
) -> ContractResult:
    expected_violations: list[dict[str, Any]] = expectation.get("expected", [])
    verdict_expected: str = expectation.get(
        "verdict", "pass" if not expected_violations else "fail"
    )
    result = ContractResult(
        name=name,
        verdict_expected=verdict_expected,
        expected_total=len(expected_violations),
    )

    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
        contract = Contract.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        result.error = f"contract load/parse failed: {exc}"
        return result

    if not run_llm:
        return result

    try:
        from app.llm import call_compiler

        output: CompilerOutput = call_compiler(contract)
    except Exception as exc:  # noqa: BLE001
        result.error = f"compiler call failed: {exc}\n{traceback.format_exc()}"
        return result

    verdict = output.verdict if isinstance(output.verdict, str) else output.verdict.value
    result.verdict_actual = verdict
    result.questions = list(output.questions)
    result.intent_guess = output.intent_guess

    emitted = []
    for v in output.violations:
        emitted.append(
            {
                "type": v.type if isinstance(v.type, str) else v.type.value,
                "severity": v.severity if isinstance(v.severity, str) else v.severity.value,
                "message": v.message,
                "affects": list(v.affects),
                "suggested_question": v.suggested_question,
            }
        )
    result.violations_emitted = emitted
    result.emitted_total = len(emitted)

    matched_emitted_idxs: set[int] = set()
    for exp in expected_violations:
        for i, em in enumerate(emitted):
            if _violation_matches(em, exp):
                result.expected_matched += 1
                matched_emitted_idxs.add(i)
                break

    for i, em in enumerate(emitted):
        if any(_violation_matches(em, exp) for exp in expected_violations):
            result.emitted_matched += 1

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_result(r: ContractResult) -> None:
    status = "PASS" if r.passed else "FAIL"
    print(f"\n=== {r.name} -> {status} ===")
    if r.error:
        print(f"  error: {r.error}")
        return
    print(f"  verdict: expected={r.verdict_expected}  actual={r.verdict_actual}")
    print(f"  expected violations: {r.expected_total}  matched: {r.expected_matched}")
    print(f"  emitted violations: {r.emitted_total}  matched: {r.emitted_matched}")
    if r.intent_guess:
        print(f"  intent_guess: {r.intent_guess}")
    if r.violations_emitted:
        print("  violations:")
        for v in r.violations_emitted:
            affects = ",".join(v["affects"]) or "-"
            print(f"    [{v['severity']}] {v['type']}({affects}): {v['message']}")
    if r.questions:
        print("  questions:")
        for q in r.questions:
            print(f"    - {q}")


def _aggregate(results: list[ContractResult]) -> tuple[float, float]:
    total_expected = sum(r.expected_total for r in results)
    total_emitted = sum(r.emitted_total for r in results)
    matched_recall = sum(r.expected_matched for r in results)
    matched_precision = sum(r.emitted_matched for r in results)
    recall = matched_recall / total_expected if total_expected else 1.0
    precision = matched_precision / total_emitted if total_emitted else 1.0
    return recall, precision


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Blind Compiler eval harness.")
    parser.add_argument("--contract", help="Run against a single contract by filename.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM calls; only validate that contracts parse cleanly.",
    )
    args = parser.parse_args(argv)

    if not EXPECTED_FILE.exists():
        print(f"missing {EXPECTED_FILE}", file=sys.stderr)
        return 2
    expectations = json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))

    contract_files = sorted(
        p for p in SEED_DIR.glob("*.json") if p.name != EXPECTED_FILE.name
    )
    if args.contract:
        contract_files = [SEED_DIR / args.contract]
        if not contract_files[0].exists():
            print(f"missing seed contract: {contract_files[0]}", file=sys.stderr)
            return 2

    results: list[ContractResult] = []
    for path in contract_files:
        expectation = expectations.get(path.name, {})
        if not expectation and path.name != EXPECTED_FILE.name:
            print(f"warning: no expectation entry for {path.name}; treating as valid")
            expectation = {"verdict": "pass", "expected": []}
        r = evaluate_contract(
            name=path.name,
            contract_path=path,
            expectation=expectation,
            run_llm=not args.no_llm,
        )
        _print_result(r)
        results.append(r)

    if args.no_llm:
        ok = all(r.error is None for r in results)
        print("\n--- contract-only sanity check ---")
        print(f"contracts parsed cleanly: {sum(1 for r in results if not r.error)}/{len(results)}")
        return 0 if ok else 1

    recall, precision = _aggregate(results)
    contracts_passed = sum(1 for r in results if r.passed)
    print("\n--- aggregate ---")
    print(f"contracts:  {contracts_passed}/{len(results)} passed")
    print(f"recall:     {recall:.2%}  (target >= 80%)")
    print(f"precision:  {precision:.2%}  (target >= 90%)")

    target_met = recall >= 0.80 and precision >= 0.90 and contracts_passed == len(results)
    return 0 if target_met else 1


if __name__ == "__main__":
    sys.exit(main())
