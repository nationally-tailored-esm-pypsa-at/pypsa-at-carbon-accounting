# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Constants of the carbon accounting."""

from frozendict import frozendict

# Carbon accounting (docs-ca/explanations/carbon-accounting-spec.md, section 3.2).
# Link carriers per transformation class of the carrier-based method.
GREEN_BIO_PRODUCERS: tuple[str, ...] = (
    "biogas to gas",
    "biogas to gas CC",
    "BioSNG",
    "BioSNG CC",
    "biomass to liquid",
    "biomass to liquid CC",
    "electrobiofuels",
    "unsustainable bioliquids",
    "biomass-to-methanol",
    "biomass-to-methanol CC",
)
# synthetic fuel producers are charged for the captured CO2 they use (CCU)
GREEN_SYNTHETIC_PRODUCERS: tuple[str, ...] = (
    "Fischer-Tropsch",
    "Sabatier",
    "methanolisation",
)
GREEN_IMPORTS: tuple[str, ...] = ("import gas", "import oil", "import methanol")
# capture, sequestration and vent keep their technology-based coefficients
CAPTURE: tuple[str, ...] = (
    "DAC",
    "SMR CC",
    "gas for industry CC",
    "urban central gas CHP CC",
    "CCGT methanol CC",
    "Methanol steam reforming CC",
    "allam gas",
    "allam methanol",
    "waste CHP CC",
    "process emissions CC",
    "solid biomass for industry CC",
    "solid biomass to hydrogen",
    "urban central solid biomass CHP CC",
)
SEQUESTRATION: tuple[str, ...] = ("co2 sequestered",)
VENT: tuple[str, ...] = ("co2 vent",)
FUEL_TRANSPORT: tuple[str, ...] = ("gas pipeline", "gas pipeline new")
# links at CO2 or fuel buses that both methods treat the same
UNCHANGED: tuple[str, ...] = (
    *FUEL_TRANSPORT,
    "CO2 pipeline",
    "co2 compression",
    "co2 expansion",
    "CCGT",
    "OCGT",
    "SMR",
    "gas for industry",
    "methane pyrolysis plasma",
    "rural gas boiler",
    "urban central gas boiler",
    "urban decentral gas boiler",
    "urban central gas CHP",
    "agriculture machinery oil",
    "kerosene for aviation",
    "land transport oil",
    "naphtha for industry",
    "shipping oil",
    "oil",
    "rural oil boiler",
    "urban decentral oil boiler",
    "urban central oil CHP",
    "CCGT methanol",
    "OCGT methanol",
    "Methanol steam reforming",
    "industry methanol",
    "methanol-to-kerosene",
    "shipping methanol",
    "coal",
    "coal for industry",
    "lignite",
    "urban central coal CHP",
    "urban central lignite CHP",
    "oil refining",
    "nuclear",
    "process emissions",
    "HVC to air",
    "waste CHP",
    "municipal solid waste",
)
# bus carriers whose link ports must be classified
CO2_BUS_CARRIERS: tuple[str, ...] = (
    "co2",
    "co2 stored",
    "co2 dense",
    "co2 sequestered",
)
ACCOUNTING_FUELS: tuple[str, ...] = ("gas", "oil", "methanol")

# accounting layer of the carrier-based method (section 3.3)
CARBON_ACCOUNTING_METHODS: tuple[str, ...] = ("technology", "carrier")
CARBON_ACCOUNTING_MARKER = "carbon_accounting"
CO2_IMPORT = "co2 import"
ATTRIBUTE_CARRIERS: frozendict = frozendict(
    {
        "gas": "renewable gas attribute",
        "oil": "renewable oil attribute",
        "methanol": "renewable methanol attribute",
    }
)
# fuels whose attributes are pooled EU-wide (D3); gas follows the pipelines
POOLED_ATTRIBUTES: tuple[str, ...] = ("oil", "methanol")
CLAIM_CARRIERS: frozendict = frozendict(
    {
        "gas": "renewable gas claim",
        "oil": "renewable oil claim",
        "oil aviation": "renewable oil claim aviation",
        "methanol": "renewable methanol claim",
    }
)
AVIATION_CARRIERS: tuple[str, ...] = (
    "kerosene for aviation",
    CLAIM_CARRIERS["oil aviation"],
)
TRANSFER_CARRIER = "renewable gas attribute transfer"
# fixed demand that defines the fair share key of each pooled claim (D18):
# carriers of the load buses, each supplied by one consumer link of the fuel
FAIR_SHARE_DEMAND: frozendict = frozendict(
    {
        "oil": (
            "land transport oil",
            "naphtha for industry",
            "shipping oil",
            "agriculture machinery oil",
        ),
        "oil aviation": ("kerosene for aviation",),
        "methanol": ("industry methanol", "shipping methanol"),
    }
)
FAIR_SHARE_KEY = "fair_share_key"
DISTRIBUTION_CARRIERS: frozendict = frozendict(
    {k: f"{ATTRIBUTE_CARRIERS[k]} distribution" for k in POOLED_ATTRIBUTES}
)
