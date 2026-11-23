# Specification: Design-Principle Evaluation Notebook (manuscript Sec. 4.1)

Status: **spec agreed and implemented 2026-11-23** in `evals/carbon_accounting/design_principles.py` and
`evals/carbon_accounting/notebooks/design_principles.py` (AI-assisted). Developed on the local test runs. Builds on the runs of
[design-principle-effects-spec.md](design-principle-effects-spec.md).

## Goal

Answer RQ2 per principle: compare each DP run with `DP_base` (full PyPSA-AT), focused on AT.
Development runs against the local test runs (`results/carbon-accounting-test/`, monthly,
HiGHS, solve status "Unknown"). Their numbers are **not** interpreted. The production runs
(`results/design-principles/`, Gurobi) replace them by switching the result root.

> [!NOTE]
> The objective is the EU system cost. In the test runs the DP runs differ from `DP_base` by
> < 0.5 % of it, so the EU objective says little about AT. Cost is measured in AT.

## Location and structure

Same pattern as [carbon-accounting-eval-spec.md](carbon-accounting-eval-spec.md):

- Module: `evals/carbon_accounting/design_principles.py` (all computations). Reuses
  `find_scenarios`, `load_networks`, `Check`, `country_cost`, `system_cost`,
  `national_co2_categories` and `national_budget` from `accounting.py`.
- Notebook: `evals/carbon_accounting/notebooks/design_principles.py` (marimo, only UI, caching,
  plots).
- Tests: `test/test_carbon_accounting/test_evals/test_design_principles.py` (toy networks).
- Functions take `scenario -> horizon -> network` and return frames with a `scenario` level.
  Every Δ is measured against the reference (`DP_base`).

## Notebook flow

Numbered steps with status badges (✓ / ⚠ / ✗) as in the CA notebook; a ✗ calls `mo.stop`.
The notebook answers one question per principle, in order.

| Step | Content |
|---|---|
| 0 Setup | Result root (default `results/design-principles`, test runs selectable), scenarios (default: all), reference (default `DP_base`), country (default `AT`). Table scenario × horizon of the networks found. |
| 1 Checks | See *Checks*. |
| A Data (P1) | `DP1` vs `DP_base`: wind and solar potentials and production in AT; does the potential make a difference, is the cap binding? |
| B Resolution (P2) | `DP2` vs `DP_base`: capacities per NUTS 2 region (AT35 summed to NUTS 2). |
| B ii Transmission (P2) | Total (gross, not net) transmission inside AT. |
| C Policy (P3) | `DP3` vs `DP_base`: are the policy goals binding, what changes without them, which other constraints bind the same elements then? |
| 4 Binding constraints | Duals of all global constraints and binding potential caps (general overview). |
| 5 Cost in AT | `country_cost` per scenario and horizon, split by component group, Δ vs reference. |

## (1) Checks

| Check | Rule |
|---|---|
| Solved | as in the CA notebook: every horizon has a `solved_<horizon>.nc` (`find_scenarios`); ✗ if horizons differ between scenarios. No solver status check (production runs use Gurobi). |
| Spatial | 35 AT AC buses, 10 in `DP2_at10`. |
| Config diff | flattened `n.meta` vs the reference; the differing keys must equal the expected keys of the run table in the runs spec (`run`, `wildcards`, `description` ignored). |
| P3 constraints | `DP3`: no `co2_limit-AT`, `net-zero-electricity-production-AT`, `green-gas-production-AT`, `green-h2-production-AT`; EAG and electrolysis limits with constant 0. |

The expected keys per run sit in one mapping in the module, so new DP runs need one entry.

## (A) Data: do the KLIEN potentials make a difference? (P1)

Carrier groups: **onshore wind** (`onwind`), **ground PV** (`solar` + `solar-hsat`, one land
potential, see `mods/network/potentials.py`), **rooftop PV** (`solar rooftop`). AT buses,
`DP1_no_national_data` vs `DP_base`, all horizons.

| Metric | Definition |
|---|---|
| Potential (GW) | per bus and group: `p_nom_max` of the extendable generator of the horizon + `p_nom` of the existing (non-extendable) generators of the group. `p_nom_max` is the remaining headroom after the brownfield deduction. Ground PV: `p_nom_max` of `solar` (shared with `solar-hsat`). |
| Capacity (GW) | `Σ p_nom_opt` (all vintages) |
| Production (TWh) | generation weighted with `snapshot_weightings.generators`; plus curtailment (available − dispatched) |
| Utilisation | capacity / potential, AT total |
| Binding buses | buses with capacity ≥ 0.999 · potential, count and share of the AT capacity there |
| Forced buses | buses where `p_nom_min ≥ 0.999 · p_nom_max` (trajectory floor fills the potential); not counted as binding |
| Capacity factor | production / (capacity · 8760 h), AT; shows the effect of the brownfield locations |

PyPSA does not store duals of `p_nom_max`, so *binding* means *no slack left*. Curtailment is
only meaningful at hourly resolution (≈ 0 in the monthly test runs).

Figures: capacity vs potential (bars with potential marker), production, scenario × horizon.
Answer: Δ capacity and Δ production `DP1 − DP_base`; binding buses in each run.

## (B) Resolution: capacities per NUTS 2 region (P2)

- NUTS 2 region = first four characters of the bus name (`AT111` → `AT11`, `AT333` → `AT33`).
- `DP_base` capacities summed per NUTS 2 region vs `DP2_at10` per region, for **every** AT NUTS 2
  region, all horizons.
