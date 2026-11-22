# Specification: Design-Principle Effect Runs (manuscript Sec. 3.2.1 / 4.1)

Status: **spec agreed 2026-11-22, not implemented.** Scope: model runs only. The evaluation
(metrics, figures) is work in progress and not part of this spec.

## Goal

Provide the runs for RQ2: *how does implementing the design principles of a nationally tailored
ESM change model outcomes relative to an over-regional model?* Manuscript Sec. 2.2 defines three
principles. Validation is cross-cutting and **not** part of these runs.

| ID | Principle (Sec. 2.2) | Switched in this study |
|---|---|---|
| P1 | Integration of country-specific data | KLIEN renewable potentials and KLIEN existing onshore-wind capacities for AT |
| P2 | Adequate spatial (and temporal) granularity | AT at NUTS 3 (AT35) vs NUTS 2 (AT10) |
| P3 | Country-centred policy representation and international embedding | all national AT policy constraints |

Design rule (Sec. 3.2): **each comparison differs in one choice only.** Every principle gets a
pair: `DP_base` (full PyPSA-AT) vs a run without the principle.

## Common setup

- Overlay: `config/config.carbon-accounting.yaml` (reduced PyPSA-AT, Gurobi), technology-based
  carbon accounting in all DP runs, so the DP results are independent of RQ3.
- Spatial resolution: **AT35DE5** for all DP runs except `DP2_at10`. The 30-min solve target of
  the overlay does not apply to DP runs.
- Planning horizons: 2025, 2030, 2040, 2050 (from `config/config.at.yaml`).
- Temporal resolution: inherited (`clustering.temporal`). If AT35 does not solve in acceptable
  time, coarsen it **for all DP runs alike** (never for one run of a pair only).
- Scenarios go into `config/scenarios.carbon-accounting.yaml` and `run.name` of
  `config/config.carbon-accounting.yaml`; results land in `results/carbon-accounting/<scenario>/`.
- Scenario `mods` are deep-merged (`update_config`): keys can be overwritten, not deleted.

## Runs

| Scenario | Principle | Differs from `DP_base` by |
|---|---|---|
| `DP_base` | – | `CA_base` + `mods.modify_nuts3_shapes: AT35DE5`, `clustering.administrative.AT: 3` |
| `DP1_no_national_data` | P1 | KLIEN potential caps off (`mods.klien_potential_limits.technologies: []`, PyPSA-Eur/ERA5 potentials apply) **and** KLIEN onwind brownfield off (PyPSA-Eur existing onwind capacities apply) |
| `DP2_at10` | P2 | `mods.modify_nuts3_shapes: AT10DE5`, `clustering.administrative.AT: 2` |
| `DP3_no_national_policy` | P3 | all national AT policy constraints removed (table below) |

`CA_base` (AT10) is not reused as a DP run: if the temporal resolution of the DP runs is
coarsened, it would differ from `DP_base` in two choices.

### DP3: national AT policies removed

| Policy | Config key | In `DP3_no_national_policy` |
|---|---|---|
| Climate neutrality 2040 (national CO2 budget) | `solving.constraints.co2_budget_national.AT` | **removed entirely** (no AT budget constraint; DE budget unchanged) |
| EAG +27 TWh RE by 2030 | `solving.constraints.limits_volume_min.{solar,wind,hydro,biomass}.AT` | `0` (non-binding) |
| 1 GW electrolysis | `solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT` | `0` (non-binding) |
| 100 % RE electricity, annual balance, from 2030 | `mods.net_zero_electricity.enable` | `false` |

## Implementation items (before the first run)

1. **Onwind brownfield switch (P1).** `apply_onwind_brownfield` (`mods/network/onwind.py`, called
   in `modify_prenetwork`) has no `enable` toggle. Needed: a toggle that skips it, so the
   PyPSA-Eur onwind capacities stay. The file is AT-owned: either a small PyPSA-AT PR (toggle under
   `mods`, `enable: true` default, per the feature-toggle rule) or a CA hook. Recommendation:
   PyPSA-AT PR, since the toggle is generic.
2. **Removing the AT CO2 budget (P3).** `constraint_national_co2_budgets_ca`
   (`mods/carbon_accounting/budget.py`) loops over all countries in `co2_budget_national` and
   indexes `budget[investment_year]`; deep merge cannot delete the `AT` key. Needed: skip a country
   whose budget is `null` (CA-owned change; check the drift test against PyPSA-AT). Confirm that the
   PyPSA-AT budget (`mods/constraints/co2_budget.py`) is not added in parallel.
3. **Zero limits.** Check that `0` in `limits_volume_min` / `limits_capacity_min` adds no
   constraint or only a non-binding one (no infeasibility, no errors in `additional_functionality.py`).
4. Dry run: `pixi run snakemake -n --configfile config/config.carbon-accounting.yaml`.

## Execution

- Solve on the cluster; no full local runs.
- Sanity checks in `evals/` (understanding only): solved to optimality for all horizons; 35 AT buses
  in all runs but `DP2_at10`; no KLIEN caps and PyPSA-Eur onwind brownfield in AT in `DP1`; no AT
  CO2 budget and no EAG/electrolysis/net-zero-electricity constraints in `DP3`.
- Acceptance: each pair differs only in the keys listed above (diff of the resolved configs in
  `results/carbon-accounting/<scenario>/configs/`).

## Open (discussion later)

- **P1 scope:** other KLIEN uses stay active in `DP1` (hydro inflow targets, `klien_residual_plants`,
  KLIEN ror corridor). Switch them off as well?
- **P3, international embedding:** belongs to P3, but kept unchanged in `DP3` for now:
  `mods.tyndp_cross_border_flow_limits`, `mods.tyndp_lower_bounds` (NTC floors),
  `mods.block_russian_gas_imports`, `mods.tyndp_h2_import_scenario`.
- **P3, further national settings** kept unchanged for now: `mods.override_gas_storage_capacities`
  (fixed gas storage, policy?), `mods.threshold_year_for_gas_grid_expansion` (frozen gas grid),
  national capacity trajectories (`mods.trajectories`; Sec. 2.2 lists "national technology
  trajectories" under P3).
- **Results location:** where cluster results are stored and how they reach the evaluation
  notebooks (see `CLAUDE.local.md`).
- **Evaluation:** metrics and figures per principle (work in progress, later spec).
