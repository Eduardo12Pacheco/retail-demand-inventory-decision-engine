# AGENTS.md — retail-demand-inventory-decision-engine

## Objective

Build demand forecasting, inventory policy simulation, and replenishment
decisions for retail. Independent, greenfield project. It may learn from the
baselines in the existing `demand-inventory-optimizer` project, but MUST NOT
copy its code and MUST NOT claim results yet.

## Status

Scaffold / implementation not started. No metrics, no claims of results.

## Boundaries

- Do NOT modify these sibling projects: `ecuador-job-market-intelligence`,
  `ecuador-mobility-reliability`, `demand-inventory-optimizer`,
  `ecuador-public-information-evidence-assistant`, `eduardo-github-profile`.
- Do NOT push, publish, or create GitHub remotes.
- No corpus/dataset is implemented until its source and license are audited
  (see `docs/source-contract.md`).

## Structure

```text
src/retail_demand_inventory/   # package under src layout
tests/                         # pytest; real tests only, no fake coverage
docs/                          # source contract, evaluation protocol, demo script
data/fixtures/                 # small versioned fixtures
data/manifests/                # versioned manifests of captured/processed artifacts
data/raw/ data/processed/      # gitignored runtime output
deploy/                        # deployment notes (later)
```

## Expected commands

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## Data policy

- Never commit `data/raw/` or `data/processed/`.
- Commit small fixtures and manifests only.
- License and source of any dataset MUST be audited and documented before use.

## CodeGraph

Use `.codegraph/` index for structural queries. Never commit its contents.

## Testing

Tests must verify real behavior that exists. No placeholder tests pretending
features exist.
