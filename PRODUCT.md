# Product — retail-demand-inventory-decision-engine

Status: **implemented as a synthetic-fixture prototype** (no real data used;
every reported number is explicitly labeled synthetic).

## Platform

Web (local demo) + offline analysis pipeline.

## Users

- Inventory planners who need a defensible restock recommendation.
- Technical evaluators who want to verify the forecast and simulation
  methodology before trusting a number.
- The author: demonstrating forecasting, simulation, and decision-science
  skills with reproducible evidence.

## Problem

Forecasts and inventory policies are only useful if their evidence is
auditable. Without a fixed evaluation protocol, any reported improvement can
be the result of cherry-picking. This product makes the evaluation the
centerpiece: every replenishment decision is traceable to a scored simulation
run.

## What it is NOT yet

- Not a forecast service, no API, no production deployment.
- Not integrated with any live retail system.
- Not claiming any accuracy on real data (none has been audited yet).

## Success metric (product)

A reviewer can run one command, see a forecast and a policy simulation with
baselines, and trace the recommended action to its simulation evidence —
without reading code.

## Risks

- Dataset access: the whole pipeline depends on an audited, licensed source.
- Methodology trust: unfixable splits would invalidate every result.

## No-goals

- No multi-tenant SaaS, no user accounts.
- No mobile app.
- No real-time streaming; batch analysis is the pattern.

## Definition of done

- [ ] Demo answers "should I restock X and why" with evidence in under a minute.
- [ ] Every reported number is reproducible with one command.
- [ ] Baselines and limitations are documented next to results.
