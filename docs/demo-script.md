# Demo Script — retail-demand-inventory-decision-engine

Status: **implemented** — fixture-default and offline; real-snapshot mode is
shown only when a verified real report exists, and is never relabeled.

## What the demo shows

A Streamlit app over committed files. The user picks a SKU and sees:

1. **Experiment status** — dataset/manifest info, fixed seed, protocol and
   package versions, and the prominent label
   `Synthetic fixture — not a real business result`.
2. **Real-snapshot status panel** — if `data/evaluations/freshretailnet-real-report.json`
   exists it shows the pinned revision, manifest path/version, the
   `Deterministic bounded evaluation over pinned snapshot` scope, stockout
   semantics, and limitations. If it does not exist, it shows that real mode is
   unavailable and gives the exact recovery commands (acquisition → schema
   report → materialize --source real).
3. **Demand history** for the selected SKU (from the fixture).
4. **Forecast comparison** — selected model's final-test forecast vs observed
   demand, plus the deployment forecast for the next horizon.
5. **Error metrics** — MAE / RMSE / WMAPE / MASE from the report.
6. **Policy comparison** — every simulated candidate policy with service
   level, fill rate, stockout units/events, and total cost.
7. **Recommendation** — selected policy, order quantity, simulated service /
   fill / stockouts / cost, constraint status, reason, evidence, and run IDs.
8. **Assumptions and limitations** — surfaced verbatim from the report.

The demo visibly distinguishes the **audited source contract**
(`docs/source-contract.md`, FreshRetailNet-50K) and the optional **real
snapshot report** from the **synthetic development fixture** that all charts and
numbers use: the fixture is never presented as real data, and the real report
is never presented as a full-dataset or production result.

## Constraints

- Reads ONLY committed files under `data/fixtures/`, `data/manifests/`,
  `data/evaluations/`, and `data/reports/`. Real raw files in `data/raw/` are
  NOT read by the demo.
- **No network access** at runtime.
- Streamlit is an optional extra; the module imports safely without it. The
  demo itself requires `--extra demo` to run.

## Run book

```bash
uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## Reproducing the reports the demo reads

Fixture report (offline, default):

```bash
uv run python -m retail_demand_inventory.evaluation.materialize
```

Real snapshot report (acquisition needs network once, then offline):

```bash
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json --output-dir data/raw
uv run python -m retail_demand_inventory.data.schema_report \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-schema.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json
```

These regenerate `data/evaluations/experiment_report.json` (fixture) and
`data/evaluations/freshretailnet-real-report.json` (real) deterministically.

## What the demo must NOT claim

- No real-world accuracy numbers: every metric is labeled as produced from the
  synthetic fixture.
- The real snapshot report, when shown, is labeled
  `Deterministic bounded evaluation over pinned snapshot` and is never called a
  full-dataset result.
- No assertion that a policy is "best": the demo says the policy was
  "selected under the protocol objective", never "optimal".
