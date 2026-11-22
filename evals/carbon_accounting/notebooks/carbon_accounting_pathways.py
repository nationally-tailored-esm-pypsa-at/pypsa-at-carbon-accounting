# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Emissions of carbon accounting scenarios under every accounting method (marimo).

Evaluates every scenario of the carbon accounting configuration for all
planning horizons under the evaluators ``CA_technology`` and ``CA_carrier``,
split into the categories of the national balance bridge
of ``evals/carbon_accounting/notebooks/carbon_accounting.py``, and answers:

1. Are different evaluation methods needed for the two accounting methods?
2. How do they differ, and what happens if they are applied vice versa?
3. How do the decarbonisation pathways of the approaches differ?

All computations live in ``evals/carbon_accounting/pathways.py``. Run it from
the repository root with

    pixi run marimo edit evals/carbon_accounting/notebooks/carbon_accounting_pathways.py
"""

import marimo

__generated_with = "0.25.0"
app = marimo.App(width="full", app_title="Carbon accounting pathways")


@app.cell
def _():
    import sys
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import plotly.graph_objects as go

    REPO = Path(__file__).resolve().parents[3]
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    from evals.carbon_accounting import accounting as ca
    from evals.carbon_accounting import pathways as cp

    return REPO, ca, cp, go, mo, pd


@app.cell
def _(ca, cp, mo):
    # categorical slots in fixed order (validated palette); grey for "Other"
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
    EVALUATOR_COLOURS = dict(zip(cp.EVALUATORS, PALETTE))
    # one colour per category of the bridge; the claims share one colour and
    # differ by pattern
    _claims = list(ca.CLAIM_CATEGORIES.values())
    _others = [c for c in ca.CATEGORIES if c not in _claims]
    CATEGORY_STYLE = {c: (PALETTE[i], "") for i, c in enumerate(_others)}
    CATEGORY_STYLE.update(
        {c: (PALETTE[len(_others)], p) for c, p in zip(_claims, ["", "/", "x", "."])}
    )
    ICONS = {"ok": "✓", "warn": "⚠", "fail": "✗"}
    KINDS = {"ok": "success", "warn": "warn", "fail": "danger"}

    def badge(check) -> mo.Html:
        """Return a callout with the status icon, name and message of a check."""
        text = mo.md(f"**{ICONS[check.status]} {check.name}** — {check.message}")
        return mo.callout(text, kind=KINDS[check.status])

    def layout(fig, title: str, yaxis: str = "Mt CO2", height: int = 420):
        fig.update_layout(
            title=title,
            template="plotly_white",
            bargap=0.3,
            legend=dict(orientation="h", y=-0.2),
            hovermode="x unified",
            height=height,
            margin=dict(t=60, b=40),
        )
        fig.update_yaxes(title_text=yaxis, zeroline=True, zerolinecolor="#c3c2b7")
        fig.update_xaxes(type="category")
        return fig

    return CATEGORY_STYLE, EVALUATOR_COLOURS, badge, layout


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Carbon accounting: emissions under every method

    A scenario is **optimised** under one accounting method (its *method*), but its
    flows can be **evaluated** under either method (the *evaluator*). Both evaluators
    read the **same network elements** of a run and differ only in which of them count
    towards the national total. An element a run does not have counts as 0:

    | Category | Network element | `CA_technology` | `CA_carrier` |
    |---|---|---|---|
    | Fuel use, process & waste, capture credit | consumer, process and capture links | ✓ | ✓ |
    | Biofuel credit | bio producers: −EF × fuel output | ✓ | – |
    | Green import credit | green import links: −p0 | ✓ | – |
    | Captured CO2 used in synthetic fuels | synthetic producers: CO2 input | – | ✓ |
    | Claims gas, oil, kerosene, methanol | claim links: −EF × claim | – | ✓ (0 in technology runs) |

    Emissions are split into the categories of the national balance bridge (notebook
    `carbon_accounting.py`, section 2). National totals follow the national CO2 budget:
    links by name prefix, kerosene and kerosene claims scaled by the domestic aviation share.
    """)
    return


