# kostra-fdv

FDV-normtall og energibruk per kvadratmeter for kommunale formålsbygg, regnet
fra KOSTRA og publisert som en statisk nettside via GitHub Pages.

Alt er reproduserbart. Hvert publiserte tall kan spores tilbake til et
kronebeløp, et kWh-tall og et areal i statistikkbanken. Metoden er dokumentert
i [METODE.md](METODE.md).

## Kom i gang

```bash
pip install -e ".[test]"
pytest -q                                  # 81 tester, ingen nett
python -m kostra_fdv.cli hent --aargang alle
KOSTRA_NETT=1 pytest tests/test_nett.py -q  # blokkerende avstemming
python -m kostra_fdv.cli beregn
```

`hent` henter og fryser de fem siste **reviderte** årgangene under
`data/grunnlag/<år>/`. `beregn` leser det frosne grunnlaget, skriver
revisjonsfiler per kommune og bygger `docs/normtall.json`, som nettsiden leser.

Første gang bør du lese jobbloggen fra `hent`. Den skriver ut hvilke verdikoder
den fant, og om valget var automatisk eller overstyrt.

## Struktur

```
config.yaml              alle terskler, tabeller, søkemønstre og brudd
src/kostra_fdv/
  ssb_api.py             metadata, uttrekk, json-stat2-parsing
  kodevalg.py            kodegjenkjenning, sektorvakt, årgangsvalg
  beregning.py           kr/m², flagg, log-Tukey, tre-punktsmodell
  energi.py              kWh/m², energivarer, implisitt pris
  historikk.py           nivåserie, balansert panel, vekstrater, brudd
  utdata.py              JSON, CSV, avrunding, frosset grunnlag
  pipeline.py            kjeden fra uttrekk til normtall
  cli.py                 kommandolinje
data/grunnlag/<år>/      frosset KOSTRA-grunnlag, versjonert
data/revisjon/<år>/      per kommune: kroner, kWh, areal, flagg
docs/                    GitHub Pages
tests/                   enhetstester, syntetisk grunnlag, nett-tester
```

## Workflows

| Fil | Når | Hva |
|---|---|---|
| `test.yml` | hver push | tester, og sjekk mot hardkodede verdikoder |
| `manedlig.yml` | den 5. hver måned | endringsdetektor: ny eller stille revidert årgang |
| `grunnlag.yml` | manuelt | full henting, blokkerende avstemming, publisering |

`manedlig.yml` er en detektor, ikke en beregningsjobb. Uten indeksjustering er
det ingenting å regne på mellom KOSTRA-publiseringene, så de fleste kjøringene
ender uten commit. Det er forventet.

## Fem ting som er lette å gjøre feil

1. **Summere energi + renhold + drift.** Drift inneholder de to andre. Bare
   drift og vedlikehold kan summeres.
2. **Bruke kommunekasse i stedet for kommunekonsern.** Da får du en teller uten
   foretak delt på et areal med foretak, og verdier som 7 kr/m². Jobben feiler
   hardt hvis sektordimensjonen er uavklart.
3. **Bruke marspubliseringen.** Den inneholder imputerte verdier som ser
   normale ut og passerer alle kvalitetsfiltre.
4. **Regne vekstrater på nivåserien.** Da blander du prisvekst med
   sammensetningsendring. Feilen gir ingen feilmelding, bare et litt galt tall,
   så den er testdekket.
5. **Summere delpostenes lav og høy.** Delpostene er nesten ukorrelerte, så
   summen av P10 blir for lav og summen av P90 for høy. Bruk det forankrede
   settet.

## Lisens og kilde

Tallene er hentet fra Statistisk sentralbyrå. Kildehenvisning skal følge med
ved videre bruk.
