# Retail Demand Inventory Decision Engine

Status: **scaffold / implementation not started.**

A greenfield project for demand forecasting, inventory policy simulation, and
replenishment decisions, built with reproducible evidence at its center. This
README is the project contract and will be updated as the system becomes real.

## What this will be

- A forecast of demand per SKU over a fixed horizon.
- A discrete-event simulation of inventory policies (service level, fill rate,
  stockouts, mean inventory).
- A replenishment decision layer that only proposes actions the simulation has
  scored.
- A local Streamlit demo that reads committed fixtures only.

## What this is NOT yet

- No code beyond the workspace scaffold.
- No dataset, no real metrics, no claimed results.
- **No real data is implemented until the source and license are audited**
  (see `docs/source-contract.md`).

## Relationship to demand-inventory-optimizer

This is an independent project. It may study the baselines in
`demand-inventory-optimizer` for methodology reference, but it does not copy
that code or data, and it claims nothing from that project's results.

## Planned architecture

```text
src/retail_demand_inventory/
├── data/          # typed loaders over the source contract
├── forecasting/   # forecast models behind one interface
├── simulation/    # discrete-event inventory policy simulation
├── decisions/     # replenishment rules over simulation output
└── evaluation/    # protocol-driven metrics
```

Design decisions and no-goals: `DESIGN.md`. Product intent: `PRODUCT.md`.

## Evidence that will be required

- Source contract satisfied (`docs/source-contract.md`).
- Evaluation protocol committed BEFORE results (`docs/evaluation-protocol.md`).
- Every number reproducible by one command.
- Baselines and limitations reported alongside results.

## Data and license limits

- Third-party data retains its own terms; this repo's MIT license covers only
  original code.
- `data/raw/` and `data/processed/` are never committed.
- Small fixtures and manifests are committed for offline development.

## Running the scaffold

```bash
uv sync --dev
uv run pytest          # passes: workspace contract tests only
uv run ruff check .
```

The demo command will be added when the demo exists
(`docs/demo-script.md`).