- Technologies: generators by carrier group (onwind, ground PV, rooftop PV, ror, hydro), links by
  output capacity (electrolysis, gas power, heat pumps, CHP), batteries (store `e_nom_opt`).
- Table region × technology × horizon with `DP_base`, `DP2`, Δ and Δ %; figure: grouped bars per
  region.
- Two numbers per technology and horizon separate the effects: **AT total Δ** (resolution
  changes how much is built) and **regional shift** `Σ_regions |Δ| / AT total of DP_base`
  (resolution changes where it is built).
- Region of a bus: `n.buses.location` (sector buses such as `AT111 urban central heat` sit at
  `AT111`); heat pumps by electric input (`p_nom_opt`), other links by output capacity.

## (B ii) Total transmission inside AT (P2)

- Branches with both buses in AT (`n.buses.location`): AC lines, DC links, H2 pipelines (incl.
  retrofitted), gas pipelines (incl. new). All vintages of a branch count.
- **Gross** transmission: no netting of directions, snapshots or branches.
  - `TWh = Σ_branches Σ_t |p0| · w_t`. A flow counts once per branch it passes, so a finer
    network shows more TWh for the same transport (AT35 has 47 intra-AT AC lines, AT10 15).
  - **Transport work** `TWh·km = Σ_branches length · Σ_t |p0| · w_t` (main metric): does not
    depend on how a route is split into branches.
- Two views: (i) all intra-AT branches, (ii) only branches crossing NUTS 2 borders (the
  branches AT10 also has).
- Also: added capacity (`s_nom_opt − s_nom`, `p_nom_opt − p_nom`; negative for gas pipelines
  retrofitted to H2), capacity-weighted mean loading, share of time at the limit
  (`|p0| ≥ 0.99 · s_max_pu · s_nom_opt`). Loading and time at the limit need hourly
  resolution; monthly averages hide congestion.

## (C) Policy: are the policy goals binding, and what replaces them? (P3)

1. **Binding in `DP_base`:** `constant`, achieved value and `mu` of each AT policy constraint
   per horizon: `co2_limit-AT`, `production_limit_lower-{solar,wind,hydro,biomass}-AT`,
   `capacity_minimum-AT-Link-H2-Electrolysis`, `net-zero-electricity-production-AT`,
   `green-gas-production-AT`, `green-h2-production-AT`. Binding: `|mu| > 1e-3`.
2. **Without them (`DP3`):** Δ of the elements each constraint acts on, `DP3 − DP_base`: AT CO2
   emissions (vs the budget of `DP_base`), RE production per group (vs the EAG targets),
   electrolysis capacity (vs 1 GW), AT electricity balance (production − consumption), green
   gas and green H2 production, AT net imports of electricity, H2, methane, liquids.
3. **What binds the same elements then:** each policy constraint is mapped to its elements
   (e.g. EAG wind → AT `onwind` generators, electrolysis → AT `H2 Electrolysis` links,
   `co2_limit-AT` → AT emitters). For these elements, in both runs: binding potential caps
   (A), binding `p_nom_min`/`p_nom_max`, binding TYNDP and trajectory constraints with AT
   elements, and the EU `CO2Limit-upper` (its `mu` vs the AT CO2 price of `DP_base`). Table
   policy constraint → binding constraints in `DP_base` and `DP3`.
4. **Achieved values** (LHS of each policy constraint) need the constraint expressions (e.g.
   hydro inflow weighted by turbine efficiency, the net-zero-electricity balance). Simple
   statistics only approximate them (hydro 2030: 48.6 TWh vs binding target 47 TWh). See open
   points.

## (4) Binding constraints

- Table `GlobalConstraint` × scenario × horizon: `constant`, `mu`, binding flag
  (`|mu| > 1e-3`). The TYNDP constraints are summed into one row per type (count binding).
- Grouped as AT policy (`co2_limit-AT`, `production_limit_lower-*-AT`,
  `capacity_minimum-AT-*`, `net-zero-*`, `green-*`), EU/DE (`CO2Limit-upper`, `*-DE`),
  other.
- Potential caps: count of binding `p_nom_max` per carrier from (3).
- Heatmap: `mu` of the AT constraints, scenario × horizon.

## (5) Cost in AT

`country_cost` (CAPEX + OPEX of components in AT, as in the CA notebook) by component group,
Δ vs reference; EU system cost Δ in the headline only.

## Open points

- C4: exact LHS of the AT policy constraints. Options: re-evaluate the expressions of
  `mods/constraints/{production,eag}.py` on the solved network, or store the LHS value in the
  network (`GlobalConstraint` column) when solving (AT-owned code, needs a hook).

- B ii: gas pipeline lengths differ between AT35 and AT10 (TWh·km ratio ≈ 2–4 vs ≈ 1.2–1.7 for AC). Check the gas network clustering before interpreting.

- A, 2025: without KLIEN data the base year is unconstrained above the trajectory floor
  (`DP1` builds 21 GW ground PV in 2025). Show 2025 separately or exclude it?

- Maps of regional capacities: later, if the manuscript needs them (bars first).
- Summary metrics for the manuscript table: which numbers per question?
- C3: which linopy constraints without a `GlobalConstraint` (land use, TYNDP flow limits) bind AT elements? Their duals are not stored.
