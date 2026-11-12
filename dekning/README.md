# Dekning av kommunale formålsbygg

Estimerer over- og underdekning av areal per kommune for seks bygningstyper,
i dag og framskrevet til 2050. Publiseres som `docs/dekning/` på GitHub Pages.

Dette er en selvstendig del av repoet. Den deler ingen kode med `kostra_fdv`.

## Kjøring

```bash
bash dekning/hent.sh     # henter fra SSB og fryser i dekning/grunnlag/
python dekning/bygg.py   # bygger docs/dekning/index.html, ingen nett
```

`bygg.py` stopper hvis summen av kommunenes areal avviker mer enn 2 % fra SSBs
landstall.

## Metode

| Bygningstype (funksjon) | Brukergrunnlag | Framskrives med |
|---|---|---|
| Barnehagelokaler (221) | Barn i kommunale barnehager | Innbyggere 1–5 år |
| Skolelokaler (222) | Elever i kommunale grunnskoler | Innbyggere 6–15 år |
| Institusjonslokaler (261) | Innbyggere 80 år og eldre | Innbyggere 80+ |
| Administrasjonslokaler (130) | Alle innbyggere | Folketallet |
| Idrettsbygg og idrettsanlegg (381) | Alle innbyggere | Folketallet |
| Kulturbygg (386) | Alle innbyggere | Folketallet |

- Areal er samlet areal (eid og leid) fra KOSTRA. Siste årgang brukes, med 2024 som reserve.
- Referansen er medianen av m² per bruker i kommunens KOSTRA-gruppe, eller i hele landet.
  Oslo (gruppe 13) sammenlignes med gruppe 12 og 13 samlet.
- Behov = brukere × referansens m² per bruker. Dekning = areal ÷ behov.
- Framover holdes arealet fast og brukertallet skaleres med veksten i aldersgruppen.
- Under 90 % er underdekning, over 110 % er overdekning.

Medianen er ikke en norm. Se forbeholdene nederst på siden.

## Kilder (SSB)

- Tabell 11906: Areal for kommunale formålsbygg
- Tabell 14522: Barn i barnehager
- Tabell 11971: Elever i kommunale grunnskoler
- Tabell 11875: Plasser i helse- og omsorgsinstitusjoner
- Tabell 14746: Framskrevet folkemengde 2026–2050
- Klass 112: KOSTRA-grupper