@app.cell
def _(REPO, mo):
    root_input = mo.ui.text(
        value=str(REPO / "results" / "carbon-accounting"),
        label="Result root",
        full_width=True,
    )
    root_input
    return (root_input,)


@app.cell
def _(ca, mo, root_input):
    files = ca.find_scenarios(root_input.value)
    mo.stop(
        not files,
        mo.callout(
            mo.md(f"✗ No solved networks found in `{root_input.value}`."), kind="danger"
        ),
    )
    info = ca.run_info(files)
    scenario_select = mo.ui.multiselect(
        options=list(files), value=ca.default_scenarios(info), label="Scenarios"
    )
    budget_countries = sorted({c for b in info.budgets for c in b.split(", ") if c})
    country_select = mo.ui.dropdown(
        options=budget_countries,
        value="AT" if "AT" in budget_countries else budget_countries[0],
        label="Country",
    )
    return country_select, files, info, scenario_select


@app.cell
def _(ca, country_select, info, mo, scenario_select):
    setup = ca.check_setup(info, list(scenario_select.value), country_select.value)
    _icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}[setup.status]
    mo.output.replace(
        mo.vstack(
            [
                mo.md("## 0 Setup"),
                mo.hstack([scenario_select, country_select], justify="start", gap=2),
                mo.md(f"**{_icon}** {setup.message}"),
                mo.ui.table(
                    info.loc[list(scenario_select.value)]
                    .drop(columns="file")
                    .reset_index(),
                    selection=None,
                    label="Networks per scenario and horizon",
                ),
            ]
        )
    )
    mo.stop(setup.failed)
    selected = list(scenario_select.value)
    country = country_select.value
    reference = ca.default_reference(info.loc[selected])
    return country, reference, selected


@app.cell
def _(ca, cp, mo):
    @mo.cache
    def load(path: str) -> dict:
        """Load the solved networks of one scenario, once."""
        return ca.load_networks(path)

    @mo.cache
    def scenario_emissions(path: str, scenario: str):
        """Evaluate one scenario under every evaluator, once."""
        return cp.emissions({scenario: load(path)})

    @mo.cache
    def scenario_checks(path: str, scenario: str) -> list:
        """Check the evaluators on one scenario, once."""
        return cp.checks({scenario: load(path)})

    return load, scenario_checks, scenario_emissions


@app.cell
def _(
    badge,
    country,
    cp,
    files,
    load,
    mo,
    pd,
    scenario_checks,
    scenario_emissions,
    selected,
):
    _paths = {s: str(files[s][next(iter(files[s]))].parents[1]) for s in selected}
    _frames, _checks = [], {}
    for _scenario in mo.status.progress_bar(
        selected, title="Loading and evaluating scenarios", remove_on_exit=True
    ):
        _frames.append(scenario_emissions(_paths[_scenario], _scenario))
        for _check in scenario_checks(_paths[_scenario], _scenario):
            _checks.setdefault(_check.name, []).append((_scenario, _check))
    frame = pd.concat(_frames)
    totals = cp.national_totals(frame, country)
    _networks = {s: load(_paths[s]) for s in selected}
    budget = cp.budgets(_networks, [country])[country]

    # one badge per check, merged over the scenarios
    _summary = [cp.merge_checks([c for _, c in _items]) for _items in _checks.values()]
    _status = "fail" if any(c.failed for c in _summary) else "ok"
    mo.output.replace(
        mo.vstack(
            [
                mo.md(f"### Checks {dict(ok='✓', fail='✗')[_status]}"),
                *[badge(c) for c in _summary],
            ]
        )
    )
    mo.stop(_status == "fail")
    return budget, frame, totals


