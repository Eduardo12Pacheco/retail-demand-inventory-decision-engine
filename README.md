# Retail Demand Inventory Decision Engine

Status: **research-to-product prototype implemented on a synthetic fixture,
plus a deterministic bounded evaluation on the pinned real snapshot.**

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

- **The default demo, tests, and fixture report are synthetic.** All numbers in
  `data/evaluations/experiment_report.json` come from a small synthetic fixture
  (`data/fixtures/`). No metric, forecast, cost, or recommendation there is a
  real-world result.
- **The real-snapshot evaluation is bounded and clearly separated.** It lives
  in `data/evaluations/freshretailnet-real-report.json`, is labeled
  `Deterministic bounded evaluation over pinned snapshot`, covers only the
  first 10 store-product keys of the 50,000-key snapshot under a documented
  deterministic rule, and **does not generalize**. It is never called a
  full-dataset or production result.
- **No claim of optimality** anywhere: models and policies are selected under
  documented rules, never labeled optimal.

## Source audit and real snapshot (summary)

The audited candidate is **FreshRetailNet-50K** (Dingdong Limited, Hugging
Face, pinned revision `08c1fab7f9257bc73679d415d65d644165d351d4`, CC BY 4.0,
version 1.0). Audit details, verbatim license terms, canonical mapping,
missingness rules, and the stockout-censoring limitation are in
`docs/source-contract.md`.

- **Raw data is never committed.** The pinned parquet files (train 4,500,000
  rows / eval 350,000 rows) are downloaded into the gitignored `data/raw/` by
  an explicit acquisition command, which verifies exact byte sizes, raw SHA-256
  over the untouched bytes, and the pinned revision (`x-repo-commit`) before
  recording observed checksums in `data/manifests/freshretailnet-real.json`.
- **Offline after acquisition:** once the raw files and the manifest are in
  place, every subsequent step (verify, schema report, real evaluation, demo)
  runs with no network.
- **Stockout semantics:** `stockout_flag` is derived directly from the
  documented `stock_hour6_22_cnt > 0` field (a missing value stays unknown).
  **Zero sales never imply a stockout**; forecasts target observed sales, not
  unconstrained demand.

## Relationship to demand-inventory-optimizer

This is an independent project. It may study the baselines in
`demand-inventory-optimizer` for methodology reference, but it does not copy
that code or data, and it claims nothing from that project's results.

## Architecture

```text
src/retail_demand_inventory/
├── versions.py       # package/schema/protocol version identifiers
├── data/             # contracts, loaders, real manifests, parquet loader,
│                     # acquisition + schema-report CLIs, chronological splits
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

# Fixture evaluation (offline, default) -> data/evaluations/experiment_report.json
uv run python -m retail_demand_inventory.evaluation.materialize

# Real snapshot pipeline (one-time acquisition needs network; then offline)
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json --output-dir data/raw
uv run python -m retail_demand_inventory.data.schema_report \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-schema.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json
# -> data/evaluations/freshretailnet-real-report.json

uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

The evaluation protocol (`docs/evaluation-protocol.md`) fixes splits, seed,
horizon, metrics, the real population rule, and selection rules BEFORE any
number is produced. The demo script (`docs/demo-script.md`) documents what the
demo shows and must not claim.

## Data and license limits

- Third-party data retains its own terms; this repo's MIT license covers only
  original code. `data/raw/` and `data/processed/` are never committed.
- Small fixtures, manifests, schema reports, and generated evaluation reports
  are committed for offline development and auditability.
- The synthetic fixture is visibly labeled; real-snapshot results are bounded
  and labeled, never presented as full-dataset or production results.
