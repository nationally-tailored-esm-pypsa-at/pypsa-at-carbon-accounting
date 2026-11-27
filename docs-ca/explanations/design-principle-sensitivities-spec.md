# Specification: Design-Principle Sensitivity Runs (Issue #19)

Status: **spec agreed 2026-11-27 (AI-assisted), not implemented.** Scope: the sensitivity runs
and how the existing DP evaluation compares them. Builds on
[design-principle-effects-spec.md](design-principle-effects-spec.md) (runs) and
[design-principle-eval-spec.md](design-principle-eval-spec.md) (evaluation).

## Goal

Test whether the DP effects hold when key assumptions change: claim shares, AT CO2
emissions against the national budget, cross-border flows and AT cost. Each sensitivity
answers one of these questions:

| Question | Sensitivity |
|---|---|
| Does the P1 effect depend on which KLIEN potential is the national data? | **S1** KLIEN ambition / technical potential |
| Which part of the P3 effect comes from the national targets and which from the international embedding? | **S2** DP3 split |
| Once the TYNDP H2 imports are gone, how much does the P3 effect depend on the assumed H2 import price? | **S3** H2 import price |
| Once the NTC limits and floors are gone, how much does the P3 effect depend on the generic extension limits? | **S4** transmission extension limits |
| Is the P3 effect a loss of climate ambition, or does it come from the national policy itself? | **S5** general emission cap set to the AT path |

Scope: the design-principle family only. Sensitivities of the reduced carbon accounting runs
(`CA_*`) are not part of this spec, and the acceptance criteria of #19 need to be updated to
say so.

## Design rules

- **One-at-a-time:** each sensitivity run differs from its reference run in **one choice**,
  as the DP spec requires. There is no factorial grid.
- **Reuse:** a sensitivity point that an existing DP run already covers is not solved again.
- **Common setup** as in the DP spec: AT35DE5, horizons 2025/2030/2040/2050, inherited
  temporal resolution, Gurobi, technology-based accounting. The horizons are **not** a
  sensitivity.
- **Naming:** `DP<principle>S_<what>`. `_principle` in `evals/carbon_accounting/design_principles.py`
  (regex `DP(\d+)`) then maps each run to its principle without code changes.

## Runs

10 new runs, × 4 horizons = 40 solves.

### S1: KLIEN potential (P1), decided in #19

DP1 removes the KLIEN caps, so the KLIEN potential only changes the **reference** of the P1
pair. Each variant is `DP_base` with another potential, and the P1 effect per variant is
*variant − `DP1_no_national_data`*. `year` (2040) and `climate_scenario` (`wocc`) stay at the
`DP_base` values.

| Point | Run | Differs from `DP_base` by |
|---|---|---|
| low | `DP1S_klien_low` (new) | `mods.klien_potential_limits.ambition: low` |
| medium | `DP_base` (exists) | – |
| high | `DP1S_klien_high` (new) | `mods.klien_potential_limits.ambition: high` |
| technical | `DP3_with_national_policy` (exists) | `mods.klien_potential_limits.use_technical_potentials: true` |

> [!IMPORTANT]
> `ambition` also sets the **KLIEN run-of-river corridor** (`build_klien_hydro_trajectory_at`,
> `rules/pypsa-at/build_electricity.smk`). Decided 2026-11-27: the corridor follows the ambition.
> S1 is therefore a sensitivity of *the KLIEN ambition* (PV/wind caps **and** ror), not of the
> PV/wind potential alone. Two consequences:
> - `DP1_no_national_data` keeps the `medium` ror corridor. For low and high, *variant − DP1*
>   therefore also contains a ror difference. The evaluation reports the AT ror capacity next
>   to the P1 effect, so that this part is visible.
> - The technical point (`use_technical_potentials`) does not change the ror corridor (it stays
>   at `medium`), so this point does not lie on the same axis as low and high.
>
> The KLIEN hydro pathway has no `wocc` variant and falls back to `mocc` (as in `DP_base`).

### S2: DP3 split into targets and embedding (P3)