@app.cell(hide_code=True, expand_output=True)
def _(budget, country, cp, mo, totals):
    _table = totals.copy()
    _table.insert(
        0, "budget", budget.reindex(totals.index.droplevel("method")).to_numpy()
    )
    mo.vstack(
        [
            mo.md(
                f"""
    ## 1 Are different evaluation methods needed?

    **Yes, for the national split, not for the EU total of a carrier scenario.** Both
    evaluators give the same EU total for every carrier scenario (check P5 above): the
    carrier method moves CO2 between countries and between the moment a fuel is made and
    the moment it is burned, but it creates or destroys no CO2.

    - **`{cp.TECHNOLOGY}`** reads the producers and green imports. It needs nothing but
      the physical flows, so it reads every scenario.
    - **`{cp.CARRIER}`** reads the claim links instead. A technology scenario has none, so
      its green fuels count as fossil at the consumer and nobody gets their credit: its EU
      total is higher than under `{cp.TECHNOLOGY}` by the green fuel burned.

    National totals of {country} under both evaluators, with the national budget (Mt CO2):
    """
            ),
            mo.ui.table(_table.round(2).reset_index(), selection=None),
        ]
    )
    return


@app.cell(hide_code=True, expand_output=True)
def _(EVALUATOR_COLOURS, budget, country, cp, go, layout, mo, totals):
    _gaps = cp.against_budget(totals, budget)

    def _scenario_figure(scenario: str):
        rows = totals.xs(scenario, level="scenario")
        method = rows.index.get_level_values("method")[0]
        horizons = rows.index.get_level_values("horizon")
        fig = go.Figure()
        for evaluator, colour in EVALUATOR_COLOURS.items():
            own = (evaluator, method) in [
                (cp.TECHNOLOGY, "technology"),
                (cp.CARRIER, "carrier"),
            ]
            fig.add_trace(
                go.Bar(
                    x=horizons,
                    y=rows[evaluator],
                    name=evaluator + (" (as booked)" if own else ""),
                    marker=dict(color=colour, line=dict(width=0)),
                    hovertemplate="%{y:.2f} Mt",
                )
            )
        fig.add_trace(
            go.Scatter(
                x=horizons,
                y=budget.xs(scenario, level="scenario").reindex(horizons),
                name="budget",
                mode="lines+markers",
                line=dict(color="#0b0b0b", dash="dash", width=2),
                marker=dict(size=8),
                hovertemplate="%{y:.2f} Mt",
            )
        )
        return mo.ui.plotly(
            layout(fig, f"{country}: {scenario} (optimised with method {method})")
        )

    _scenarios = list(totals.index.unique("scenario"))
    mo.vstack(
        [
            mo.md(
                f"""
    ## 2 How do they differ, and what if they are applied vice versa?

    Each scenario under every evaluator, against the national budget of {country}. The bar
    of the scenario's own method (*as booked*) meets the budget by construction (where the
    budget binds). The other bars show how the same physical system reads under the other
    method:

    - **A technology scenario evaluated as `CA_carrier`** loses the biofuel and green
      import credits of the green fuels it produces or imports and books the captured CO2
      used in synthetic fuels. It has no claim links, so it gets no credit for the green
      fuels it consumes: it misses its budget by the green fuel credits it relied on.
    - **A carrier scenario evaluated as `CA_technology`** loses all claims and gets the
      biofuel and green import credits of its own producers and importers back. A country
      that met its budget by claims shows its physical emissions, typically far above the
      budget.

    Distance to the budget (Mt CO2, positive = above budget):
    """
            ),
            mo.ui.table(_gaps.round(2).reset_index(), selection=None),
            *[_scenario_figure(s) for s in _scenarios],
        ]
    )
    return


