# Demo Script — retail-demand-inventory-decision-engine

Status: **implemented** (reads committed synthetic fixture + generated report only).

## What the demo shows

A Streamlit app over the committed synthetic fixture and the report produced
by the materializer. The user picks a SKU and sees:

1. **Experiment status** — dataset/manifest info, fixed seed, protocol and
   package versions, and the prominent label
   `Synthetic fixture — not a real business result`.
2. **Demand history** for the selected SKU (from the fixture).
3. **Forecast comparison** — selected model's final-test forecast vs observed
   demand, plus the deployment forecast for the next horizon.
4. **Error metrics** — MAE / RMSE / WMAPE / MASE from the report.
5. **Policy comparison** — every simulated candidate policy with service
   level, fill rate, stockout units/events, and total cost.
6. **Recommendation** — selected policy, order quantity, simulated service /
   fill / stockouts / cost, constraint status, reason, evidence, and run IDs.
7. **Assumptions and limitations** — surfaced verbatim from the report.

The demo visibly distinguishes the **audited source contract**
(`docs/source-contract.md`, FreshRetailNet-50K) from the **synthetic
development fixture** used here: the fixture is never presented as real data.

## Constraints

- Reads ONLY committed files under `data/fixtures/`, `data/manifests/`, and
  `data/evaluations/`.
- **No network access** at runtime.
- Streamlit is an optional extra; the module imports safely without it. The
  demo itself requires `--extra demo` to run.

## Run book

```bash
uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## Reproducing the report the demo reads

```bash
uv sync --dev
uv run python -m retail_demand_inventory.evaluation.materialize
```

This regenerates `data/evaluations/<run-id>.json` deterministically (fixed
seed and timestamp; see `docs/evaluation-protocol.md`).

## What the demo must NOT claim

- No real-world accuracy numbers: every metric is labeled as produced from the
  synthetic fixture.
- No assertion that a policy is "best": the demo says the policy was
  "selected under the protocol objective", never "optimal".
