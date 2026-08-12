# Decision Robustness Protocol — retail-demand-inventory-decision-engine

Status: **implemented (scenario manifest `robustness-scenarios-v1.0.0`,
protocol version 1.0)** — the scenario matrix was frozen BEFORE any robustness
metric was materialized.

## Purpose

Decision robustness measures how the replenishment decision layer responds to
**modeled business assumptions**: service targets, cost multipliers, lead
times, review cadence, and a forecast-stress demand scale. It re-runs the
decision pipeline over the **existing v2 population** with the same source
facts, forecasts, candidate policies, seed, horizon, and folds, varying only
the declared assumption of each scenario. It answers: *does the selected policy
(and its order quantity / reorder point) change under plausible assumption
changes?*

**Modeled costs, lead times, and service targets are NOT observed retailer
facts.** They are documented assumptions from `docs/evaluation-protocol.md`,
multiplied by scenario multipliers for this analysis.

## Quick path

1. Freeze the matrix: `data/manifests/robustness-scenarios-v1.0.0.json` (typed
   generator: `src/retail_demand_inventory/decisions/scenarios.py`).
2. Materialize:
   `uv run python -m retail_demand_inventory.evaluation.robustness_materialize
   --source real --scenarios data/manifests/robustness-scenarios-v1.0.0.json`
3. Read `data/evaluations/freshretailnet-robustness-report-v1.0.0.json`; the
   baseline-v1 scenario must equal the current v2 decisions.

## Source facts vs modeled assumptions

| Kind | Item | Origin |
| --- | --- | --- |
| Source fact | Pinned revision, raw SHA-256, canonical checksum | `data/manifests/freshretailnet-real.json` + verified `data/raw/` |
| Source fact | v2 population (100 keys / 10 stores / 40 products) | `data/manifests/freshretailnet-real-population-v2.json` |
| Source fact | Stockout derivation (`stock_hour6_22_cnt > 0`; zero sales never imply a stockout) | audited source contract |
| Source fact | Observed-sales semantics (censored demand documented, not recovered) | `docs/source-contract.md` |
| Modeled assumption | Service targets, cost multipliers, lead/review, demand stress | scenario manifest (this analysis) |
| Modeled assumption | Baseline costs 0.10/2.00/5.00 per unit | `docs/evaluation-protocol.md` |

The report separates the two: top-level `source_facts` (never changed by any
scenario) and `modeled_assumptions` (varied). **Nothing in the cost/lead/service
columns is observed retailer data.**

## Baseline exact configuration

`baseline-v1` is the exact current reference and must reproduce the current v2
decisions:

- Service target `0.90`; lead time `3` days; review period `1` day.
- Holding `0.10` / unit / day; stockout `2.00` / lost unit; ordering `5.00` /
  order (multipliers `1.0`).
- Selection demand: observed last-validation-fold demand, **unscaled**.
- Deployment/simulation demand: the deployment forecast, **unscaled**; the
  `{0.9, 1.0, 1.1}` sensitivity scales apply as in the primary protocol.

## The frozen scenario matrix (12 scenarios)

Stable IDs; one-factor-at-a-time plus joint stress cases. Baseline first, then
OFAT cost, lead, review, service, one joint case, and demand stress last. All
other parameters are invariant (see below).

| ID | Change from baseline | Rationale |
| --- | --- | --- |
| `baseline-v1` | none (exact current reference) | Reproduces current v2 decisions; comparison reference |
| `holding-high` | holding multiplier `2.0` | Higher holding should reduce inventory coverage |
| `stockout-high` | stockout multiplier `2.0` | Higher stockout should raise service coverage |
| `ordering-high` | ordering multiplier `2.0` | Higher fixed order cost favors larger, less frequent orders |
| `costs-low` | holding/stockout/ordering `0.5` | Uniform deflation: checks selection is not scale-driven |
| `lead-short` | lead time `2` days | Shorter supply lead |
| `lead-long` | lead time `5` days | Longer supply lead |
| `review-weekly` | review period `7` days | Weekly review cadence |
| `lead-review-long` | lead `5` and review `7` (joint stress) | Compounds lead + review stress |
| `service-085` | service target `0.85` | Relaxed decision target |
| `service-095` | service target `0.95` | Tightened decision target |
| `demand-stress-high` | demand scale `1.30` (scenario simulation only) | 30% forecast-stress on the deployment/simulation window |

