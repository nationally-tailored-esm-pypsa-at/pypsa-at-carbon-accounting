import marimo

__generated_with = "0.25.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import pypsa

    return go, mo, np, pd, pypsa


@app.cell
def _(pypsa):
    fp = "/home/mnutz/projects/pypsa-at-carbon-accounting/results/carbon-accounting/CA_carrier/networks/solved_2030.nc"
    n = pypsa.Network(fp)
    # technology-based accounting (status quo) of the same model and horizon
    n_tech = pypsa.Network(fp.replace("/CA_carrier/", "/CA_base/"))
    return n, n_tech


@app.cell
def _(n):
    buses_biogas = n.buses[n.buses.carrier == "biogas"].index
    n.links[n.links.bus0.isin(buses_biogas)].carrier.unique()
    return


@app.cell
def _(n):
    n.links[n.links.carrier == "methanol-to-kerosene"]
    return


@app.cell
def _(n):
    buses_attr = n.buses[
        n.buses["carrier"].str.contains("attribute", case=False, na=False)
    ].index
    n.links[
        n.links.bus0.isin(buses_attr)
        | n.links.bus1.isin(buses_attr)
        | n.links.bus2.isin(buses_attr)
        | n.links.bus3.isin(buses_attr)
    ]
    return


@app.cell
def _(n):
    n.links[n.links.carrier == "methanol-to-kerosene"]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Creation of the attribution layer
    1. **Create the network elements:**
      - one bus per country for gas, one bus per country and one EU-bus each for methanol and oil.
      - one store per country for yearly balancing
      - a generator for renewable-fuel import to the system
      - links between the buses for gas, links from the bus to the EU bus for the respective carrier of methanol and oil

    2. **Transform existing emission ports**
      - adapts the existing links to `co_2 atmosphere` to change behaviour of links that represent technologies, creating renewable (bio and synthetic) fuels
      -

    ```bash
    ┌─────────────────────┬─────────────────┬────────────────────┬───────────────────────────────────────────┐
    │        Link         │ atm, technology │    atm, carrier    │                   Check                   │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ biogas to gas       │ −0.198          │ 0.0                │ ✅ credit gone                            │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ biogas to gas CC    │ −0.3282         │ −0.1302            │ ✅ only the stored share keeps its credit │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ biomass to liquid   │ −0.1157         │ 0.0                │ ✅                                        │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ electrobiofuels     │ −0.3416         │ −0.0001            │ ✅ (rounding in technology-data)          │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ biomass-to-methanol │ −0.1614         │ −0.0002            │ ✅                                        │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ Fischer-Tropsch     │ —               │ +0.1939 (new                       │
    ├─────────────────────┼─────────────────┼────────────────────┼───────────────────────────────────────────┤
    │ Sabatier            │ —               │ +0.1584 (new port) │ ✅ = 0.8 × 0.198                          │
    ├─────────────────────┼─────────────────┼────────────────────────────────────┤
    │ methanolisation     │ —               │ +0.2179 (new port) │ ✅ = 0.8787 × 0.248                       │
    └─────────────────────┴─────────────────┴────────────────────┴───────────────────────────────────────────┘
    ```

    3. **Introduces a fair-share** of attributes, countries can claim
      - sums over all FIXED loads of the respective fuel
      - normalizes everything per fuel, so all part per fuel sum to 1
      - adds that as new column element to the claim-links.

    ## Structure of the attribution layer

    The carrier method adds an accounting layer of attribute buses. Green fuel
    producers feed one attribute per MWh into it, claim links take the
    attributes out again and book them against `co2 atmosphere`.

    - **gas**: one attribute bus per country, linked by transfers along the gas pipelines
    - **oil, methanol**: an `EU` pool that distributes to one claim bus per country
    - **co2 import**: virtual carbon source of green imports

    The table below summarises all producers that feed the attribute buses.
    The schematic shows the layer for the selected countries in detail:

    - **ellipses** are buses, coloured attribute buses form the accounting layer
    - **boxes** are the producer links, grouped by country and carrier; edges
      to and from their buses are labelled with the mean port efficiency
    - **bold edges** are the two-port links of the layer itself (transfers,
      distributions, claims), labelled with their efficiency
    - attribute buses of the other countries are merged into one node per fuel,
      their producers into one box; hover over nodes and edges for annual flows

    The map further down shows the attribute buses of all countries.
    """)
    return


@app.cell
def _(n, pd):
    attribute_kinds = {
        "renewable gas attribute": "gas",
        "renewable oil attribute": "oil",
        "renewable methanol attribute": "methanol",
    }
    layer_roles = {
        "renewable gas attribute transfer": "transfer",
        "renewable oil attribute distribution": "distribution",
        "renewable methanol attribute distribution": "distribution",
        "renewable gas claim": "claim",
        "renewable oil claim": "claim",
        "renewable oil claim aviation": "claim",
        "renewable methanol claim": "claim",
    }
    kind_colors = {"gas": "#e05b09", "oil": "#7a5195", "methanol": "#2f9e8f"}
    co2_import, atmosphere = "co2 import", "co2 atmosphere"

    _w = n.snapshot_weightings.generators
    _ports = sorted(
        int(c[3:]) for c in n.links.columns if c.startswith("bus") and c[3:].isdigit()
    )

    def annual(port, links):
        """Annual energy at a link port, positive into the link."""
        df = n.links_t[f"p{port}"].reindex(columns=links, fill_value=0.0)
        return df.mul(_w, axis=0).sum()

    layer_buses = n.buses[n.buses.carrier.isin(attribute_kinds)].assign(
        kind=lambda df: df.carrier.map(attribute_kinds),
        country=lambda df: df.location,
        has_store=lambda df: df.index.isin(n.stores.bus),
    )
    layer_links = n.links[n.links.carrier.isin(layer_roles)][
        ["bus0", "bus1", "carrier", "efficiency"]
    ].assign(role=lambda df: df.carrier.map(layer_roles))
    layer_links["kind"] = layer_links.bus0.map(layer_buses.kind)
    layer_links["flow"] = annual(0, layer_links.index)

    # every other link with a port at an attribute bus is a producer
    _rows = []
    for _p in _ports[1:]:
        _at = n.links[f"bus{_p}"].isin(layer_buses.index) & ~n.links.carrier.isin(
            layer_roles
        )
        _idx = n.links.index[_at]
        _rows.append(
            pd.DataFrame(
                {
                    "bus0": n.links.loc[_idx, "bus0"],
                    "attribute_bus": n.links.loc[_idx, f"bus{_p}"],
                    "carrier": n.links.loc[_idx, "carrier"],
                    "flow": -annual(_p, _idx),
                }
            )
        )
    producers = pd.concat(_rows)
    producers["kind"] = producers.attribute_bus.map(layer_buses.kind)
    return (
        atmosphere,
        co2_import,
        kind_colors,
        layer_buses,
        layer_links,
        producers,
    )


@app.cell
def _(producers):
    producer_summary = (
        producers.assign(flow=producers.flow / 1e6)
        .groupby(["kind", "carrier"])
        .agg(
            links=("flow", "size"),
            attribute_buses=("attribute_bus", "nunique"),
            attributes_TWh=("flow", "sum"),
        )
        .round(2)
    )
    producer_summary
    return


@app.cell
def _(layer_buses, mo):
    country_select = mo.ui.multiselect(
        options=sorted(set(layer_buses.country) - {"EU"}),
        value=["AT", "DE"],
        label="Countries in the schematic",
    )
    show_labels = mo.ui.checkbox(label="Show all edge labels")
    mo.hstack([country_select, show_labels], justify="start", gap=2)
    return country_select, show_labels


@app.cell
def _(atmosphere, co2_import, kind_colors, layer_buses, mo, pd, show_labels):
    import html
    import re
    import shutil
    import subprocess

    def schematic(n, producers, layer_links, selected, kind):
        """
        Return the DOT source of the schematic of one fuel kind.

        ``producers`` holds the producer links (columns ``bus0``,
        ``attribute_bus``, ``flow``, ``kind``), ``layer_links`` the two-port
        links of the accounting layer, empty for the technology method.
        """
        w = n.snapshot_weightings.generators
        ports = sorted(
            int(c[3:])
            for c in n.links.columns
            if c.startswith("bus") and c[3:].isdigit()
        )
        units = {"MWh": "TWh", "t_co2": "Mt"}
        # co2 atmosphere is drawn twice: at the producer ports and as claim sink
        emissions, sink = "co2 atmosphere (ports)", "co2 atmosphere (claims)"
        color = kind_colors[kind]
        other = f"other {kind} attributes"

        def bus_group(bus):
            """Aggregate a bus to its country and carrier, keep layer buses."""
            if bus == co2_import:
                return bus
            if bus == atmosphere:
                return emissions
            if bus in layer_buses.index:
                ct = layer_buses.at[bus, "country"]
                return bus if ct in selected or ct == "EU" else other
            return f"{n.buses.at[bus, 'location'][:2]} {n.buses.at[bus, 'carrier']}"

        def fmt(flow, bus):
            unit = n.buses.at[bus, "unit"] if bus in n.buses.index else ""
            return f"{flow / 1e6:.2f} {units.get(unit, 'M' + str(unit))}"

        def q(text):
            return '"' + str(text).replace('"', r"\"") + '"'

        prod = producers[producers.kind == kind]
        # producer country: the fuel output bus, or bus0 for EU-wide fuel buses
        loc = prod.index.to_series().map(
            lambda link: n.buses.at[n.links.at[link, "bus1"], "location"]
        )
        loc = loc.where(loc != "EU", prod.bus0.map(n.buses.location).fillna("EU"))
        country = loc.str[:2]
        inside = country.isin(selected) | (country == "EU")

        # edges of the selected producers, one row per link port
        rows = []
        links = n.links.loc[prod.index[inside]]
        for p in ports:
            col = "efficiency" if p == 1 else f"efficiency{p}"
            bus = links[f"bus{p}"].fillna("")
            at = links[bus != ""]
            flow = -n.links_t[f"p{p}"].reindex(columns=at.index, fill_value=0.0)
            rows.append(
                pd.DataFrame(
                    {
                        "link": country[at.index].astype(str)
                        + " · "
                        + at.carrier.astype(str),
                        "bus": bus[at.index],
                        "group": bus[at.index].map(bus_group),
                        "efficiency": -1.0 if p == 0 else at[col].astype(float),
                        "flow": flow.mul(w, axis=0).sum(),
                    }
                )
            )
        ports_df = pd.concat(rows)
        edges = ports_df.groupby(["link", "group"]).agg(
            efficiency=("efficiency", "mean"),
            flow=("flow", "sum"),
            bus=("bus", "first"),
        )
        n_links = ports_df.reset_index().groupby("link")["name"].nunique()

        # producers outside the selection only feed their attribute buses
        outside = prod[~inside & prod.attribute_bus.notna()].assign(
            group=lambda df: df.attribute_bus.map(bus_group)
        )
        outside_edges = outside.groupby("group").agg(
            flow=("flow", "sum"), bus=("attribute_bus", "first"), links=("flow", "size")
        )

        # two-port links of the layer, aggregated between bus groups
        layer = layer_links[layer_links.kind == kind].assign(
            g0=lambda df: df.bus0.map(bus_group),
            g1=lambda df: df.bus1.map(bus_group).replace(emissions, sink),
        )
        layer = layer[layer.g0 != layer.g1]
        layer_edges = layer.groupby(["g0", "g1", "role"]).agg(
            efficiency=("efficiency", "mean"),
            flow=("flow", "sum"),
            links=("flow", "size"),
            bus=("bus0", "first"),
        )

        lines = [
            "digraph G {",
            "rankdir=LR; ranksep=0.9; nodesep=0.15; newrank=true;",
            'node [fontname="Helvetica", fontsize=10];',
            'edge [fontname="Helvetica", fontsize=8];',
        ]

        # columns: inputs | producers | outputs | attribute buses | claim sink
        attribute_nodes = sorted(
            {
                g
                for g in set(layer.g0) | set(layer.g1) | set(outside_edges.index)
                if g in layer_buses.index or g == other
            }
        )
        bus_edges = edges.reset_index()
        bus_edges = bus_edges[~bus_edges.group.isin(attribute_nodes)]
        is_output = bus_edges.efficiency > 0
        outputs = sorted(set(bus_edges.group[is_output]))
        inputs = sorted(set(bus_edges.group) - set(outputs))

        def column(nodes):
            if nodes:
                lines.append("{rank=same; " + " ".join(q(g) for g in nodes) + "}")

        for g in inputs + outputs:
            if g in (co2_import, emissions):
                label = atmosphere if g == emissions else g
                lines.append(
                    f"{q(g)} [label={q(label)}, shape=diamond, style=filled, "
                    "fillcolor=black, fontcolor=white];"
                )
            else:
                lines.append(
                    f'{q(g)} [shape=ellipse, style=filled, fillcolor="#eeeeee", '
                    'color="#888888"];'
                )
        for g in attribute_nodes:
            pool = g in layer_buses.index and layer_buses.at[g, "country"] == "EU"
            store = g in layer_buses.index and layer_buses.at[g, "has_store"]
            style = "filled,dashed" if g == other else "filled"
            lines.append(
                f"{q(g)} [shape={'doubleoctagon' if pool else 'ellipse'}, "
                f"style={q(style)}, fillcolor={q(color)}, fontcolor=white, "
                f"peripheries={2 if store else 1}, "
                f"tooltip={q(g + (' (cyclic store)' if store else ''))}];"
            )
        if not layer_edges.empty:
            lines.append(
                f"{q(sink)} [label={q(atmosphere)}, shape=diamond, style=filled, "
                "fillcolor=black, fontcolor=white];"
            )
            lines.append(f"{{rank=sink; {q(sink)}}}")
        producer_nodes = list(n_links.index)
        for link, count in n_links.items():
            label = link.replace(" · ", "\n") + f" ({count})"
            lines.append(
                f'{q(link)} [shape=box, style="rounded,filled", '
                f'fillcolor="#fff6d5", label={q(label)}];'
            )
        if not outside_edges.empty:
            producer_nodes.append("producers in other countries")
            lines.append(
                '"producers in other countries" [shape=box, '
                'style="rounded,filled,dashed", fillcolor="#fff6d5"];'
            )
        column(inputs)
        column(producer_nodes)
        column(outputs)

        for (link, g), e in edges.iterrows():
            in_layer = g in attribute_nodes
            ecolor = color if in_layer else ("#333333" if g == emissions else "#aaaaaa")
            a, b = (g, link) if e.efficiency < 0 else (link, g)
            # inputs from the output column must not pull it to the left
            constraint = "false" if e.efficiency < 0 and g in outputs else "true"
            tooltip = f"{link} → {g}: {fmt(e.flow, e.bus)}"
            lines.append(
                f"{q(a)} -> {q(b)} [label={q(f'{e.efficiency:.3g}')}, "
                f"color={q(ecolor)}, fontcolor={q(ecolor)}, "
                f"penwidth={1.6 if in_layer else 1}, tooltip={q(tooltip)}, "
                f"constraint={constraint}];"
            )
        for g, e in outside_edges.iterrows():
            tooltip = f"{e.links} links: {fmt(e.flow, e.bus)}"
            lines.append(
                f'"producers in other countries" -> {q(g)} [style=dashed, '
                f"color={q(color)}, tooltip={q(tooltip)}];"
            )

        # the layer's own two-port links
        for (g0, g1, role), e in layer_edges.iterrows():
            ecolor = "#333333" if role == "claim" else color
            label = role if role != "claim" else f"claim {e.efficiency:.3g}"
            tooltip = f"{e.links} {role} links: {fmt(e.flow, e.bus)}"
            lines.append(
                f"{q(g0)} -> {q(g1)} [penwidth=2.2, color={q(ecolor)}, "
                f"fontcolor={q(ecolor)}, label={q(label)}, tooltip={q(tooltip)}];"
            )
        lines.append("}")
        return "\n".join(lines)

    # graphviz is a pixi dependency; fail early instead of guessing from PATH
    DOT = shutil.which("dot")
    if DOT is None:
        raise FileNotFoundError("Graphviz 'dot' not found, run inside the pixi env.")

    def render(dot, scope):
        # fixed argv without a shell, the DOT source only reaches dot via stdin
        svg = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            [DOT, "-Tsvg"],
            input=dot,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return interactive(svg[svg.index("<svg") :], scope)

    def interactive(svg, scope):
        """
        Highlight a hovered node with its edges and neighbours, using CSS only.

        Marimo does not run scripts in HTML output, so every node gets the
        class ``n{i}`` plus ``nb{j}`` per neighbour j, every edge ``e{i}`` per
        end, and one ``:has(:hover)`` rule per node switches them on.
        """
        title = r'<g id="(?:node|edge)\d+" class="(node|edge)">\s*<title>(.*?)</title>'
        found = [(kind, html.unescape(t)) for kind, t in re.findall(title, svg)]
        index = {name: i for i, (kind, name) in enumerate(found) if kind == "node"}
        ends = [
            [index[x] for x in name.split("->", 1)]
            for kind, name in found
            if kind == "edge"
        ]
        neighbours = {i: {i} for i in index.values()}
        for a, b in ends:
            neighbours[a].add(b)
            neighbours[b].add(a)

        classes = iter(
            " ".join(
                [f"node n{index[name]}"] + [f"nb{j}" for j in neighbours[index[name]]]
            )
            if kind == "node"
            else f"edge e{index[name.split('->', 1)[0]]} e{index[name.split('->', 1)[1]]}"
            for kind, name in found
        )
        svg = re.sub(
            r'(<g id="(?:node|edge)\d+" )class="(?:node|edge)"',
            lambda m: f'{m.group(1)}class="{next(classes)}"',
            svg,
        )

        w = f".ca-{scope}"
        hidden = "" if show_labels.value else f"{w} .edge text {{display: none}}"
        rules = [
            f"{w} .node, {w} .edge {{transition: opacity .15s}}",
            hidden,
            f"{w}:has(.node:hover) .node, {w}:has(.node:hover) .edge {{opacity: .12}}",
            f"{w} .edge:hover text {{display: inline}}",
            f"{w} .edge:hover path {{stroke-width: 4}}",
            f"{w} .node:hover {{cursor: pointer}}",
        ]
        for i in index.values():
            on = f"{w}:has(.n{i}:hover)"
            rules.append(f"{on} .nb{i}, {on} .e{i} {{opacity: 1}}")
            rules.append(f"{on} .e{i} text {{display: inline}}")
        style = "<style>" + "\n".join(rules) + "</style>"
        return mo.Html(
            f'{style}<div class="ca-{scope}" style="overflow:auto">{svg}</div>'
        )

    return render, schematic


@app.cell(expand_output=True)
def _(
    country_select,
    kind_colors,
    layer_links,
    mo,
    n,
    producers,
    render,
    schematic,
):
    _dot = {
        kind: schematic(n, producers, layer_links, country_select.value, kind)
        for kind in kind_colors
    }
    mo.vstack(
        [
            mo.md(
                "### Carrier-based method\n\n"
                "Hover over a node to highlight its links and neighbours, "
                "over an edge for its label and annual flow."
            ),
            mo.ui.tabs({k: render(d, f"carrier-{k}") for k, d in _dot.items()}),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Technology-based method

    The same producers in the `CA_base` run. There is no accounting layer:
    bio-fuel producers book their credit at the `co2 atmosphere` port when the
    fuel is created, synthetic fuel producers take their CO2 from `co2 stored`
    without an emission port, and green imports draw their carbon from
    `co2 atmosphere` instead of `co2 import`.
    """)
    return


