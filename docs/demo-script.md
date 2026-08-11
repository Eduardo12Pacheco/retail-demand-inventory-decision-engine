# Demo Script — retail-demand-inventory-decision-engine

Status: **scaffold / implementation not started**

## What the demo will show

A single retail scenario where the user picks a SKU and an inventory policy,
and sees:

1. The demand history with the forecast over the horizon.
2. Simulated outcomes (service level, stockouts, mean inventory) for the
   chosen policy versus a baseline.
3. The proposed replenishment decision with the evidence behind it.

## Constraint

The demo runs ONLY on committed fixtures or audited, licensed data. It never
performs live network fetches.

## Run book (once implemented)

```bash
uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## What the demo must NOT claim

- No real-world accuracy numbers before the evaluation protocol is executed.
- No assertion that a policy is "best" without the simulation evidence.
