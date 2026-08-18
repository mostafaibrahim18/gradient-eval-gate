#!/usr/bin/env python3
"""
eval_driver.py

Starts a DigitalOcean Gradient agent evaluation run, polls until it finishes,
reads the star-metric score, and exits non-zero if the score is below the
threshold. Runs after sync_config.py in CI, so it scores the configuration
exactly as the pull request defines it.

Configuration is read from config/agent.yaml (the single source of truth for
agent_uuid, test_case_uuid, and star_threshold). The API token is read from the
environment (a local .env file locally, a repository secret in CI):

    DIGITALOCEAN_API_TOKEN   (required)  PAT with genai scopes
    CONFIG_PATH              (optional)  path to the config file, default config/agent.yaml
    POLL_INTERVAL_SECONDS    (optional)  seconds between polls, default 15
    POLL_TIMEOUT_SECONDS     (optional)  give-up time, default 2700 (45 min)
"""

import os
import sys
import time

import requests
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE = "https://api.digitalocean.com/v2/gen-ai"


def main():
    token = os.environ.get("DIGITALOCEAN_API_TOKEN")
    if not token:
        sys.exit("ERROR: DIGITALOCEAN_API_TOKEN is required but not set.")

    # Read agent_uuid, test_case_uuid, and star_threshold from the config file,
    # so a single file is the source of truth for both sync and scoring.
    config_path = os.environ.get("CONFIG_PATH", "config/agent.yaml")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"ERROR: config file not found at {config_path}")

    test_case_uuid = config.get("test_case_uuid")
    agent_uuid = config.get("agent_uuid")
    threshold = float(config.get("star_threshold", 80.0))
    if not test_case_uuid or not agent_uuid:
        sys.exit("ERROR: test_case_uuid and agent_uuid must be set in the config.")

    poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
    poll_timeout = int(os.environ.get("POLL_TIMEOUT_SECONDS", "2700"))

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
        sys.exit(f"TIMEOUT: run did not finish within {poll_timeout}s. This is a platform-speed timeout, not a quality failure. Re-run or raise POLL_TIMEOUT_SECONDS.")

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