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
8. **Robustness (sensitivity over modeled business assumptions)** — shown only
   when the committed robustness report exists
   (`data/evaluations/freshretailnet-robustness-report-v1.0.0.json`). A
   scenario selector lets the user compare `baseline-v1` against any of the 12
   frozen scenarios for the selected SKU (policy, order quantity, reorder
   point / order-up-to level, service, cost) and shows the cross-key summary
   (policy retention %, change %, infeasible %). It renders the exact labels
   `Sensitivity analysis over modeled business assumptions — not observed
   retailer costs` and `Results are bounded to the deterministic v2 population
   and do not generalize to all retailers.`
9. **Assumptions and limitations** — surfaced verbatim from the report.

The demo visibly distinguishes the **audited source contract**
(`docs/source-contract.md`, FreshRetailNet-50K), the optional **real
snapshot reports** (v1, v2, and the robustness report), and the **synthetic
development fixture** that all charts and numbers use: the fixture is never
presented as real data, the real reports are never presented as full-dataset
or production results, and robustness numbers are never presented as observed
retailer costs.

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

Robustness report — freeze the scenario matrix, then materialize over the v2
population:

```bash
uv run python -m retail_demand_inventory.decisions.scenarios \
    --out data/manifests/robustness-scenarios-v1.0.0.json
uv run python -m retail_demand_inventory.evaluation.robustness_materialize \
    --source real --scenarios data/manifests/robustness-scenarios-v1.0.0.json
```

These regenerate `data/evaluations/experiment_report.json` (fixture),
`data/evaluations/freshretailnet-real-report.json` (v1),
`data/evaluations/freshretailnet-real-expanded-report.json` (v2), and
`data/evaluations/freshretailnet-robustness-report-v1.0.0.json` (robustness)
deterministically.

## What the demo must NOT claim

- No real-world accuracy numbers: every metric is labeled as produced from the
  synthetic fixture.
- The real snapshot reports (v1 and v2), when shown, are labeled as
  deterministic bounded evaluations over the pinned snapshot and are never
  called full-dataset results.
- The robustness report, when shown, is labeled `Sensitivity analysis over
  modeled business assumptions — not observed retailer costs` and `Results are
  bounded to the deterministic v2 population and do not generalize to all
  retailers.` It is never presented as observed retailer costs or as a
  generalization.
- No assertion that a policy is "best": the demo says the policy was
  "selected under the protocol objective", never "optimal".
