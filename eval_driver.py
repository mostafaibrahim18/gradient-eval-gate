#!/usr/bin/env python3
"""
eval_driver.py

Starts a DigitalOcean Gradient agent evaluation run, polls until it finishes,
reads the star-metric score, and exits non-zero if the score is below the
threshold. Designed to be called from CI (e.g. GitHub Actions) so a quality
regression fails the build.

Configuration comes from environment variables so the same file works locally
and in CI without edits:

    DIGITALOCEAN_API_TOKEN   (required)  your PAT with genai scopes
    TEST_CASE_UUID           (required)  the evaluation test-case UUID
    STAR_THRESHOLD           (optional)  pass mark, default 80.0
    POLL_INTERVAL_SECONDS    (optional)  seconds between polls, default 15
    POLL_TIMEOUT_SECONDS     (optional)  give-up time, default 900 (15 min)
"""

import os
import sys
import time

import requests

try:
    # Load variables from a local .env file if present. In CI there is no
    # .env file and the variables come from the environment directly, so a
    # missing dotenv package or missing file is not an error.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE = "https://api.digitalocean.com/v2/gen-ai"


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"ERROR: environment variable {name} is required but not set.")
    return value


def main():
    token = env("DIGITALOCEAN_API_TOKEN", required=True)
    test_case_uuid = env("TEST_CASE_UUID", required=True)
    agent_uuid = env("AGENT_UUID", required=True)
    threshold = float(env("STAR_THRESHOLD", default="80.0"))
    poll_interval = int(env("POLL_INTERVAL_SECONDS", default="15"))
    poll_timeout = int(env("POLL_TIMEOUT_SECONDS", default="900"))

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Start the evaluation run.
    print(f"Starting evaluation run for test case {test_case_uuid} ...")
    start_body = {
        "test_case_uuid": test_case_uuid,
        "agent_uuids": [agent_uuid],
        "run_name": f"ci-run-{int(time.time())}",
    }
    resp = requests.post(
        f"{API_BASE}/evaluation_runs", headers=headers, json=start_body, timeout=30
    )
    if resp.status_code >= 300:
        sys.exit(f"ERROR: failed to start run ({resp.status_code}): {resp.text}")

    data = resp.json()
    # The API returns one or more run UUIDs (one per agent in the test case).
    run_uuids = data.get("evaluation_run_uuids") or (
        [data["evaluation_run_uuid"]] if data.get("evaluation_run_uuid") else []
    )
    if not run_uuids:
        sys.exit(f"ERROR: no run UUID returned. Raw response: {data}")

    run_uuid = run_uuids[0]
    print(f"Run started: {run_uuid}")

    # 2. Poll until the run leaves its queued/running state.
    deadline = time.time() + poll_timeout
    run = None
    while time.time() < deadline:
        r = requests.get(
            f"{API_BASE}/evaluation_runs/{run_uuid}", headers=headers, timeout=30
        )
        if r.status_code >= 300:
            sys.exit(f"ERROR: failed to poll run ({r.status_code}): {r.text}")

        run = r.json().get("evaluation_run", {})
        status = run.get("status", "UNKNOWN")
        # Log the raw status so we learn the real enum on first runs.
        print(f"  status: {status}")

        # Keep polling while the run is still queued or running. The API uses
        # granular running states such as EVALUATION_RUN_RUNNING_DATASET, so we
        # match on the substrings rather than an exact list.
        if (
            "QUEUED" in status
            or "RUNNING" in status
            or "EVALUATING" in status
            or status == "UNKNOWN"
        ):
            time.sleep(poll_interval)
            continue

        # Any other status is terminal (completed / failed / cancelled).
        break
    else:
        sys.exit(f"ERROR: run did not finish within {poll_timeout}s (timeout).")

    print(f"Final status: {run.get('status')}")

    # 3. Read the star-metric score from the finished run.
    star = run.get("star_metric_result") or {}
    # The score may live under any of these keys depending on API version.
    score = None
    for key in ("value", "score", "metric_value", "number_value", "percentage"):
        if star.get(key) is not None:
            score = star.get(key)
            break
    metric_name = star.get("metric_name", "star metric")

    # Fall back to dumping the star metric object so we learn the exact field.
    if score is None:
        print("Could not find score. Raw star_metric_result:")
        print(star)
        rr = requests.get(
            f"{API_BASE}/evaluation_runs/{run_uuid}/results",
            headers=headers,
            timeout=30,
        )
        if rr.status_code < 300:
            print("Raw results payload (for debugging):")
            print(rr.text[:2000])
        sys.exit("ERROR: could not read star-metric score from the run summary.")

    score = float(score)
    print("")
    print(f"{metric_name}: {score:.2f}%  (threshold {threshold:.2f}%)")

    # 4. Gate: exit non-zero if below threshold so CI fails the build.
    if score < threshold:
        print(f"RESULT: FAIL - {score:.2f}% is below the {threshold:.2f}% threshold.")
        sys.exit(1)

    print(f"RESULT: PASS - {score:.2f}% meets the {threshold:.2f}% threshold.")
    sys.exit(0)


if __name__ == "__main__":
    main()