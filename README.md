# Gradient Eval Gate

Regression-test a [DigitalOcean Gradient](https://www.digitalocean.com/products/ai-platform) agent in CI. This repo runs your agent against a golden dataset through the Evaluations API on every pull request, and fails the build when the correctness score drops below a threshold you set.

A silent agent regression becomes a red build, caught before it reaches a user.

## Architecture

![Architecture](assets/architecture.png)

<!-- Save the architecture diagram to assets/architecture.png -->

The gate has four parts: the Gradient agent under test, a golden dataset of `query` and `expected_response` rows, the Evaluations API that scores each answer with an LLM judge, and a GitHub Actions workflow that reads the score and exits non-zero when it falls below the threshold.

## Prerequisites

- A DigitalOcean account with a payment method added.
- [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/), authenticated.
- Python 3.10 or newer.
- A DigitalOcean Personal Access Token with `genai` (create, read, update) and `project` (read) scopes.

## Setup

1. **Clone and install dependencies.**

   ```bash
   git clone https://github.com/your-org/gradient-eval-gate.git
   cd gradient-eval-gate
   pip install -r requirements.txt
   ```

2. **Configure environment variables.** Copy `.env.example` to `.env` and fill in the values:

   ```
   DIGITALOCEAN_API_TOKEN=dop_v1_your_token_here
   TEST_CASE_UUID=your_test_case_uuid_here
   AGENT_UUID=your_agent_uuid_here
   STAR_THRESHOLD=80
   ```

   `.env` is gitignored and must never be committed.

3. **Provision the agent and dataset.** Create a Gradient agent, upload the golden dataset in `evaluations/`, and create an evaluation test case bound to the agent. See the [full tutorial](#) for step-by-step instructions.

## Run it locally

```bash
python eval_driver.py
```

The driver starts an evaluation run, polls until it finishes, reads the star-metric score, prints a PASS or FAIL line, and exits 0 or 1 to match. That exit code is what CI keys on.

## How the CI gate works

The workflow at `.github/workflows/eval-gate.yml` triggers on every pull request. It runs `eval_driver.py` with the token from repository secrets and the identifiers from repository variables. If the score is below `STAR_THRESHOLD`, the driver exits 1 and the job fails.

To block merges on a failing gate, add a required status check under **Settings → Branches** targeting `main` and select the `eval-gate` check. Required status checks are enforced on public repositories and on paid or organization plans.

## Configuration

All configuration is passed through environment variables, so the same driver and workflow drop onto any Gradient agent without code changes:

| Variable | Where | Purpose |
|---|---|---|
| `DIGITALOCEAN_API_TOKEN` | GitHub secret | Authenticates to the Evaluations API |
| `TEST_CASE_UUID` | GitHub variable | The evaluation test case to run |
| `AGENT_UUID` | GitHub variable | The agent under test |
| `STAR_THRESHOLD` | GitHub variable | Pass mark for the star metric |

## Repo structure

```
gradient-eval-gate/
├── .github/workflows/eval-gate.yml   CI workflow
├── evaluations/golden_dataset.csv    golden dataset (query, expected_response)
├── eval_driver.py                    starts, polls, and gates the eval run
├── requirements.txt                  Python dependencies
├── .env.example                      template for local configuration
└── README.md
```

## License

MIT