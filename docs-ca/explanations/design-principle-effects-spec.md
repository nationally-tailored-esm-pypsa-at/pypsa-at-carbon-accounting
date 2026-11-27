# Specification: Design-Principle Effect Runs (manuscript Sec. 3.2.1 / 4.1)

Status: **spec agreed 2026-11-22, implemented 2026-11-22, own overlay 2026-11-23, DP3 widened to all of P3 2026-11-23 (runs pending).** Scope: model runs only. The evaluation
(metrics, figures) is work in progress and not part of this spec.

## Goal

Provide the runs for RQ2: *how does implementing the design principles of a nationally tailored
ESM change model outcomes relative to an over-regional model?* Manuscript Sec. 2.2 defines three
principles. Validation is cross-cutting and **not** part of these runs.

| ID | Principle (Sec. 2.2) | Switched in this study |
|---|---|---|
| P1 | Integration of country-specific data | KLIEN renewable potentials and KLIEN existing onshore-wind capacities for AT |
| P2 | Adequate spatial (and temporal) granularity | AT at NUTS 3 (AT35) vs NUTS 2 (AT10) |
| P3 | Country-centred policy representation and international embedding | national AT policy targets **and** the international embedding and national settings (TYNDP grid, gas import routes, gas storage, capacity trajectories) |

Design rule (Sec. 3.2): **each comparison differs in one choice only.** Every principle gets a
pair: `DP_base` (full PyPSA-AT) vs a run without the principle. Exception P3: the KLIEN scenario
potentials (climate scenario, year, ambition) hold policy assumptions and would mask the policy
effect, so the P3 pair is `DP3_with_national_policy` vs `DP3_no_national_policy`, both on the KLIEN
technical potentials (one config switch, `use_technical_potentials`). `DP3_with_national_policy` vs
`DP_base` shows the effect of that basis.

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
| `DP3_with_national_policy` | P3 | basis of the P3 pair: `mods.klien_potential_limits.use_technical_potentials: true` (KLIEN technical potentials instead of the scenario potentials; the caps stay on, KLIEN onwind brownfield unchanged) |
| `DP3_no_national_policy` | P3 | as `DP3_with_national_policy`, **and** national policy targets, international embedding and national settings removed (tables below). Compared with `DP3_with_national_policy`, not with `DP_base` |

`CA_base` (AT10) is not reused as a DP run: if the temporal resolution of the DP runs is
coarsened, it would differ from `DP_base` in two choices. The DP runs have their own overlay,
so changes to the reduced carbon accounting setup never reach them.

### DP3: country-centred policy and international embedding removed

Review 2026-11-23: a DP3 with the national targets only tests "national targets", not
"country-centred policy and international embedding". Sec. 2.2 also puts national technology
trajectories and physically plausible import/export under P3, and Sec. 3.1.2 the fixed gas
storage and the TYNDP flows. Decided: `DP3_no_national_policy` removes all of P3 in one run.
The target and the embedding effects are therefore not separated.

#### National policy targets

| Policy | Config key | In `DP3_no_national_policy` |
|---|---|---|
| Climate neutrality 2040 (national CO2 budget) | `solving.constraints.co2_budget_national.AT` | **removed entirely** (no AT budget constraint; DE budget unchanged) |
| EAG +27 TWh RE by 2030 | `solving.constraints.limits_volume_min.{solar,wind,hydro,biomass}.AT` | `0` (non-binding) |
| 1 GW electrolysis | `solving.constraints.limits_capacity_min.Link.H2 Electrolysis.AT` | `0` (non-binding) |
| 100 % RE electricity, annual balance, from 2030 | `mods.net_zero_electricity.enable` | `false` |

### DP3: cross-border flow and infrastructure constraints removed

`DP3_no_national_policy` also drops everything that restricts flows or infrastructure across
the Austrian border (international embedding, P3). The pair `DP3_with_national_policy` keeps them.

| Element | Where | In `DP3_no_national_policy` |
|---|---|---|
| TYNDP NTC net-flow limits per corridor (AC lines and DC links, per snapshot; 2030 and 2040) | `mods.tyndp_cross_border_flow_limits.enable`, `constraint_ntc_flow_limits` | `false` |
| TYNDP NTC capacity floors (`s_nom_min`, `p_nom_min`; 2030 and 2040) | `mods.tyndp_lower_bounds.enable`, `.years`, `apply_tyndp_transmission_lower_bounds` | `false`, `years: []` (the function checks only the years and would read its input, which the rule drops when the switch is off) |
| DE net electricity import limit (TWh/a; a DE limit, not AT) | `solving.constraints.limits_volume_max.electricity_import.DE` | `500` in every year (non-binding; the constraint stays in the network, because PyPSA-DE loops over the countries and a `null` would fail) |
| TYNDP H2 import generators (fixed `p_nom`, `e_sum_max`) | `sector.imports.carriers_tyndp` | `[]`. The upstream price-based import options (`sector.imports.enable`, e.g. H2 at 74 EUR/MWh) stay |
| Frozen gas grid: AGGM capacities fixed, no new methane pipelines, H2 retrofit only within the gas capacity, reverse legs restored | `mods.threshold_year_for_gas_grid_expansion`, `fix_gas_grid_capacity`, `restore_asymmetric_pipeline_capacities` | `2020` (before the first horizon: both functions are skipped in every horizon) |

