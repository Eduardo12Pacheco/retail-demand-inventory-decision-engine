# Evaluation Protocol — retail-demand-inventory-decision-engine

Status: **implemented (protocol version 1.0)** — fixed BEFORE any report is
materialized.

## Purpose

Define exactly how forecasts, inventory policies, and replenishment decisions
are measured. The protocol is fixed before results are produced so that
reported numbers are not shaped to look good. This document is normative; the
materializer (`src/retail_demand_inventory/evaluation/materialize.py`) encodes
it.

## Data frequency and calendar

- **Frequency**: daily. The canonical `DemandTable` is on a strict daily
  cadence per SKU; internal missing days are filled with `demand_units = 0.0`
  and `stockout_flag = None` by the loaders (see `docs/source-contract.md`).
- All dates in a SKU's series are consecutive calendar days.

## Minimum history

- `MIN_TRAIN_PERIODS = 42` days. A SKU must have at least this many
  observations before the first fold to be evaluated. The fixture provides
  ~120 days per SKU, so all SKUs qualify.

## Splits (chronological, no leakage)

- **Horizon**: `HORIZON = 7` days.
- **Final untouched test**: the last `FINAL_TEST_PERIODS = 14` days of the
  calendar. This window is **never** used for model or policy selection; it is
  used only for final reporting of the already-selected model.
- **Backtest window**: all dates before the final test.
- **Origins**: expanding-window rolling origins over the backtest window.
  - Train window: `calendar[0 : origin]` (expanding; origin is the split point).
  - Validation window: `calendar[origin : origin + HORIZON]`.
  - Origin step = `HORIZON`, so consecutive validation windows are **disjoint
    (no overlap)** and each fold's train strictly precedes its validation.
  - A fold exists only if `len(train) >= MIN_TRAIN_PERIODS`.
- Splits are computed by `data/splits.py` and validated (no overlap between
  folds, no fold touches the final test, train never contains validation or
  final-test dates).

## SKU criteria

- A SKU is evaluated if it has a continuous daily series that supports the
  required minimum history, at least one fold, and the final test window.
  The fixture defines 2 SKUs that meet these criteria.

## Missing-day and stockout treatment

- Missing days are absent from the raw rows and are filled as zeros by the
  loaders; they are then ordinary (zero-demand) days.
- `stockout_flag` days remain in the series with their observed (possibly
  zero) demand. **Forecasts target observed sales, not unconstrained demand**;
  censoring is documented, not corrected.

## No future-feature leakage

- Forecast models consume only: past observed demand (lags and rolling
  statistics) and **calendar features derived from the date itself**
  (day-of-week, day-of-month, month, day-of-year, weekend flag).
- Future covariates (discount, holiday, activity, weather) are **not** used,
  so no unobserved-future feature can leak into a prediction. Calendar features
  for future dates are deterministic.

## Randomness

- Fixed seed `SEED = 20260811`. The pipeline is fully deterministic: any
  stochastic step (currently none is required, but the seed is fixed
  regardless) draws from `random.Random(SEED)` / sklearn's fixed
  configuration. Two runs of the materializer with identical inputs produce
  byte-identical reports.

## Hyperparameter policy

- All model and policy hyperparameters use the documented defaults fixed in
  code (see module docstrings). **No per-SKU or per-fold tuning** is
  performed, to avoid selection bias on the evaluation data. Versioned
  `model_version` / `policy_version` identifiers identify the exact
  configuration that produced every number.

## Metrics

All metrics compare observed demand `a_t` with predicted demand `f_t` over a
window of length `n`. A metric that is undefined returns `None` and is
reported as such; undefined values never silently count as zero.

| Metric | Definition | Undefined case |
| --- | --- | --- |
| MAE | `mean(|a_t - f_t|)` | no observations → `None` |
| RMSE | `sqrt(mean((a_t - f_t)^2))` | no observations → `None` |
| WMAPE | `sum(|a_t - f_t|) / sum(a_t)` | `sum(a_t) == 0` → `None` |
| MASE | `MAE / mean(|e_naive|)` where `e_naive` are in-sample one-step naive errors from the training window of the same fold | training naive errors absent or `mean(|e_naive|) == 0` → `None` |

## Reporting granularity

- **Per fold**: each fold's per-model metrics.
- **Per model**: pooled metrics across all folds plus the mean of per-fold
  metrics.
- **Per SKU** and **per category**: pooled metrics grouped by that key.
- **Per horizon**: horizons are fixed at `HORIZON` in this protocol; the
  summarizer still keys on horizon so the report structure survives a change
  of horizon.
- All reported numbers are rounded to 6 decimal places.

## Model selection

- Selection happens **per SKU** and uses **validation folds only** (never the
  final test).
- Rule: minimize pooled validation **MAE**; tie-break on lower pooled
  **WMAPE**; final tie-break on lexicographically smaller `model_id`.
- After selection, the chosen model is refit on all data preceding the final
  test and evaluated on the final test (reported as `final_test`), and refit
  on all history to produce the deployment forecast for the next `HORIZON`
  days.

## Policy simulation and selection

- Policies are simulated with the deterministic daily lost-sales engine
  (`simulation/engine.py`); each run has an auditable run ID over its config,
  policy, versions, seed, and demand source.
- **Policy evaluation window**: the last fold's validation window demand
  (observed sales). The final test is **not** used for policy selection.
- Candidate policies are generated deterministically from per-SKU demand
  statistics (mean/standard deviation) with documented parameters.
- Selection objective: **minimize total cost subject to service level ≥
  `SERVICE_LEVEL_TARGET = 0.90`**, where total cost =
  holding + stockout + ordering cost over the simulated window.
- Infeasible case (no candidate reaches the target): fall back to the
  candidate with the highest simulated service level (tie → lower cost) and
  report `feasible = false` with a transparent reason. This is a fallback,
  not an "optimal" solution — no selection in this project is ever labeled
  optimal.
- Deterministic tie-break between feasible candidates: lower total cost, then
  lower stockout units, then lexicographically smaller run ID.
- **Sensitivity**: the selected policy is re-simulated on demand scaled by
  `{0.9, 1.0, 1.1}`; service level, fill rate, and total cost are reported per
  scale.

## Assumptions and limitations (normative)

1. Demand is exogenous to the policy: inventory availability does not change
   the demand series used in simulation.
2. Sales lost during a stockout are **lost, not backlogged**.
3. Orders placed at the end of a review day arrive at the **start of the day
   `lead_time` days later**; lead time is constant; supply is unlimited.
4. Holding cost is charged on end-of-day on-hand inventory; ordering cost is
   charged per order placed; stockout cost is charged per lost unit.
5. Review happens after demand for the day (end-of-period review).
6. No perishability/expiry, no quantity discounts, no capacity limits.
7. Forecasts target **observed sales**; censored demand during stockouts is
   not recovered.
8. The fixture is synthetic; **no reported number is a real-world result**.

## Definition of done for evaluation

- [x] Splits, seeds, horizons, and metric formulas committed in this document.
- [x] A single reproducible command reproduces every reported number:
  `uv run python -m retail_demand_inventory.evaluation.materialize`.
- [x] Baseline comparison (naive forecast) is included in every report.
- [x] Every recommendation cites the simulation run IDs that support it.
