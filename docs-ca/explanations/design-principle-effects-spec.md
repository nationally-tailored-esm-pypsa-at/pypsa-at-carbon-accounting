# Specification: Design-Principle Effect Runs (manuscript Sec. 3.2.1 / 4.1)

Status: **spec agreed 2026-11-22, implemented 2026-11-22, own overlay 2026-11-23 (runs pending).** Scope: model runs only. The evaluation
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

- Overlay: `config/config.design-principles.yaml` (full PyPSA-AT, Gurobi), separate from the
  reduced carbon accounting overlay `config/config.carbon-accounting.yaml`. Technology-based
  carbon accounting in all DP runs, so the DP results are independent of RQ3.
- Spatial resolution: **AT35DE5** (the PyPSA-AT default) for all DP runs except `DP2_at10`.
- Planning horizons: 2025, 2030, 2040, 2050 (from `config/config.at.yaml`).
- Temporal resolution: inherited (`clustering.temporal`). If AT35 does not solve in acceptable
  time, coarsen it **for all DP runs alike** in `config/config.design-principles.yaml` (never
  for one run of a pair only).
- Scenarios go into `config/scenarios.design-principles.yaml` and `run.name` of
  `config/config.design-principles.yaml`; results land in `results/design-principles/<scenario>/`.
- Scenario `mods` are deep-merged (`update_config`): keys can be overwritten, not deleted.

## Runs

| Scenario | Principle | Differs from `DP_base` by |
|---|---|---|
| `DP_base` | – | – (PyPSA-AT defaults, AT35DE5, Gurobi, technology-based accounting) |
| `DP1_no_national_data` | P1 | KLIEN potential caps off (`mods.klien_potential_limits.technologies: []`, PyPSA-Eur/ERA5 potentials apply) **and** KLIEN onwind brownfield off (`mods.carbon_accounting.onwind_brownfield.enable: false`, PyPSA-Eur existing onwind capacities apply) |
| `DP2_at10` | P2 | `mods.modify_nuts3_shapes: AT10DE5`, `clustering.administrative.AT: 2` |
| `DP3_no_national_policy` | P3 | all national AT policy constraints removed (table below) |

`CA_base` (AT10) is not reused as a DP run: if the temporal resolution of the DP runs is
coarsened, it would differ from `DP_base` in two choices. The DP runs have their own overlay,
so changes to the reduced carbon accounting setup never reach them.

### DP3: national AT policies removed

| Policy | Config key | In `DP3_no_national_policy` |
|---|---|---|
| Climate neutrality 2040 (national CO2 budget) | `solving.constraints.co2_budget_national.AT` | **removed entirely** (no AT budget constraint; DE budget unchanged) |
| EAG +27 TWh RE by 2030 | `solving.constraints.limits_volume_min.{solar,wind,hydro,biomass}.AT` | `0` (non-binding) |
| 1 GW electrolysis | `solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT` | `0` (non-binding) |
| 100 % RE electricity, annual balance, from 2030 | `mods.net_zero_electricity.enable` | `false` |

## Implementation items (done)

1. **Onwind brownfield switch (P1).** Decided: CA hook only, no PyPSA-AT PR. The switch
   `mods.carbon_accounting.onwind_brownfield.enable` (default `true`, in `config/config.ca.yaml`) is read by
   `onwind_brownfield_enabled` (`mods/carbon_accounting/design_principles.py`); a fenced hook in
   `modify_prenetwork` (`mods/network/common.py`) calls `apply_onwind_brownfield` only when it is
   on. The brownfield CSV is still built, so the DAG is the same in all runs.
2. **Removing the AT CO2 budget (P3).** `national_budgets` (`mods/carbon_accounting/budget.py`)
   drops countries whose budget is `null`; the CA budget, the claim pricing and the fair share use
   it. The PyPSA-AT budget is not added in parallel: `additional_functionality.py` calls either the
   CA or the AT budget. The drift test against PyPSA-AT is unchanged.
3. **Zero limits.** Non-binding: `limits_volume_min: 0` adds `production >= 0` (production
   variables are non-negative), `limits_capacity_min: 0` adds `p_nom >= -existing`.
4. **Dry run** with `--configfile config/config.design-principles.yaml` resolves 16 compose and
   16 solve jobs (4 scenarios × 4 horizons). `test/test_carbon_accounting/test_config.py` checks
   that each DP run differs from `DP_base` only in the keys of the run table.

## Local test run (2026-11-22)

The four DP runs went through the whole workflow locally at monthly resolution
(`clustering.temporal.averaging: 730h`) with HiGHS, all horizons solved. In the solved networks:
35 AT buses (10 in `DP2_at10`); `DP1` has the PyPSA-Eur potentials and onwind brownfield in AT;
`DP3` has no `co2_limit-AT`, no net-zero-electricity/green-gas/green-H2 constraints, and the zero
EAG and electrolysis limits have zero duals. Caveats for the production runs:

- HiGHS (IPX, no crossover) reports every solve as "Unknown" after unscaling (tolerance violation
  1e3–1e4); the DP runs need Gurobi, as in the overlay.
- `pixi.lock` pins gurobi 14.0.0; a Gurobi 13 license does not work with it.
- Each AT35 scenario needs about 8–10 GB of resources (`shared_resources.policy: false`).

## Execution

- Solve on the cluster; no full local runs.
- Sanity checks in `evals/` (understanding only): solved to optimality for all horizons; 35 AT buses
  in all runs but `DP2_at10`; no KLIEN caps and PyPSA-Eur onwind brownfield in AT in `DP1`; no AT
  CO2 budget and no EAG/electrolysis/net-zero-electricity constraints in `DP3`.
- Acceptance: each pair differs only in the keys listed above (diff of the resolved configs in
  `results/design-principles/<scenario>/configs/`).

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