`DP3_no_national_policy` removes both tables of the DP spec in one step. The split removes one
table each. The reference is `DP3_with_national_policy`.

| Run | Removes (tables in the DP spec) |
|---|---|
| `DP3S_targets_only` | *National policy targets*: AT CO2 budget `null`, EAG `limits_volume_min.*.AT.2030: 0`, electrolysis `limits_capacity_min…AT: 0`, `net_zero_electricity.enable: false` |
| `DP3S_embedding_only` | *Cross-border flow and infrastructure constraints*: `tyndp_cross_border_flow_limits.enable: false`, `tyndp_lower_bounds.enable: false`, DE `electricity_import: 500`, `carriers_tyndp: []`, `threshold_year_for_gas_grid_expansion: 2020` |

Both runs use the KLIEN technical potentials. The keys of the two runs together are exactly
the keys of `DP3_no_national_policy`, and a config test checks this. Evaluation: the target
effect, the embedding effect, the full P3 effect, and the **interaction**
*P3 − (targets + embedding)* for each headline metric.

### S3: H2 import price (P3)

The base is `DP3_no_national_policy`. Without the TYNDP H2 generators, the upstream
price-based import (`sector.imports.price.H2`, 74 EUR/MWh) decides how much H2 AT imports.
The range is ±50 %, and only H2 changes. NH3, methanol, gas and oil keep their prices, so the
derivative imports may take over part of the change (this is reported, not prevented).

| Run | `sector.imports.price.H2` |
|---|---|
| `DP3S_h2_price_low` | 37 EUR/MWh |
| `DP3_no_national_policy` (exists) | 74 EUR/MWh |
| `DP3S_h2_price_high` | 111 EUR/MWh |

`sector.imports.price` is a dict, so the scenario sets only `H2` and the deep merge keeps
the other carriers.

### S4: transmission extension limits (P3)

The base is `DP3_no_national_policy`. Without the NTC limits and floors, the upstream limits
on extension per line/link become binding for cross-border expansion. The range is half and
double.

| Run | `lines.s_nom_max_extension` | `links.p_nom_max_extension` |
|---|---|---|
| `DP3S_extension_half` | 10000 MW | 15000 MW |
| `DP3_no_national_policy` (exists) | 20000 MW | 30000 MW |
| `DP3S_extension_double` | 40000 MW | 60000 MW |

> [!NOTE]
> The limits apply to **every** AC line and DC link in the model (`prepare_network.py`), not
> only to AT border corridors. S4 therefore also changes expansion inside DE and AT. A value of
> `0` or `inf` disables the limit, so neither is used as a sensitivity point.

### S5: general emission cap set to the AT path (P3)

`co2_budget.upper` (the EU cap, relative to 1990) gets the reduction path of the AT national
budget, so that removing the AT budget does not loosen the climate ambition. The DE national
budget stays unchanged.

| Horizon | EU cap in `config.de.yaml` | AT path (`co2_budget_national.AT`) = new EU cap |
|---|---|---|
| 2025 | 0.627 | 0.52 |
| 2030 | 0.467 | 0.34 |
| 2035 | 0.285 | 0.21 |
| 2040 | 0.142 | 0.00 |
| 2045 | 0.030 | 0.00 |
| 2050 | −0.024 | −0.05 |

| Run | Base | AT budget | References |
|---|---|---|---|
| `DP3S_eu_cap_at_path_no_policy` | `DP3_no_national_policy` + AT path as EU cap | removed | `DP3_no_national_policy` (effect of the cap); `DP3_with_national_policy` (P3 effect at the same ambition) |
| `DP3S_eu_cap_at_path_with_policy` | `DP3_with_national_policy` + AT path as EU cap | kept | `DP3_with_national_policy` |

Comparing the two S5 runs gives the P3 effect when the general cap has the AT path.

