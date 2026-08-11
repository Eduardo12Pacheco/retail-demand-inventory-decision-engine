# Source Contract — retail-demand-inventory-decision-engine

Status: **audited / ACCEPTED with conditions; real snapshot acquired, verified,
and evaluated on a bounded population** (audit + acquisition date 2026-08-11).
Source data is NOT retained in this repository (raw files live in the
gitignored `data/raw/`). Offline development/tests/demo run on the committed
synthetic fixture (see [Synthetic fixture](#synthetic-fixture-not-an-audited-source-result)).

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

### Evidence URLs (exact, pinned)

| Resource | URL |
| --- | --- |
| Dataset page | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K |
| Pinned tree | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/tree/08c1fab7f9257bc73679d415d65d644165d351d4 |
| Pinned README | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/raw/08c1fab7f9257bc73679d415d65d644165d351d4/README.md |
| Train resolve URL | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/08c1fab7f9257bc73679d415d65d644165d351d4/data/train.parquet |
| Eval resolve URL | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/08c1fab7f9257bc73679d415d65d644165d351d4/data/eval.parquet |

### Acquired raw files (local, gitignored) — observed vs HF metadata

The raw files are kept ONLY under `data/raw/` (gitignored, never committed).
Observed sizes and SHA-256 were computed over the untouched downloaded bytes;
the expected values are the HF LFS metadata reported at the pinned revision.
Both files matched exactly, and the resolve endpoint reported
`x-repo-commit == 08c1fab7…` at download time.

| Split | Local file (under `data/raw/`) | Rows | Expected size (HF) | Observed size | Expected SHA-256 (HF LFS) | Observed SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| train | `freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-train.parquet` | 4,500,000 | 106,436,287 | 106,436,287 | `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d` | `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d` |
| eval | `freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-eval.parquet` | 350,000 | 8,440,124 | 8,440,124 | `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da1095e960e` | `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da1095e960e` |

All expected and observed values are recorded in
`data/manifests/freshretailnet-real.json` (committed). Verification is
re-runnable offline with:

```bash
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json \
    --output-dir data/raw --mode verify
```

## Schema findings (from the actual parquet bytes)

- `train.parquet` and `eval.parquet` expose the exact 19 columns documented in
  the pinned README, with these types (verified against the bytes):
  `city_id int64, store_id int64, management_group_id int64, first_category_id
  int64, second_category_id int64, third_category_id int64, product_id int64,
  dt string, sale_amount double, hours_sale list<double>, stock_hour6_22_cnt
  int32, hours_stock_status list<int64>, discount double, holiday_flag int32,
  activity_flag int32, precpt double, avg_temperature double, avg_humidity
  double, avg_wind_level double`.
- Minor discrepancy: the README's Python-feature spec describes
  `hours_stock_status` as `sequence(int32)`, but the parquet bytes carry
  `list<int64>`. The loader does not consume that column; it is preserved raw
  for audit only.
- Both files have zero nulls in the used columns (`store_id`, `product_id`,
  `dt`, `sale_amount`, `first_category_id`, `stock_hour6_22_cnt`).
- All 50,000 store-product keys appear in both splits; every key has exactly
  97 daily rows covering `2024-03-28 → 2024-07-02` with no internal gaps.
- `sale_amount` is a non-negative continuous float (0.0–49.9 observed), i.e.
  normalized sales, not an integer count.
- `stock_hour6_22_cnt` ranges 0–16 (README documents 0–17).

See `data/reports/freshretailnet-real-schema.json` for the deterministic schema
report over the bounded population.

## Raw vs canonical checksums

- **Raw checksums** are SHA-256 over the untouched parquet bytes (above). They
  prove byte-identity with the pinned revision.
- **Canonical-content checksum** is SHA-256 over a deterministic JSON
  serialization of the canonical records (`sku, date, demand_units, category,
  stockout_flag`) of the bounded population:
  `cc7c57e6bd4071e1628e79833869ed7e11d856236c8db5da399fa21955ebd160`.
  It proves that the loaded canonical table is reproducible from the raw bytes,
  independent of any file-format details. Real-mode materialization fails if
  either set of checksums mismatches.

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

- **Do NOT commit source data in this repository.** `data/raw/` and
  `data/processed/` are gitignored; the acquired raw parquet files live under
  `data/raw/` for audit and are never committed or pushed.
- The committed `data/manifests/freshretailnet-real.json` records the pinned
  revision, retrieval date, expected + observed file-level SHA-256 checksums,
  and the retention decision. Distribution of the dataset by this project is
  out of scope; consumers retrieve it from the official pinned revision.

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
| `stock_hour6_22_cnt` | `stockout_flag` | **Finalized direct derivation**: a day is a stockout day iff `stock_hour6_22_cnt > 0` (documented count of out-of-stock hours in 06:00–22:00); validated integer in 0..17; a missing value stays unknown (`None`). **Never inferred from zero sales.** |
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

- `stockout_flag` is preserved in canonical data, derived directly from the
  documented `stock_hour6_22_cnt > 0` field (never from zero sales). Verified
  on the real bytes: stockout days retain positive sales (partial-hour
  stockouts), so a zero-sales rule would be wrong for this data.
- **Forecasts target observed sales, not unconstrained demand.** No claim of
  latent-demand recovery is made in this prototype.
- Policy simulation treats demand as an exogenous observed series; stockout
  costs in simulation are about the policy under test, not about censoring in
  the source.

## Checksum and manifest policy

- Every data artifact that is retained (fixture, generated evaluation report,
  real schema report) is declared in a committed manifest under
  `data/manifests/` with SHA256 checksums
  (see `src/retail_demand_inventory/data/manifests.py` and
  `src/retail_demand_inventory/data/real_manifest.py`).
- The real snapshot manifest (`data/manifests/freshretailnet-real.json`)
  records: dataset id, pinned revision, source URLs, publisher, license +
  attribution + citation, access method, raw files (expected sizes, expected
  HF-LFS SHA-256, observed sizes, observed SHA-256), canonicalization
  version/rule, canonical-content SHA-256, schema report path, stockout
  derivation version/rule, and five explicit gates
  (`source_verified`, `license_verified`, `snapshot_verified`,
  `schema_verified`, `stockout_semantics_verified`). All five gates are true.
- **Missing observed checksums FAIL real-mode verification** (no silent pass);
  the optional-checksum behavior exists only for the synthetic fixture.
- Checksums are verified before any loader consumes the artifact; real-mode
  materialization additionally verifies the canonical-content checksum.

## Synthetic fixture — NOT an audited-source result

`data/fixtures/freshretailnet_style_synthetic.csv` is a **small, clearly
labeled synthetic series** (2 SKUs, ~120 daily points) created for offline
development, tests, and the demo. It is styled after the audited source's grain
(store-product × day, normalized continuous demand, `stockout_flag`) but is
**not derived from, sampled from, or representative of FreshRetailNet-50K**.
No number produced from it is a real-world result.

## Remaining limitations (real snapshot)

- The evaluation runs on a **deterministic bounded population** (first 10
  store-product keys under the documented rule), not the full 50,000-key
  snapshot; it is labeled
  `Deterministic bounded evaluation over pinned snapshot` and does not
  generalize to other keys, periods, or retailers.
- `demand_units` is **observed sales**; censored demand during stockouts is
  documented, not recovered.
- Forecasts use only lags, rolling statistics, and calendar features;
  discount/holiday/activity/weather covariates are not consumed yet.
- Raw parquet bytes are retained locally in gitignored `data/raw/` for audit;
  they are never committed and never redistributed by this project.

## Acceptance

- [x] Candidate dataset listed with source URL, pinned revision, and retrieval date (2026-08-11).
- [x] License terms (CC BY 4.0) documented verbatim with legal-code link, attribution, and permitted-use statement.
- [x] Required source properties verified against the official card and against the actual parquet bytes (grain, demand signal, history length, calendar, missingness, versioning).
- [x] Canonical mapping, missingness/filtering/transformation rules, and stockout censoring documented above.
- [x] Raw files acquired from the pinned revision; exact sizes and raw SHA-256 observed and recorded (match HF LFS metadata).
- [x] Schema verified against the bytes; schema report committed under `data/reports/freshretailnet-real-schema.json`.
- [x] Stockout derivation finalized as `stock_hour6_22_cnt > 0` and verified on real bytes (never from zero sales).
- [x] Canonical-content SHA-256 computed and recorded; raw-vs-canonical checksum distinction documented.
- [x] Checksum/manifest policy defined and enforced for real snapshots.
- [x] Synthetic fixture committed under `data/fixtures/` and clearly labeled.

**Acceptance status: ACCEPTED with conditions.** Methodology development on the
synthetic fixture and a **deterministic bounded evaluation on the pinned real
snapshot** (10 of 50,000 keys) are both implemented and reproducible. The real
evaluation remains **bounded** by design; no full-dataset, production, or
generalization claim is made.
