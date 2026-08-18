#!/usr/bin/env python3
"""
eval_driver.py

Starts a DigitalOcean Gradient agent evaluation run, polls until it finishes,
reads the star-metric score, and exits non-zero if the score is below the
threshold. Runs after sync_config.py in CI, so it scores the configuration
exactly as the pull request defines it.

Configuration comes from environment variables (a local .env file locally,
repository secrets and variables in CI):

    DIGITALOCEAN_API_TOKEN   (required)  PAT with genai scopes
    TEST_CASE_UUID           (required)  the evaluation test-case UUID
    AGENT_UUID               (required)  the agent under test
    STAR_THRESHOLD           (optional)  pass mark, default 80.0
    POLL_INTERVAL_SECONDS    (optional)  seconds between polls, default 15
    POLL_TIMEOUT_SECONDS     (optional)  give-up time, default 1500 (25 min)
"""

import os
import sys
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE = "https://api.digitalocean.com/v2/gen-ai"


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"ERROR: {name} is required but not set.")
    return value


def main():
    token = env("DIGITALOCEAN_API_TOKEN", required=True)
    test_case_uuid = env("TEST_CASE_UUID", required=True)
    agent_uuid = env("AGENT_UUID", required=True)
    threshold = float(env("STAR_THRESHOLD", default="80.0"))
    poll_interval = int(env("POLL_INTERVAL_SECONDS", default="15"))
    poll_timeout = int(env("POLL_TIMEOUT_SECONDS", default="1500"))

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Start the run (asynchronous).
    print(f"Starting evaluation run for test case {test_case_uuid} ...")
    body = {
        "test_case_uuid": test_case_uuid,
        "agent_uuids": [agent_uuid],
        "run_name": f"ci-run-{int(time.time())}",
    }
    resp = requests.post(f"{API_BASE}/evaluation_runs", headers=headers, json=body, timeout=30)
    if resp.status_code >= 300:
        sys.exit(f"ERROR: failed to start run ({resp.status_code}): {resp.text}")

    data = resp.json()
    run_uuid = (data.get("evaluation_run_uuids") or [data.get("evaluation_run_uuid")])[0]
    if not run_uuid:
        sys.exit(f"ERROR: no run UUID returned. Raw response: {data}")
    print(f"Run started: {run_uuid}")

    # 2. Poll until the run reaches a terminal state.
    deadline = time.time() + poll_timeout
    run = {}
    while time.time() < deadline:
        r = requests.get(f"{API_BASE}/evaluation_runs/{run_uuid}", headers=headers, timeout=30)
        if r.status_code >= 300:
            sys.exit(f"ERROR: failed to poll run ({r.status_code}): {r.text}")
        run = r.json().get("evaluation_run", {})
        status = run.get("status", "UNKNOWN")
        print(f"  status: {status}")

        # Treat a platform failure as a hard error, not a score of zero.
        if "FAILED" in status or "ERROR" in status or "CANCEL" in status:
            sys.exit(f"ERROR: evaluation run ended in status {status}.")

        if "QUEUED" in status or "RUNNING" in status or "EVALUATING" in status or status == "UNKNOWN":
            time.sleep(poll_interval)
            continue
        break
    else:
        sys.exit(f"ERROR: run did not finish within {poll_timeout}s (timeout).")

    print(f"Final status: {run.get('status')}")

    # 3. Read the star-metric score.
    star = run.get("star_metric_result") or {}
    score = None
    for key in ("value", "score", "metric_value", "number_value", "percentage"):
        if star.get(key) is not None:
            score = float(star[key])
            break
    if score is None:
        print("Raw star_metric_result:", star)
        sys.exit("ERROR: could not read star-metric score.")

    name = star.get("metric_name", "star metric")
    print(f"\n{name}: {score:.2f}%  (threshold {threshold:.2f}%)")

    # 4. Gate: exit non-zero if below threshold.
    if score < threshold:
        print(f"RESULT: FAIL - {score:.2f}% is below the {threshold:.2f}% threshold.")
        sys.exit(1)
    print(f"RESULT: PASS - {score:.2f}% meets the {threshold:.2f}% threshold.")
    sys.exit(0)


if __name__ == "__main__":
    main()