@app.cell(expand_output=True)
def _(
    country_select,
    kind_colors,
    layer_links,
    mo,
    n_tech,
    pd,
    producers,
    render,
    schematic,
):
    # the producers of the carrier run, found by carrier in the technology run
    _kind = producers.groupby("carrier").kind.first()
    _links = n_tech.links[n_tech.links.carrier.isin(_kind.index)]
    producers_tech = pd.DataFrame(
        {
            "bus0": _links.bus0,
            "carrier": _links.carrier,
            "attribute_bus": float("nan"),
            "flow": 0.0,
            "kind": _links.carrier.map(_kind),
        }
    )
    _dot = {
        kind: schematic(
            n_tech, producers_tech, layer_links.iloc[:0], country_select.value, kind
        )
        for kind in kind_colors
    }
    mo.ui.tabs({k: render(d, f"technology-{k}") for k, d in _dot.items()})
    return


@app.cell(expand_output=True)
def _(go, kind_colors, layer_buses, layer_links, np):
    def geo_figure():
        # shift the kinds apart, the buses of one country share their coordinates
        shift = {"gas": 0.0, "oil": -0.4, "methanol": 0.4}
        xy = layer_buses[["x", "y"]].assign(
            x=lambda df: df.x + layer_buses.kind.map(shift)
        )
        links = layer_links[layer_links.role.isin(["transfer", "distribution"])]
        # merge the two directions of a gas border into one line
        pair = links.apply(lambda r: tuple(sorted([r.bus0, r.bus1])), axis=1)
        edges = links.groupby(pair).agg(
            kind=("kind", "first"),
            role=("role", "first"),
            flow=("flow", "sum"),
            names=(
                "flow",
                lambda s: "<br>".join(f"{i}: {v / 1e6:.2f} TWh" for i, v in s.items()),
            ),
        )
        max_flow = edges.flow.max() or 1.0

        fig = go.Figure()
        shown = set()
        for (a, b), e in edges.iterrows():
            label = f"{e.kind} {e.role}"
            fig.add_trace(
                go.Scattergeo(
                    lon=[xy.at[a, "x"], xy.at[b, "x"]],
                    lat=[xy.at[a, "y"], xy.at[b, "y"]],
                    mode="lines",
                    name=label,
                    legendgroup=label,
                    showlegend=label not in shown,
                    line=dict(
                        color=kind_colors[e.kind], width=0.5 + 6 * e.flow / max_flow
                    ),
                    opacity=0.8 if e.role == "transfer" else 0.35,
                    text=e.names,
                    hoverinfo="text",
                )
            )
            shown.add(label)

        for kind, color in kind_colors.items():
            buses = layer_buses[layer_buses.kind == kind]
            is_pool = buses.country == "EU"
            fig.add_trace(
                go.Scattergeo(
                    lon=xy.loc[buses.index, "x"],
                    lat=xy.loc[buses.index, "y"],
                    mode="markers",
                    name=f"{kind} attribute bus",
                    text=buses.index,
                    hoverinfo="text",
                    marker=dict(
                        color=color,
                        size=np.where(is_pool, 14, 7),
                        symbol=np.where(buses.has_store, "square", "circle"),
                        line=dict(color="white", width=0.5),
                    ),
                )
            )

        fig.update_geos(
            projection_type="mercator",
            lonaxis_range=[-12, 35],
            lataxis_range=[34, 71],
            showcountries=True,
            countrycolor="#bbbbbb",
            showland=True,
            landcolor="#f4f4f4",
        )
        fig.update_layout(
            title="Geographic representation of the attribution layer",
            height=800,
            margin=dict(l=0, r=0, t=50, b=0),
        )
        return fig

    geo_figure()
    return


@app.cell
def _():
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
