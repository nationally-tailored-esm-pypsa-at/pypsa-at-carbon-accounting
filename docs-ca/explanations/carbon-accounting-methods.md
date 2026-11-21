# Carbon Accounting Methods

PyPSA-AT balances national CO2 emissions with the technology-based method described in
[National CO2 Balance](https://pypsa-at.readthedocs.io/en/latest/explanations/co2-balancing/)
of the PyPSA-AT documentation. This fork adds a switch between that method and a
carrier-based one.

The configuration key `mods.carbon_accounting.method` decides *where* a green fuel
counts as green. The choice applies to the whole model: the national CO2 budgets, the
EU-wide CO2 limit and the CO2 balances in the evaluations.

```yaml
mods:
  carbon_accounting:
    enable: true
    method: technology   # technology | carrier
    claim_cost: 0.01     # EUR/t CO2, carrier method only
```

| | `technology` (default) | `carrier` |
|---|---|---|
| Producing biomethane, bio-oil or e-fuels | negative emissions in the producing country | zero |
| Burning a green fuel | emissions in the burning country, like fossil fuel | zero, if the country claims the green fuel |
| Burning a fossil fuel | emissions in the burning country | emissions in the burning country |
| Green fuel imports from outside Europe | negative emissions at the entry point (oil and methanol: no country) | zero in the country that claims them |
| CO2 captured and stored (CCS, DAC) | negative emissions where the CO2 is captured | negative emissions where the CO2 is captured |
| CO2 captured and turned into e-fuels (CCU) | negative emissions at the capture plant | the e-fuel plant books the CO2 it uses, so the capture credit is cancelled; the e-fuel itself counts as green |

**How the carrier method works.** The gas, oil and methanol networks stay as they are:
green and fossil molecules still mix in the same pipelines and markets. In parallel, every
MWh of green fuel creates a *green certificate* (an attribute). A country can turn
certificates into avoided emissions by *claiming* them, at the emission factor of the fuel
(gas 0.198, oil 0.2571, methanol 0.248 t CO2/MWh). Three rules keep the bookkeeping honest:

1. A country can claim at most as much green fuel as it consumes in the year. Green
   kerosene is claimed against kerosene for aviation only, and it is scaled with the
   domestic aviation share, like kerosene itself.
2. Green gas certificates only travel along the gas pipelines: from one country to the
   next, at most as much as gas actually flowed across that border in the year.
   Certificates for oil and methanol are traded freely across Europe.
3. Every certificate is claimed by the end of the year. The EU-wide CO2 balance is
   therefore exactly the same as under the technology method; only the split between
   countries changes.

Captured CO2 counts as negative emissions in the capturing country (point sources, DAC,
biogenic capture), as under the technology method, unless it is used for e-fuels. The
e-fuel plant (Fischer-Tropsch, Sabatier, methanolisation) books the CO2 it takes as an
emission in its own country. A country therefore keeps the credit only for CO2 that it
does not turn into e-fuels itself: CO2 that it stores or exports to storage. If exported
CO2 is turned into e-fuels abroad, the importing country books it.

**Who claims what.** Within these limits, the model decides which country claims a
certificate. Countries with a national CO2 budget (Austria, Germany) claim certificates
only when their budget needs them: their claims carry a tiny cost (`claim_cost`) that
breaks the tie in favour of the other countries. Without it, the split between countries
would be arbitrary whenever no national budget binds. The evaluation
*Carbon Accounting Claims* shows the claimed credits per country next to the credit it
would receive at the EU-average green share of each fuel, so that this effect is visible.

**Fair share (optional).** With `mods.carbon_accounting.fair_share.enable: true`, Austria
and Germany can claim pooled oil, kerosene and methanol certificates only up to their fair
share: their share of the EU's fixed demand for that fuel (transport, aviation, naphtha,
shipping, agriculture, industry methanol) times the green fuel produced in the EU, times
`tolerance` (default 1). The other countries take the rest. Gas is not affected, because gas
certificates already follow the pipelines.

**Example.** Austria upgrades 1 TWh of biogas, which is burned in German gas boilers.
Under `technology`, Austria books −0.198 Mt and Germany +0.198 Mt. Under `carrier`,
Austria books 0 and Germany books 0.198 Mt for burning the gas and −0.198 Mt for claiming
its green certificates, so 0 in total. Germany can only make that claim because the gas
physically flowed from Austria to Germany.

See [Carbon Accounting Methods](carbon-accounting-spec.md) for the full specification.

