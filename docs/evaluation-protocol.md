# Evaluation Protocol — retail-demand-inventory-decision-engine

Status: **scaffold / implementation not started**

## Purpose

Define how forecasts, inventory policies, and replenishment decisions are
measured. The protocol is fixed BEFORE implementation so results are not
shaped to look good.

## Components

1. **Forecast evaluation** — train/test split fixed by time (no leakage),
   rolling or walk-forward origin, and reported with confidence intervals.
   Primary metric: MAE. Secondary: WAPE, MASE (baseline: naive), bias.
2. **Inventory policy simulation** — discrete-event simulation over held-out
   demand with a fixed random seed. Reports service level, fill rate, mean
   inventory, and expired/stockout events.
3. **Replenishment decision** — policy rules and their parameters are evaluated
   in simulation first; the decision layer only proposes actions that the
   simulator has scored.

## Honesty rules

- No metric is reported before its protocol definition is committed.
- Baselines are reproduced in-repo; external results are not claimed.
- Results are limited to the exact data slice described in the source contract.

## Definition of done for evaluation

- [ ] Splits, seeds, and metric formulas are committed in this doc.
- [ ] A single reproducible command reproduces every reported number.
- [ ] Baseline comparison (naive forecast, current policy) is included.

## Demo script

See `docs/demo-script.md` for the human-facing walkthrough.