## Unchanged protocol parameters (invariant)

Source facts, the v2 population, forecast models/versions (`naive`,
`moving_average`, `ses`, `hist_gradient_boosting`), candidate policy
families/versions, horizon `7`, temporal folds (expanding origins, final test
untouched), seed `20260811`, and observed selection-window semantics. The
backtest is computed once per population and reused; **no forecast is retrained
and no policy is tuned from scenario outcomes.**

## v2 evaluation population

The exact v2 population from `freshretailnet-real-population-v2.json`
(100 store-product keys across 10 stores, 40 products, ~9,700 canonical rows).
Selection uses metadata only; results are bounded to these keys and do not
generalize to all retailers.

## Selection objective and tie-break

Objective: **minimize total cost subject to simulated service level ≥ scenario
target**; infeasible → transparent highest-service fallback with
`constraint_satisfied = false`. Feasible tie-break: lower total cost, then
lower stockout units, then lower avg inventory, then smaller run ID. Fallback
tie-break: highest service, then lower cost, then smaller run ID. Selection is
among generated candidates and is never labeled optimal.

## Scenario-only demand stress

`demand-stress-high` models `scale 1.30` **only on the deployment/simulation
stress window**: the recommendation simulation and the `{0.9, 1.0, 1.1}`
sensitivity runs use the deployment forecast multiplied by `1.30` (effective
sensitivity scales `1.17 / 1.30 / 1.43`). Source demand, forecast training,
final-test evaluation, and **policy candidate selection** are untouched —
selection always uses the observed selection-window demand unscaled.

## Interpretation rules

- Compare each scenario against `baseline-v1` **per key**; deltas are scenario
  minus baseline on the deployment-window recommendation outcome.
- `policy_retained` means the same `policy_id` was selected; a change in params
  alone is recorded in `trigger_level`/`order_quantity` deltas.
- Relative deltas are undefined (reported `null`) when the baseline value is 0.
- Feasibility/fallback counts come from the selection result, not the
  deployment outcome.
- `observed_tradeoffs` are neutral descriptive summaries (cost vs service,
  inventory vs fill, stockouts vs holding). **Nothing is a Pareto or optimality
  claim.**

## Deterministic serialization and timestamps

Fixed seed, fixed protocol, and the documented deterministic timestamp
(`SOURCE_DATE_EPOCH` when set, else `2026-08-11T00:00:00+00:00`); sorted-key
JSON with fixed indentation. Two identical runs produce byte-identical reports.
The scenario manifest records a stable `content_sha256` over its canonical
serialization. Runtime is recorded as a documented constant, never a
wall-clock number, so repeated output stays byte-identical.

## Limitations

- All numbers are sensitivity analyses over the deterministic v2 population;
  they are NOT observed retailer costs and do not generalize.
- Modeled costs/lead times/service targets are assumptions, not measured facts.
- The demand-stress scenario is a modeled forecast-stress assumption; it does
  not alter source demand or training.
- No optimality/Pareto claim; summaries are neutral observations.
- Raw data stays in the gitignored `data/raw/`; only checksums are committed.

## Definition of done

- [x] Scenario matrix frozen and committed before metrics are materialized.
- [x] `baseline-v1` reproduces the current v2 decisions.
- [x] One command reproduces the report byte-identically.
- [x] Source facts and modeled assumptions are separated in the report.
- [x] Robustness report is distinct and never overwrites v1/v2 reports.
