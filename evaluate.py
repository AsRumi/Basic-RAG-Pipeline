"""
Scores the adjudicator against hand-authored pairs with known verdicts.
"""

import argparse
import json
import sys
from collections import Counter
from supersede import judge

CASES_PATH = "tests/contradictions.jsonl"

def read_cases():
    try:
        with open(CASES_PATH, encoding = "utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        raise SystemExit(f"No cases at {CASES_PATH}.")

def score(case):
    try:
        answer = judge(case["earlier"], case["later"])
    except Exception as error:
        return "ERROR", f"{type(error).__name__}: {error}"[:200]

    return answer["verdict"], answer["rationale"]

def outcome(case, verdict):
    if verdict == case["expected"]:
        return "PASS"
    # a pair the adjudicator has never got right is recorded rather than rediscovered each run
    if verdict == case.get("known"):
        return "KNOWN"
    return "FAIL"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action = "store_true",
                        help = "Print the model's rationale for every case.")
    args, _ = parser.parse_known_args()

    cases = read_cases()
    results = []

    for case in cases:
        verdict, rationale = score(case)
        result = outcome(case, verdict)
        results.append(result)

        print(f"{result:6} {case['name']:34} expected {case['expected']:12} got {verdict}")
        if result != "PASS" or args.verbose:
            print(f"       {' '.join(rationale.split())}")

    counts = Counter(results)
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['KNOWN']} known-wrong, {counts['ERROR']} errored, of {len(cases)}")

    for case, result in zip(cases, results):
        if result == "KNOWN":
            print(f"  known-wrong: {case['name']} answers {case['known']}, not {case['expected']}")

    sys.exit(1 if counts["FAIL"] or counts["ERROR"] else 0)
