# Retail Demand Inventory Decision Engine

Status: **research-to-product prototype implemented on a synthetic fixture.**

A greenfield project for demand forecasting, inventory policy simulation, and
replenishment decisions, built with reproducible evidence at its center.

## What this is

- A canonical, validated demand data layer (typed `DemandRecord` / `DemandTable`).
- A set of forecasting models behind one `fit(train_data) / predict(context, horizon)`
  interface: naive, moving average, simple exponential smoothing, and a
  supervised `HistGradientBoostingRegressor` using only prior lags, rolling
  statistics, and calendar features.
- A deterministic daily lost-sales inventory simulator (reorder-point/order-qty
  and order-up-to/safety-stock policies) with auditable run IDs.
- A decision layer that selects a policy by *min total cost subject to a
  service-level target* and attaches evidence (run IDs, versions, report paths)
  to every recommendation.
- A protocol-driven evaluation that produces a reproducible JSON report and an
  offline Streamlit demo.

## What this is NOT (read this first)

- **No real data.** All numbers in this repository come from a small synthetic
  fixture (`data/fixtures/`). No metric, forecast, cost, or recommendation here
  is a real-world result.
- No dataset is implemented until its source and license are audited and
  recorded in `docs/source-contract.md`.
- **No claim of optimality** anywhere: models and policies are selected under
  documented rules, never labeled optimal.

## Source audit (summary)

The primary audited candidate is **FreshRetailNet-50K** (Dingdong Limited,
Hugging Face, pinned revision `08c1fab7f9257bc73679d415d65d644165d351d4`,
CC BY 4.0, version 1.0). Audit details, verbatim license terms, canonical
mapping, missingness rules, and the stockout-censoring limitation are in
`docs/source-contract.md`. Real data is **not** retained; the audit is a
gate, not a download.

## Relationship to demand-inventory-optimizer

This is an independent project. It may study the baselines in
`demand-inventory-optimizer` for methodology reference, but it does not copy
that code or data, and it claims nothing from that project's results.

## Architecture

```text
src/retail_demand_inventory/
├── versions.py       # package/schema/protocol version identifiers
├── data/             # contracts, loaders, manifests, chronological splits
├── forecasting/      # base interface, baselines, features, models, predictions
├── simulation/       # policies, engine, events, outcomes (daily lost-sales)
├── decisions/        # recommendation, ranking, evidence
└── evaluation/       # metrics, backtesting, reports, materializer CLI
```

## Commands

```bash
uv sync --dev
uv run pytest                       # real behavior tests, no network
uv run ruff check .
uv run ruff format --check .

uv run python -m retail_demand_inventory.evaluation.materialize
# deterministic report -> data/evaluations/

uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

The evaluation protocol (`docs/evaluation-protocol.md`) fixes splits, seed,
horizon, metrics, and selection rules BEFORE any number is produced. The demo
script (`docs/demo-script.md`) documents what the demo shows and must not claim.

## Data and license limits

- Third-party data retains its own terms; this repo's MIT license covers only
  original code. `data/raw/` and `data/processed/` are never committed.
- Small fixtures, manifests, and the generated evaluation report are committed
  for offline development and auditability.
- The synthetic fixture is visibly labeled; it is not an audited-source result.
