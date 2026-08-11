# Design — retail-demand-inventory-decision-engine

Status: **scaffold / implementation not started**

## Problem

Retailers need demand forecasts and inventory policies that are defensible:
a forecast that is never compared to reality, or a policy tuned to look good
on past data, is not a decision engine. This project builds a small,
reproducible pipeline from demand data to a replenishment recommendation,
with evaluation as a first-class citizen.

## Planned architecture

```text
src/retail_demand_inventory/
├── data/          # typed loaders over the source contract
├── forecasting/   # forecast models behind one interface
├── simulation/    # discrete-event inventory policy simulation
├── decisions/     # replenishment rules over simulation output
└── evaluation/    # protocol-driven metrics
```

Each layer is replaceable and only depends on documented interfaces.

## Key decisions (scaffold phase)

| Topic | Decision |
| --- | --- |
| Language | Python >=3.11, `uv`, hatchling src layout |
| Forecast interface | To be designed once the source contract is met |
| Simulation | Discrete-event, fixed seed, policy-in → outcomes-out |
| Evidence | Every recommendation must cite the simulation run that supports it |
| Demo | Local Streamlit app reading committed fixtures only |

## No-goals

- No live store integration, no real POS ingestion yet.
- No claim of production readiness for real business decisions.
- No copying of `demand-inventory-optimizer` code or data.

## Risks

- Dataset license/source unavailable → forecast work is blocked by design.
- Data leakage in splits → prevented by fixed-time evaluation protocol.
- Overfit policies → baseline comparisons required in every report.

## Definition of done (for the project, not just scaffold)

- [ ] Source contract satisfied with an audited, licensed dataset.
- [ ] Reproducible forecast + simulation + decision pipeline.
- [ ] Evaluation protocol executed and reported.
- [ ] Demo runs from fixtures with no network access.
- [ ] No unsupported claims in README or docs.