@app.cell(expand_output=True)
def _(country, cp, go, mo, totals):
    # one column per (scenario, horizon): scenarios outer, horizons side by side
    _rows = cp.method_gap(totals).droplevel("method")
    _z = _rows.T.reindex(list(cp.EVALUATORS))
    _x = [
        list(_z.columns.get_level_values("scenario")),
        list(_z.columns.get_level_values("horizon").astype(str)),
    ]
    _heat = go.Figure(
        go.Heatmap(
            x=_x,
            y=list(_z.index),
            z=_z.to_numpy(),
            text=_z.map(lambda v: "" if v != v else f"{v:+.1f}").to_numpy(),
            texttemplate="%{text}",
            colorscale="RdBu_r",
            zmid=0,
            colorbar=dict(title="Δ Mt CO2"),
            hovertemplate="%{y}<br>%{x}: %{z:+.2f} Mt vs own method<extra></extra>",
        )
    )
    _heat.update_layout(
        title=f"{country}: evaluator minus own method per scenario and horizon (Mt CO2)",
        template="plotly_white",
        height=380,
        margin=dict(t=60, b=60),
    )
    _heat.update_xaxes(title_text="Scenario / horizon")
    _heat.update_yaxes(title_text="Evaluator", autorange="reversed")
    mo.vstack(
        [
            mo.md(
                f"### {country}: every evaluator against the scenario's own method\n\n"
                "Emissions under the evaluator minus emissions under the method the "
                "scenario was optimised with; the own method is 0 by construction."
            ),
            mo.ui.plotly(_heat),
        ]
    )
    return


@app.cell
def _(cp, mo, selected):
    pathway_scenario = mo.ui.dropdown(
        options=selected, value=selected[-1], label="Scenario"
    )
    pathway_evaluator = mo.ui.dropdown(
        options=list(cp.EVALUATORS), value=cp.TECHNOLOGY, label="Evaluator"
    )
    return pathway_evaluator, pathway_scenario


@app.cell(expand_output=True)
def _(
    CATEGORY_STYLE,
    country,
    cp,
    frame,
    go,
    layout,
    mo,
    pathway_evaluator,
    pathway_scenario,
):
    _pathway = cp.category_pathway(
        frame, country, pathway_scenario.value, pathway_evaluator.value, cutoff=1e-3
    )
    _fig = go.Figure()
    for _category in _pathway.columns:
        _colour, _pattern = CATEGORY_STYLE[_category]
        _fig.add_trace(
            go.Bar(
                x=_pathway.index,
                y=_pathway[_category],
                name=_category,
                marker=dict(
                    color=_colour,
                    line=dict(width=0),
                    pattern=dict(shape=_pattern, fgcolor="#ffffff"),
                ),
                hovertemplate="%{y:.2f} Mt",
            )
        )
    _fig.add_trace(
        go.Scatter(
            x=_pathway.index,
            y=_pathway.sum(axis=1),
            name="total",
            mode="lines+markers",
            line=dict(color="#0b0b0b", width=2),
            marker=dict(size=8),
            hovertemplate="%{y:.2f} Mt",
        )
    )
    _fig.update_layout(barmode="relative")
    _chart = mo.ui.plotly(
        layout(
            _fig,
            f"{country}: {pathway_scenario.value} evaluated as "
            f"{pathway_evaluator.value}",
            height=480,
        )
    )
    mo.vstack(
        [
            mo.md(
                "## 3 Decarbonisation pathways\n\n"
                "The categories of the national balance bridge. Fuel use, process & "
                "waste and capture credit are physical; biofuel credit and green import "
                "credit exist only in `CA_technology`; captured CO2 used in synthetic "
                "fuels and the claims only in `CA_carrier` (no claims in a technology "
                "scenario)."
            ),
            mo.hstack([pathway_scenario, pathway_evaluator], justify="start", gap=2),
            _chart,
        ]
    )
    return


@app.cell(hide_code=True)
def _(ca, country, cp, frame, mo, reference):
    _categories = (
        frame.xs((country, cp.TECHNOLOGY), level=["country", "evaluator"])
        .emissions.groupby(["scenario", "horizon", "category"])
        .sum()
    )
    _table = ca.difference_table(_categories, reference, cutoff=1e-3)
    mo.vstack(
        [
            mo.md(
                f"### Physical pathway by category against {reference}\n\n"
                f"{country} evaluated as `{cp.TECHNOLOGY}`, Δ against {reference} "
                "(Mt CO2). Positive Δ: the scenario emits more in that category."
            ),
            mo.ui.table(_table.round(2).reset_index(), selection=None),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
