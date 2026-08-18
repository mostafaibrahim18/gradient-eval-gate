#!/usr/bin/env python3
"""
sync_config.py

Pushes the agent configuration in the repository to the DigitalOcean Gradient
platform before an evaluation runs. This is what makes a prompt or model change
in Git the same change the eval gate scores.

It syncs two things from config/agent.yaml:

  1. The agent's instruction (system prompt) and model, via PUT /v2/gen-ai/agents/{uuid}
  2. The test case's star-metric pass threshold, via PUT /v2/gen-ai/evaluation_test_cases/{uuid}

The golden dataset is uploaded once through the control panel and referenced by
the test case, so this script does not manage dataset upload. That is the one
manual exception; automating it is a straightforward extension.

Configuration:

    DIGITALOCEAN_API_TOKEN   (required)  PAT with genai scopes
    CONFIG_PATH              (optional)  path to the config file, default config/agent.yaml
"""

import os
import sys

import requests
import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE = "https://api.digitalocean.com/v2/gen-ai"


def fail(message):
    sys.exit(f"ERROR: {message}")


def main():
    token = os.environ.get("DIGITALOCEAN_API_TOKEN")
    if not token:
        fail("DIGITALOCEAN_API_TOKEN is required but not set.")

    config_path = os.environ.get("CONFIG_PATH", "config/agent.yaml")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        fail(f"config file not found at {config_path}")

    agent_uuid = config.get("agent_uuid")
    test_case_uuid = config.get("test_case_uuid")
    instruction = config.get("instruction")
    model = config.get("model")
    threshold = config.get("star_threshold")
    star_metric_uuid = config.get("star_metric_uuid")

    if not agent_uuid:
        fail("agent_uuid missing from config.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Sync the agent's instruction and model.
    agent_body = {}
    if instruction is not None:
        agent_body["instruction"] = instruction
    if model is not None:
        agent_body["model_uuid"] = model

    if agent_body:
        print(f"Syncing agent {agent_uuid} (instruction/model) ...")
        r = requests.put(
            f"{API_BASE}/agents/{agent_uuid}",
            headers=headers,
            json=agent_body,
            timeout=30,
        )
        if r.status_code >= 300:
            fail(f"failed to update agent ({r.status_code}): {r.text}")
        print("  agent updated.")

    # 2. Sync the test case's star-metric threshold.
    if test_case_uuid and threshold is not None:
        print(f"Syncing test case {test_case_uuid} (threshold={threshold}) ...")
        star = {"success_threshold": float(threshold)}
        if star_metric_uuid:
            star["metric_uuid"] = star_metric_uuid
        tc_body = {"star_metric": star}
        r = requests.put(
            f"{API_BASE}/evaluation_test_cases/{test_case_uuid}",
            headers=headers,
            json=tc_body,
            timeout=30,
        )
        if r.status_code >= 300:
            fail(f"failed to update test case ({r.status_code}): {r.text}")
        print("  test case updated.")

    print("Config sync complete.")


if __name__ == "__main__":
    main()