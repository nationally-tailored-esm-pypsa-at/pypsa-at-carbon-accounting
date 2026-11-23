# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Design-principle evaluation notebook (marimo).

Compares the design-principle runs with ``DP_base`` for one country and answers
one question per principle. All computations live in
``evals/carbon_accounting/design_principles.py``; this file only does UI,
caching and plotting. Run it from the repository root with

    pixi run marimo edit evals/carbon_accounting/notebooks/design_principles.py

Specification: ``docs-ca/explanations/design-principle-eval-spec.md``.
"""

import marimo

__generated_with = "0.25.0"
app = marimo.App(width="full", app_title="Design-principle evaluation")


@app.cell
def _():
    import sys
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    REPO = Path(__file__).resolve().parents[3]
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    from evals.carbon_accounting import accounting as ca
    from evals.carbon_accounting import design_principles as dp

    return REPO, ca, dp, go, mo, pd, px


@app.cell
def _(mo):
    # categorical slots in fixed order; a scenario keeps its colour across selections
    PALETTE = [
        "#2a78d6",
        "#eb6834",
        "#1baf7a",
        "#eda100",
        "#e87ba4",
        "#008300",
        "#6250d6",
        "#e34948",
    ]
    ICONS = {"ok": "✓", "warn": "⚠", "fail": "✗"}
    KINDS = {"ok": "success", "warn": "warn", "fail": "danger"}

    def badge(check) -> mo.Html:
        """Return a callout with the status icon, name and message of a check."""
        text = mo.md(f"**{ICONS[check.status]} {check.name}** — {check.message}")
        return mo.callout(text, kind=KINDS[check.status])

    def step_status(checks) -> str:
        """Return the worst status of several checks."""
        statuses = {c.status for c in checks}
        return next((s for s in ("fail", "warn") if s in statuses), "ok")

    def layout(fig, title: str, yaxis: str):
        fig.update_layout(
            title=title,
            template="plotly_white",
            bargap=0.3,
            legend=dict(orientation="h", y=-0.25),
            hovermode="closest",
            margin=dict(t=60, b=40),
        )
        fig.update_yaxes(title_text=yaxis, zeroline=True, zerolinecolor="#c3c2b7")
        return fig

    def table(frame, digits: int = 3, label: str = ""):
        """Return a rounded, flat marimo table."""
        return mo.ui.table(
            frame.round(digits).reset_index(), selection=None, label=label
        )

    return ICONS, PALETTE, badge, layout, step_status, table


@app.cell
def _(mo):
    mo.md(r"""
    # Design-principle evaluation

    Each DP run differs from the **reference** (`DP_base`, full PyPSA-AT) in one design
    principle (manuscript Sec. 2.2). The notebook answers one question per principle:
    **A** data (P1), **B** resolution (P2), **C** policy (P3). Specification:
    `docs-ca/explanations/design-principle-eval-spec.md`.
    """)
    return


@app.cell
def _(REPO, mo):
    _production = REPO / "results" / "design-principles"
    _default = (
        _production
        if _production.is_dir()
        else REPO / "results" / "carbon-accounting-test"
    )
    root_input = mo.ui.text(value=str(_default), label="Result root", full_width=True)
    root_input
    return (root_input,)


@app.cell
def _(PALETTE, ca, dp, mo, root_input):
    files = ca.find_scenarios(root_input.value)
    mo.stop(
        not files,
        mo.callout(
            mo.md(f"✗ No solved networks found in `{root_input.value}`."), kind="danger"
        ),
    )
    colours = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(files)}
    paths = {s: str(next(iter(h.values())).parents[1]) for s, h in files.items()}
    scenario_select = mo.ui.multiselect(
        options=list(files), value=list(files), label="Scenarios"
    )
    reference_select = mo.ui.dropdown(
        options=list(files),
        value=dp.REFERENCE if dp.REFERENCE in files else next(iter(files)),
        label="Reference",
    )
    country_select = mo.ui.dropdown(options=["AT"], value="AT", label="Country")
    ignore_checks = mo.ui.checkbox(label="Continue despite failed checks")
    return (
        colours,
        country_select,
        files,
        ignore_checks,
        paths,
        reference_select,
        scenario_select,
    )


@app.cell
def _(ca, dp, mo, paths):
    @mo.cache
    def load(path: str) -> dict:
        """Load the solved networks of one scenario, once."""
        return ca.load_networks(path)

    def networks(scenarios) -> dict:
        return {s: load(paths[s]) for s in scenarios}

    @mo.cache
    def per_scenario(name: str, scenario: str, country: str):
        """Apply a per-run function of ``dp`` to one scenario, once."""
        return getattr(dp, name)(networks([scenario]), country)

    @mo.cache
    def per_pair(name: str, reference: str, other: str, country: str, *args):
        """Apply a function of ``dp`` to the reference and one run, once."""
        return getattr(dp, name)(networks([reference, other]), country, *args)

    return load, networks, per_pair, per_scenario


@app.cell(expand_output=True)
def _(
    country_select,
    files,
    mo,
    pd,
    reference_select,
    scenario_select,
    table,
):
    _info = pd.DataFrame(
        [(s, h, str(p)) for s, hs in files.items() for h, p in hs.items()],
        columns=["scenario", "horizon", "file"],
    ).set_index(["scenario", "horizon"])
    selected = list(dict.fromkeys([reference_select.value, *scenario_select.value]))
    reference = reference_select.value
    country = country_select.value
    others = [s for s in selected if s != reference]
    mo.vstack(
        [
            mo.md("## 0 Setup"),
            mo.hstack(
                [scenario_select, reference_select, country_select],
                justify="start",
                gap=2,
            ),
            table(_info.loc[selected], label="Networks per scenario and horizon"),
        ]
    )
    return country, others, reference, selected


@app.cell(expand_output=True)
def _(
    ICONS,
    badge,
    country,
    dp,
    files,
    ignore_checks,
    mo,
    networks,
    reference,
    selected,
    step_status,
):
    _checks = dp.checks(
        {s: files[s] for s in selected}, networks(selected), reference, country
    )
    _status = step_status(_checks)
    mo.output.replace(
        mo.vstack(
            [
                mo.md(f"## 1 Checks {ICONS[_status]}"),
                *[badge(c) for c in _checks],
                mo.accordion(
                    {
                        c.name: mo.ui.table(c.details.reset_index(), selection=None)
                        for c in _checks
                        if not c.details.empty
                    }
                ),
                ignore_checks,
            ]
        )
    )
    mo.stop(_status == "fail" and not ignore_checks.value)
    checked = True
    return (checked,)


@app.cell
def _(checked, country, mo, pd, per_scenario, selected):
    assert checked
    _frames = {}
    for _scenario in mo.status.progress_bar(
        selected, title="Evaluating scenarios", remove_on_exit=True
    ):
        _frames[_scenario] = {
            name: per_scenario(name, _scenario, country)
            for name in (
                "global_constraints",
                "costs",
                "potential_summary",
                "transmission_table",
            )
        }
    constraints = pd.concat([f["global_constraints"] for f in _frames.values()])
    cost = pd.concat([f["costs"] for f in _frames.values()])
    potential = pd.concat([f["potential_summary"] for f in _frames.values()])
    grid = pd.concat([f["transmission_table"] for f in _frames.values()])
    horizons = sorted(cost.index.unique("horizon"))
    return constraints, cost, grid, horizons, potential


@app.cell
def _(constraints, mo):
    group_select = mo.ui.dropdown(
        options=["all", *sorted(constraints.group.unique())],
        value="national policy",
        label="Group",
    )
    return (group_select,)


@app.cell(expand_output=True)
def _(constraints, dp, group_select, layout, mo, px, table):
    _group = None if group_select.value == "all" else group_select.value
    _mu = dp.binding_matrix(constraints, _group)
    _shown = constraints if _group is None else constraints[constraints.group == _group]
    _heat = px.imshow(
        _mu.set_axis([f"{s} {h}" for s, h in _mu.columns], axis=1),
        color_continuous_scale="RdBu",
        color_continuous_midpoint=0,
        aspect="auto",
        text_auto=".3g",
    )
    layout(_heat, "Duals of the binding constraints (mu)", "")
    _heat.update_layout(height=max(300, 40 * len(_mu) + 120))
    mo.vstack(
        [
            mo.md(
                "## 4 Binding constraints\n\n"
                "A global constraint binds if `|mu| > 1e-3`. TYNDP constraints are summed "
                "per type (`count`, `binding` = number of binding ones). Potential caps "
                "(`p_nom_max`) have no stored dual; see A."
            ),
            group_select,
            mo.ui.plotly(_heat) if len(_mu) else mo.md("No binding constraint."),
            mo.accordion(
                {
                    "All constraints": table(
                        _shown.reset_index().set_index(["scenario", "horizon", "name"])
                    )
                }
            ),
        ]
    )
    return


@app.cell(expand_output=True)
def _(colours, cost, dp, go, layout, mo, others, reference, table):
    _cost = dp.add_deltas(cost, reference)
    _fig = go.Figure()
    for _scenario in others:
        _rows = _cost.xs(_scenario, level="scenario")
        _fig.add_trace(
            go.Bar(
                x=_rows.index,
                y=_rows["Δ total"],
                name=_scenario,
                marker_color=colours[_scenario],
            )
        )
    layout(_fig, f"Cost in the country, Δ vs {reference}", "bn EUR")
    mo.vstack(
        [
            mo.md(
                "## 5 Cost in the country\n\n"
                "Capex and opex of the assets in the country plus the net trade value "
                "(`country_cost`). The EU system cost is the objective and differs "
                "little between the runs."
            ),
            mo.ui.plotly(_fig),
            table(_cost),
        ]
    )
    return


@app.cell
def _(horizons, mo, others):
    def other_select(default: str, label: str = "Run"):
        value = next((s for s in others if s.startswith(default)), None)
        return mo.ui.dropdown(
            options=others, value=value or (others[0] if others else None), label=label
        )

    a_select = other_select("DP1")
    b_select = other_select("DP2")
    c_select = other_select("DP3")
    horizon_select = mo.ui.dropdown(
        options=horizons, value=horizons[-1], label="Horizon"
    )
    return a_select, b_select, c_select, horizon_select


@app.cell(expand_output=True)
def _(a_select, colours, go, layout, mo, potential, reference, table):
    _runs = [reference, a_select.value]
    _rows = potential.loc[_runs]
    _fig = go.Figure()
    for _scenario in _runs:
        _r = _rows.xs(_scenario, level="scenario").reset_index()
        _x = [_r.group, _r.horizon]
        _fig.add_trace(
            go.Bar(
                x=_x,
                y=_r.capacity,
                name=f"{_scenario} capacity",
                marker_color=colours[_scenario],
                offsetgroup=_scenario,
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=_x,
                y=_r.potential,
                name=f"{_scenario} potential",
                mode="markers",
                marker=dict(symbol="line-ew-open", size=22, color=colours[_scenario]),
            )
        )
    layout(_fig, "Capacity and potential per carrier group", "GW")
    _prod = go.Figure()
    for _scenario in _runs:
        _r = _rows.xs(_scenario, level="scenario").reset_index()
        _prod.add_trace(
            go.Bar(
                x=[_r.group, _r.horizon],
                y=_r.production,
                name=_scenario,
                marker_color=colours[_scenario],
            )
        )
    layout(_prod, "Production per carrier group", "TWh")
    mo.vstack(
        [
            mo.md(
                "## A Data (P1): do the potentials make a difference?\n\n"
                "Potential = `p_nom_max` of the extendable generators (headroom after "
                "the brownfield deduction) + existing capacity; ground PV shares the "
                "`solar` potential with `solar-hsat`. A bus is *binding* if its "
                "capacity reaches the potential, *forced* if the trajectory floor "
                "(`p_nom_min`) fills it. Curtailment needs hourly resolution."
            ),
            a_select,
            mo.ui.plotly(_fig),
            mo.ui.plotly(_prod),
            table(_rows),
        ]
    )
    return


@app.cell
def _(b_select, country, dp, mo, per_pair, reference):
    regional = per_pair(
        "regional_comparison",
        reference,
        b_select.value,
        country,
        reference,
        b_select.value,
    )
    shift = dp.regional_shift(regional)
    technology_select = mo.ui.dropdown(
        options=sorted(regional.index.unique("technology")),
        value="onwind",
        label="Technology",
    )
    return regional, shift, technology_select


@app.cell(expand_output=True)
def _(
    b_select,
    colours,
    go,
    horizon_select,
    layout,
    mo,
    reference,
    regional,
    shift,
    table,
    technology_select,
):
    _rows = regional.xs(
        (horizon_select.value, technology_select.value),
        level=["horizon", "technology"],
    )
    _fig = go.Figure()
    for _column, _scenario in [("reference", reference), ("other", b_select.value)]:
        _fig.add_trace(
            go.Bar(
                x=_rows.index,
                y=_rows[_column],
                name=_scenario,
                marker_color=colours[_scenario],
            )
        )
    layout(
        _fig,
        f"{technology_select.value} per NUTS 2 region, {horizon_select.value}",
        "GW (GWh for batteries)",
    )
    mo.vstack(
        [
            mo.md(
                "## B Resolution (P2): capacities per NUTS 2 region\n\n"
                "The finer run is summed to NUTS 2. `Δ total` says whether the "
                "resolution changes *how much* is built, `shift` "
                "(`Σ |Δ| / total of the reference`) *where* it is built."
            ),
            mo.hstack(
                [b_select, horizon_select, technology_select], justify="start", gap=2
            ),
            mo.ui.plotly(_fig),
            table(shift, label="AT total and regional shift"),
            mo.accordion({"Per region": table(regional)}),
        ]
    )
    return


@app.cell(expand_output=True)
def _(b_select, colours, go, grid, layout, mo, reference, table):
    _runs = [reference, b_select.value]
    _rows = grid.loc[_runs]
    _fig = go.Figure()
    for _scenario in _runs:
        _r = _rows.xs(_scenario, level="scenario").reset_index()
        for _view, _pattern in [("all", ""), ("cross-region", "/")]:
            _v = _r[_r.view == _view]
            _fig.add_trace(
                go.Bar(
                    x=[_v.carrier, _v.horizon],
                    y=_v["transport work"],
                    name=f"{_scenario} {_view}",
                    marker=dict(color=colours[_scenario], pattern_shape=_pattern),
                    offsetgroup=f"{_scenario} {_view}",
                )
            )
    layout(_fig, "Gross transport work inside the country", "TWh·km")
    mo.vstack(
        [
            mo.md(
                "## B ii Resolution (P2): total transmission inside the country\n\n"
                "Gross: no netting of directions, snapshots or branches. `energy` (TWh) "
                "counts a flow once per branch it passes, so a finer network shows "
                "more; `transport work` (TWh·km) does not depend on how a route is "
                "split. `cross-region`: only branches crossing NUTS 2 borders. Loading "
                "and time at the limit need hourly resolution."
            ),
            mo.ui.plotly(_fig),
            table(_rows),
        ]
    )
    return


@app.cell(expand_output=True)
def _(c_select, country, dp, mo, per_pair, reference, table):
    _other = c_select.value
    _status = per_pair("policy_status", reference, _other, country, reference)
    _outcomes = dp.add_deltas(
        per_pair("policy_outcomes", reference, _other, country, reference), reference
    )
    _replace = per_pair(
        "replacement_table", reference, _other, country, reference, _other
    )
    mo.vstack(
        [
            mo.md(
                "## C Policy (P3): are the policy goals binding, and what replaces "
                "them?\n\n"
                "**C1** value, target (constant of the reference) and dual of every "
                "national policy constraint. The values re-evaluate the constraint "
                "expressions on the solved network, also in a run without the "
                "constraint (with the reference's formula); `slack < 0` means the run "
                "misses the target."
            ),
            c_select,
            table(_status, digits=1),
            mo.md(
                "**C2** outcomes on the elements of the policies (Mt, TWh, GW), Δ vs "
                "the reference."
            ),
            table(_outcomes),
            mo.md(
                "**C3** constraints that bind the same elements: CO2 prices, binding "
                "potential buses (A), biomass potential used, electrolysis at its "
                "bound, net imports."
            ),
            table(_replace),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
