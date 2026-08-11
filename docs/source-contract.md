# Source Contract — retail-demand-inventory-decision-engine

Status: **audited / ACCEPTED with conditions** (audit date 2026-08-11).
Source data is NOT retained in this repository. The offline prototype runs on
the committed synthetic fixture only (see [Synthetic fixture](#synthetic-fixture-not-an-audited-source-result)).

## Purpose

Define the exact requirements a demand dataset must meet before any
forecasting, simulation, or replenishment feature is implemented, and record
the completed audit of the primary candidate source. This contract must be
satisfied and documented BEFORE code touches real source data.

## Audit record — FreshRetailNet-50K

| Property | Value |
| --- | --- |
| Dataset name | FreshRetailNet-50K |
| Publisher | Dingdong Limited (Hugging Face org `Dingdong-Inc`) |
| Official URL | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K |
| Pinned snapshot (revision) | `08c1fab7f9257bc73679d415d65d644165d351d4` |
| Pinned snapshot URL | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/tree/08c1fab7f9257bc73679d415d65d644165d351d4 |
| Retrieval / audit date | 2026-08-11 |
| Dataset version | 1.0 (release date 2025-05-08) |
| Snapshot semantics | Commit pin on the Hugging Face repo; the exact bytes the dataset card described at audit time |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| License URL | https://creativecommons.org/licenses/by/4.0/legalcode |
| Card statement on use | "This dataset is ready for commercial/non-commercial use." |
| Technical report | arXiv:2505.16319 (https://arxiv.org/abs/2505.16319) |
| Baseline repo | https://github.com/Dingdong-Inc/frn-50k-baseline (reference only, not copied) |
| Size | 4,850,000 rows (train 4.5M / eval 350k), ~115 MB |

### Dataset overview (from the official card, verbatim highlights)

> FreshRetailNet-50K is the first large-scale benchmark for censored demand
> estimation in the fresh retail domain, **incorporating approximately 20%
> organically occurring stockout data**. It comprises 50,000 store-product
> 90-day time series of detailed hourly sales data from 898 stores in 18 major
> cities, encompassing 865 perishable SKUs with meticulous stockout event
> annotations.

## License terms (CC BY 4.0) — verbatim deed and link

The license is the **Creative Commons Attribution 4.0 International License
(CC BY 4.0)**, available at https://creativecommons.org/licenses/by/4.0/legalcode.

The official deed at https://creativecommons.org/licenses/by/4.0/ states,
verbatim:

> **You are free to:**
>
> - **Share** — copy and redistribute the material in any medium or format for
>   any purpose, even commercially.
> - **Adapt** — remix, transform, and build upon the material for any purpose,
>   even commercially.
> - The licensor cannot revoke these freedoms as long as you follow the license
>   terms.
>
> **Under the following terms:**
>
> - **Attribution** — You must give appropriate credit, provide a link to the
>   license, and indicate if changes were made. You may do so in any reasonable
>   manner, but not in any way that suggests the licensor endorses you or your
>   use.
> - **No additional restrictions** — You may not apply legal terms or
>   technological measures that legally restrict others from doing anything the
>   license permits.
>
> **Notices:**
>
> - You do not have to comply with the license for elements of the material in
>   the public domain or where your use is permitted by an applicable exception
>   or limitation.
> - No warranties are given. The license may not give you all of the permissions
>   necessary for your intended use. For example, other rights such as
>   publicity, privacy, or moral rights may limit how you use the material.

The deed carries the following notice: it "highlights only some of the key
features and terms of the actual license. It is not a license and has no legal
value. You should carefully review all of the terms and conditions of the
actual license before using the licensed material." The legal code is the
binding instrument: https://creativecommons.org/licenses/by/4.0/legalcode.

### Permitted use

- Commercial and non-commercial use are permitted (dataset card statement plus
  CC BY 4.0 Share/Adapt freedoms).
- Attribution is required (Section 3 of the legal code).
- No warranty is granted by the licensor; the user is responsible for
  confirming the license fits the intended purpose (dataset card, "Intended
  use").

### Attribution / citation

Per the dataset card, cite:

```bibtex
@article{2025freshretailnet-50k,
      title={FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail},
      author={Yangyang Wang, Jiawei Gu, Li Long, Xin Li, Li Shen, Zhouyu Fu, Xiangjun Zhou, Xu Jiang},
      year={2025},
      eprint={2505.16319},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2505.16319},
}
```

Where any real FreshRetailNet data is used (future work), the dataset name,
publisher, version, pinned revision, and license must be recorded next to the
results, and this repository's code must carry the CC BY 4.0 notice for that
data. The repo's own MIT license covers only original code; it never
re-licenses third-party data.

## Redistribution / retention decision

- **Do NOT retain source data in this repository.** No `data/raw/` or
  `data/processed/` files are committed (`data/raw/` and `data/processed/` are
  gitignored).
- If source data is ever downloaded for a run, it lives outside the repository
  (documented path), is recorded in a manifest with SHA256 checksums, and is
  never pushed.
- Distribution of the dataset by this project is out of scope; consumers
  retrieve it from the official pinned revision.

## Source fields used and canonical mapping

The official split exposes these fields (verbatim names from the card):
`city_id, store_id, management_group_id, first_category_id, second_category_id,
third_category_id, product_id, dt, sale_amount, hours_sale, stock_hour6_22_cnt,
hours_stock_status, discount, holiday_flag, activity_flag, precpt,
avg_temperature, avg_humidity, avg_wind_level`.

| Source field | Canonical field | Notes |
| --- | --- | --- |
| `dt` | `date` | Daily grain, ISO date string |
| `store_id` + `product_id` | `sku` | Canonical key `"{store_id}|{product_id}"` (store-product grain; 90-day series per store-product) |
| `sale_amount` | `demand_units` | Daily sales after **global normalization** (card: "Multiplied by a specific coefficient"). **Continuous non-negative float; NOT an integer count.** |
| `first_category_id` | `category` | First-level category as the coarse grouping key |
| `stock_hour6_22_cnt` / `hours_stock_status` | `stockout_flag` | A day is a stockout day when the hourly out-of-stock status indicates exhaustion. Exact derivation to be finalized at ingestion time; see censoring note below |
| `discount`, `holiday_flag`, `activity_flag`, `precpt`, `avg_temperature`, `avg_humidity`, `avg_wind_level` | — (reserved) | Retained in the source loader path for future feature work; NOT part of the canonical demand record v1 (optional fields are only added when actually used by a model) |

The `train`/`eval` split shipped by the publisher is **not** used: this project
re-splits chronologically per `docs/evaluation-protocol.md`.

## Missingness, filtering, aggregation, transformation rules

- **Granularity**: store-product × day. No aggregation is applied; rows are
  already at the target grain. Duplicate `(sku, date)` keys are a validation
  error.
- **Missing days**: internal gaps within a SKU's span are filled with
  `demand_units = 0.0` and `stockout_flag = None`. Rationale: a missing day is
  absence of a record, not evidence of a stockout. Filling keeps the canonical
  table on a strict daily cadence (validated by `DemandTable`).
- **Missing cells** in the used source fields (`dt`, `store_id`, `product_id`,
  `sale_amount`, `first_category_id`): the row is a validation error; loaders
  raise with the offending row.
- **Filters**: none in v1 beyond dropping rows whose used fields are invalid.
- **Transformation**: `sale_amount` is taken as-is (already normalized); the
  canonical field is documented as continuous, non-negative observed units.

## Stockout censoring limitation

`demand_units` is **observed sales**, which is **censored** during stockout
hours: when stock runs out, sales cannot rise to meet unconstrained demand.
FreshRetailNet is specifically a *censored-demand* benchmark (~20% organic
stockouts). Therefore:

- `stockout_flag` is preserved in canonical data.
- **Forecasts target observed sales, not unconstrained demand.** No claim of
  latent-demand recovery is made in this prototype.
- Policy simulation treats demand as an exogenous observed series; stockout
  costs in simulation are about the policy under test, not about censoring in
  the source.

## Checksum and manifest policy

- Every data artifact that is retained (fixture, generated evaluation report)
  is declared in a committed manifest under `data/manifests/` with a SHA256
  checksum (see `src/retail_demand_inventory/data/manifests.py`).
- If real FreshRetailNet data is ever captured, its manifest records the pinned
  revision, retrieval date, file-level SHA256 checksums, and the decision to
  keep it out of the repository.
- Checksums are verified before any loader consumes the artifact.

## Synthetic fixture — NOT an audited-source result

`data/fixtures/freshretailnet_style_synthetic.csv` is a **small, clearly
labeled synthetic series** (2 SKUs, ~120 daily points) created for offline
development, tests, and the demo. It is styled after the audited source's grain
(store-product × day, normalized continuous demand, `stockout_flag`) but is
**not derived from, sampled from, or representative of FreshRetailNet-50K**.
No number produced from it is a real-world result.

## Acceptance

- [x] Candidate dataset listed with source URL, pinned revision, and retrieval date (2026-08-11).
- [x] License terms (CC BY 4.0) documented verbatim with legal-code link and permitted-use statement.
- [x] Required source properties verified against the official card (grain, demand signal, history length, calendar, missingness, versioning).
- [x] Canonical mapping, missingness/filtering/transformation rules, and stockout censoring documented above.
- [x] Checksum/manifest policy defined.
- [x] Synthetic fixture committed under `data/fixtures/` and clearly labeled.

**Acceptance status: ACCEPTED with conditions.** The contract is satisfied for
methodology development on the synthetic fixture. **Real-data ingestion
remains BLOCKED** until: (1) the pinned revision is downloaded and file-level
checksums are recorded in `data/manifests/`, (2) the stockout-day derivation
rule is finalized against the real `hours_stock_status` bytes, and (3) the
retention decision is re-confirmed. None of those steps have happened.
