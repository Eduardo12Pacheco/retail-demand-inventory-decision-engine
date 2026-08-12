# Demo Script — retail-demand-inventory-decision-engine

Status: **implemented** — fixture-default and offline; real-snapshot modes are
shown only when a verified real report exists, and are never relabeled.

## What the demo shows

A Streamlit app over committed files. The user picks a SKU and sees:

1. **Experiment status** — dataset/manifest info, fixed seed, protocol and
   package versions, and the prominent label
   `Synthetic fixture — not a real business result`.
2. **Real-snapshot status panel** — if a verified real report exists it shows
   the pinned revision, manifest path/version, the deterministic-bounded scope,
   stockout semantics, and limitations. When the **expanded (v2)** report
   exists it is shown explicitly with its population ID
   (`freshretailnet-real-population-v2`), key/store/product counts, the
   bounded-population warning, stockout semantics, and a compact distributional
   summary (median/p25/p75/p95 of final-test and policy metrics). If no real
   report exists, it shows that real mode is unavailable and gives the exact
   recovery commands (acquisition → schema report → materialize).
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
snapshot reports** (v1 and v2) from the **synthetic development fixture** that
all charts and numbers use: the fixture is never presented as real data, and
the real reports are never presented as full-dataset or production results.

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

Real snapshot reports (acquisition needs network once, then offline):

```bash
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json --output-dir data/raw
uv run python -m retail_demand_inventory.data.schema_report \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-schema.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json
```

Expanded (v2) real report — opt-in population manifest + dry-run profile, then
materialize with `--population`:

```bash
uv run python -m retail_demand_inventory.data.population_manifest \
    --source-manifest data/manifests/freshretailnet-real.json \
    --raw-dir data/raw --out data/manifests/freshretailnet-real-population-v2.json
uv run python -m retail_demand_inventory.data.population_profile \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-population-profile-v2.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json \
    --population data/manifests/freshretailnet-real-population-v2.json
```

These regenerate `data/evaluations/experiment_report.json` (fixture),
`data/evaluations/freshretailnet-real-report.json` (v1), and
`data/evaluations/freshretailnet-real-expanded-report.json` (v2)
deterministically.

## What the demo must NOT claim

- No real-world accuracy numbers: every metric is labeled as produced from the
  synthetic fixture.
- The real snapshot reports (v1 and v2), when shown, are labeled as
  deterministic bounded evaluations over the pinned snapshot and are never
  called full-dataset results.
- No assertion that a policy is "best": the demo says the policy was
  "selected under the protocol objective", never "optimal".