> [!WARNING]
> - **Basis:** both paths are relative to 1990, but on different bases. The AT budget uses AT
>   1990 CO2 (`co2_total_totals`, `mods/carbon_accounting/budget.py`). The EU cap is a CO2 cap
>   derived from the EU GHG goals including non-CO2 and LULUCF (comment in `config.de.yaml`).
>   The same numbers are therefore not the same ambition in meaning.
> - **Feasibility:** the EU cap becomes 0.00 already in 2040 (10 years earlier), which is a
>   much tighter EU system. Before the cluster runs, a monthly HiGHS test run (as in the DP
>   spec) checks that the problem is feasible and that the CO2 price is plausible.

## Config and code

| Item | Where |
|---|---|
| 10 scenarios | `config/scenarios.design-principles.yaml` (scenario `mods` are deep-merged; keys can be overwritten, not deleted) |
| Run list of the sensitivities | new overlay `config/config.design-principles-sensitivities.yaml`, which only sets `run.name` to the 10 runs (and the reference runs, if a full run is wanted). Usage: `--configfile config/config.design-principles.yaml config/config.design-principles-sensitivities.yaml`. `config/config.design-principles.yaml` keeps its 5 DP runs. Same `run.prefix`, so the results sit next to the reference runs in `results/design-principles/` |
| Fork guard | add the new overlay to `CA_OWNED` in `test/test_carbon_accounting/test_fork_guard.py` and to the path table in `CLAUDE.CA.md` |
| Expected keys and references | `DP_DIFFERENCES` and `DP_REFERENCES` in `evals/carbon_accounting/design_principles.py`: one entry per new run. Reference `DP_base` for S1, `DP3_with_national_policy` for S2 and S5, `DP3_no_national_policy` for S3, S4 and `DP3S_eu_cap_at_path_no_policy` |
| Config tests | `test/test_carbon_accounting/test_config.py`: each sensitivity differs from its reference only in the expected keys (existing parametrised test); S2 keys together = DP3 keys; S3 sets only `price.H2`; S5 cap equals `co2_budget_national.AT` for each horizon |
| No new hooks, no new wildcards | everything is config; S1 changes the build of the ror corridor, but the DAG is the same |

## Evaluation

The DP notebook (`evals/carbon_accounting/notebooks/design_principles.py`) handles the
sensitivities through its existing reference mapping. In addition, there is one
**sensitivity step** per family. For each headline metric, it shows the effect of the
principle at each sensitivity point next to the base effect:

| Family | Effect shown per point |
|---|---|
| S1 | variant − `DP1_no_national_data` for capacity, production, AT cost and AT CO2 (section A metrics), plus the AT ror capacity |
| S2 | target, embedding and full P3 effect, and the interaction term |
| S3, S4 | `DP3S_* − DP3_with_national_policy` next to `DP3_no − DP3_with`; also AT net H2 imports (S3) and the added cross-border capacity (S4) |
| S5 | AT CO2 against the AT budget, EU `CO2Limit-upper` mu, AT cost |

Headline metrics (#19): AT CO2 emissions against the national budget, net cross-border flows
per carrier, AT cost (`country_cost`), and claim shares (technology-based accounting in all
DP runs). The notebook shows the effects side by side and sets no robustness threshold. The
reading is left to the analysis. Checks: the config diff against the reference (existing),
solved for all horizons.

## Acceptance

- All 10 runs go through `all_at` on the cluster. The only failures allowed are the known
  failures of CA runs (`CLAUDE.CA.md`).
- The config tests and the fork guard pass. The dry run with both overlays resolves 40
  compose and 40 solve jobs (plus the reference runs, if they are listed).
- The notebook shows each sensitivity against its reference (table above).
- This spec documents the parameters, ranges and rationale.

## Open points

- **S1 and ror:** with the ror corridor following the ambition, the P1 effect at low/high
  contains a hydro part that DP1 does not have. If this part is large, you could add
  `DP1_no_national_data` at low/high (two more runs) or a CA switch that decouples ror.
- **S5 feasibility:** if the test run is infeasible or extreme, should the AT path only be
  applied up to 2040 (and the EU path after that)?
- **Compute:** 40 solves at AT35 with Gurobi (8–10 GB of resources per scenario). If this does
  not fit, coarsen the temporal resolution **for all DP runs and sensitivities alike**, never
  for one sensitivity only.
