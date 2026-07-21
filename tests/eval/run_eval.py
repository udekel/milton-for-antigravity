#!/usr/bin/env python3
"""Automated Evaluation Suite runner for Milton Agent against golden benchmark dataset."""

import json
import os
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.agents.orchestrator import MiltonOrchestrator, RiskAssessmentAgent
from app.agents.explainer import RequestExplainerAgent


class MiltonGoldenDatasetEvaluator:
    """Evaluator engine for running benchmark assertions against golden_dataset.json."""

    def __init__(self, dataset_path: str = None):
        if not dataset_path:
            dataset_path = os.path.join(REPO_ROOT, "tests", "eval", "datasets", "golden_dataset.json")
        self.dataset_path = dataset_path

    def load_dataset(self):
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate_all(self):
        dataset = self.load_dataset()
        cases = dataset.get("eval_cases", [])
        results = []

        orchestrator = MiltonOrchestrator()
        explainer = RequestExplainerAgent()
        risk_agent = RiskAssessmentAgent()

        for case in cases:
            case_id = case["case_id"]
            tool_name = case["target_tool"]
            tool_args = case.get("tool_args", {})
            user_prompt = case.get("user_prompt", "")
            muttering = case.get("muttering", "")
            expected = case.get("expected", {})

            # Prepare turn data
            turns = [
                {
                    "user_prompt": user_prompt,
                    "current_action": tool_name,
                    "fragments": [{"type": "muttering", "content": muttering}]
                }
            ]

            # Run inference via orchestrator
            result = orchestrator.orchestrate_pre_tool_explanation(
                session_id=f"eval-{case_id}",
                target_tool=tool_name,
                turns=turns,
                fragments=[],
                tool_args=tool_args
            )
            explanation_text = result.explanation_text
            risk_level = result.risk.risk_level

            failures = []

            # 1. Check risk level
            expected_risk = expected.get("risk_level")
            if expected_risk and risk_level != expected_risk:
                failures.append(f"Risk mismatch: expected {expected_risk}, got {risk_level}")

            # 2. Check rationale substrings
            for sub in expected.get("rationale_contains", []):
                if sub not in explanation_text:
                    failures.append(f"Missing expected rationale substring: '{sub}'")

            # 3. Check forbidden boilerplate
            for forbidden in expected.get("forbidden_phrases", []):
                if forbidden in explanation_text:
                    failures.append(f"Forbidden phrase found: '{forbidden}'")

            # 4. Check sentence count (max 3)
            sentences = [s.strip() for s in explanation_text.split(".") if s.strip()]
            max_s = expected.get("max_sentences", 3)
            if len(sentences) > max_s:
                failures.append(f"Sentence count {len(sentences)} exceeds maximum {max_s}")

            passed = len(failures) == 0
            results.append({
                "case_id": case_id,
                "tool_name": tool_name,
                "passed": passed,
                "explanation": explanation_text,
                "risk_level": risk_level,
                "failures": failures
            })

        return results

    def print_report(self, results):
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        pass_rate = (passed / total * 100) if total > 0 else 0.0

        print("\n=======================================================")
        print("          MILTON AUTOMATED EVALUATION SUITE REPORT     ")
        print("=======================================================")
        print(f"Total Cases: {total} | Passed: {passed} | Failed: {total - passed} | Pass Rate: {pass_rate:.1f}%\n")

        for r in results:
            status = "PASSED" if r["passed"] else "FAILED"
            print(f"[{status}] Case {r['case_id']} ({r['tool_name']}) | Risk: {r['risk_level']}")
            print(f"  Rationale: \"{r['explanation']}\"")
            if not r["passed"]:
                for f in r["failures"]:
                    print(f"  - FAILURE: {f}")
            print("-" * 55)

        return pass_rate == 100.0


def main():
    evaluator = MiltonGoldenDatasetEvaluator()
    results = evaluator.evaluate_all()
    success = evaluator.print_report(results)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
