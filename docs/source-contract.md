# Source Contract — retail-demand-inventory-decision-engine

Status: **scaffold / implementation not started**

## Purpose

Define the exact requirements a demand dataset must meet before any
forecasting, simulation, or replenishment feature is implemented. This
contract must be satisfied and documented BEFORE code touches real data.

## Required dataset properties

A candidate source must provide, per SKU and time bucket:

| Property | Requirement |
| --- | --- |
| Granularity | SKU x day (or documented, fixed granularity) |
| Demand signal | Observed sales/demand units (integer counts) |
| History length | Enough periods for the chosen forecast horizon and split |
| Calendar | Explicit dates; no implicit frequency assumptions |
| Missingness | Documented policy: zeros, nulls, or discontinuities |
| Price/promotion | Present and documented if used by the model |
| Geography | Documented store/location scope |
| Versioning | Source snapshot is reproducible and versioned |

## Non-goals of the source contract

- No requirement to model every demand driver.
- No requirement for a specific forecast algorithm.

## License and provenance (mandatory gate)

- **Implementation of real data is BLOCKED until the dataset source and
  license are audited and recorded here.**
- Any baseline learned from `demand-inventory-optimizer` is reference
  knowledge only; its code and data are NOT copied.
- Third-party data retains its own terms and is never re-licensed under
  this repository's MIT license.

## Acceptance

- [ ] Candidate dataset listed with source URL and retrieval date.
- [ ] License terms documented verbatim with citation.
- [ ] Required properties above verified against a real sample.
- [ ] Fixture for offline development committed under `data/fixtures/`.