Gas grid in detail. In the PyPSA-AT default (`2040`) all `gas pipeline new` candidates are
non-extendable; existing pipelines are fixed before the retrofit start year (2030, from
`first_technology_occurrence`); afterwards only pipelines with an H2 retrofit candidate stay
extendable up to their current capacity, so that the upstream retrofit constraint
(`gas + H2 retrofitted / 0.6 = p_nom`) can only move capacity from gas to H2; one-way and
asymmetric AT corridors keep their AGGM reverse capacity up to 2030. With `2020` the model
falls back to the PyPSA-Eur logic: new methane pipelines and the existing ones are
extendable everywhere, the retrofit candidates exist from 2030 (`H2 pipeline retrofitted: 2030`
is unchanged) with `p_nom_max = 0.6 × gas capacity`, and the reverse legs regain the forward capacity
at no cost (the "known limitation" noted in `gas.py`). The AGGM brownfield capacities
themselves stay (`modify_brownfield_gas_network_AT` is on). The switch also frees domestic AT
pipelines, not only the border corridors; a corridor-specific switch would need a CA hook in
`mods/network/gas.py`.

Exception in 2030 (found 2026-11-27, when the first DP3-based runs composed 2030): up to 2030
PyPSA-DE keeps the DE-internal retrofit candidates non-extendable (Kernnetz assumption,
`scripts/pypsa-de/modify_prenetwork.py`). Up to the threshold year, `fix_gas_grid_capacity`
fixes the gas pipelines without an extendable candidate. After it, it does nothing, so with `2020`
about 10 DE-internal pipelines stayed extendable without a candidate in 2030, and
`check_retrofit_pairing` stopped the compose. The CA hook `fix_unpaired_gas_pipelines`
(`mods/carbon_accounting/design_principles.py`) fixes these pipelines after the threshold year,
as `fix_gas_grid_capacity` does before it. In 2040 and 2050 every gas pipeline has a candidate,
and in the PyPSA-AT default (`2040`) the hook does nothing.

Not changed (kept in `DP3_no_national_policy`): `mods.block_russian_gas_imports`,
`mods.unravel_natural_gas_imports`, `mods.PEMMDB_trajectories`, `mods.trajectories`, the DE
`limits_volume_max.h2_import` and `h2_derivate_import`, the OSM cross-border line filter
(`drop_cross_border_lines_lv`), and the upstream extension limits `lines.s_nom_max_extension` and
`links.p_nom_max_extension`.

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
5. **Widened DP3 (2026-11-23).** Scenario keys of the embedding table added; the config test lists
   them and checks that the H2 import scenario is kept. The gas grid freeze was switched off at
   first (threshold `2024`) and reverted after the test run on 2026-11-23 (see the notes above).
   The local test run below predates this change.

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
  CO2 budget, no EAG/electrolysis/net-zero-electricity constraints, no `tyndp_ntc_flow_*`
  constraints, no Russian gas block and no generic trajectory constraints in `DP3`.
- Acceptance: each pair differs only in the keys listed above (diff of the resolved configs in
  `results/design-principles/<scenario>/configs/`).

## Open (discussion later)

- **P1 scope:** other KLIEN uses stay active in `DP1` (hydro inflow targets, `klien_residual_plants`,
  KLIEN ror corridor). Switch them off as well?
- **P3, international embedding:** the NTC limits and floors, the TYNDP H2 imports, the DE
  electricity import limit and the frozen gas grid are removed in `DP3_no_national_policy`. Kept
  for now: `mods.block_russian_gas_imports`, `mods.PEMMDB_trajectories`, the DE H2 import and
  H2 derivate import limits.
- **P3, further national settings** kept unchanged for now: `mods.override_gas_storage_capacities`
  (fixed gas storage, policy?), national capacity trajectories (`mods.trajectories`; Sec. 2.2 lists "national technology
  trajectories" under P3).
- **Results location:** where cluster results are stored and how they reach the evaluation
  notebooks (see `CLAUDE.local.md`).
- **Evaluation:** metrics and figures per principle (work in progress, later spec).
