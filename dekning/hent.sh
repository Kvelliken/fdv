#!/usr/bin/env bash
# Henter grunnlaget for dekningsanalysen fra SSB og fryser det i dekning/grunnlag/.
# Kjør fra hvor som helst: bash dekning/hent.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p grunnlag

B=https://data.ssb.no/api/pxwebapi/v2/tables
AAR="${AAR:-2023,2024,2025}"

hent() {
  local ut=$1; shift
  curl -sS --fail -m 180 -G "$@" \
    --data-urlencode "lang=no" --data-urlencode "outputFormat=json-stat2" \
    -o "grunnlag/$ut" -w "$ut %{http_code} %{size_download} byte\n"
}

# 11906 Areal for kommunale formålsbygg, etter eieform og funksjon
hent areal.json "$B/11906/data" \
  --data-urlencode "valueCodes[KOKeieform0000]=*" --data-urlencode "valueCodes[KOKfunksjon0000]=*" \
  --data-urlencode "valueCodes[KOKkommuneregion0000]=*" --data-urlencode "valueCodes[ContentsCode]=*" \
  --data-urlencode "valueCodes[Tid]=$AAR"

# 14522 Barn i barnehager 0-6 år, alle eierforhold og kommunale
hent bhg.json "$B/14522/data" \
  --data-urlencode "valueCodes[KOKalder0000]=F000-006" --data-urlencode "valueCodes[KOKeierforhold0000]=0,1" \
  --data-urlencode "valueCodes[KOKoppholdstid0000]=0000" --data-urlencode "valueCodes[KOKkommuneregion0000]=*" \
  --data-urlencode "valueCodes[ContentsCode]=KOSbhgbarn0000" --data-urlencode "valueCodes[Tid]=$AAR"

# 11971 Elever i kommunale grunnskoler
hent elev.json "$B/11971/data" \
  --data-urlencode "valueCodes[KOKkommuneregion0000]=*" \
  --data-urlencode "valueCodes[ContentsCode]=KOSelevgrsk0000,KOSskolergrsk0000" --data-urlencode "valueCodes[Tid]=$AAR"

# 11875 Plasser i helse- og omsorgsinstitusjoner
hent inst.json "$B/11875/data" \
  --data-urlencode "valueCodes[KOKkommuneregion0000]=*" \
  --data-urlencode "valueCodes[ContentsCode]=KOSinstdispplass0000,KOSinstkomplasse0000" --data-urlencode "valueCodes[Tid]=$AAR"

# 14746 Framskrevet folkemengde 2026-2050, funksjonelle aldersgrupper, tre alternativer
hent fram.json "$B/14746/data" \
  --data-urlencode "valueCodes[Region]=*" --data-urlencode "codelist[Alder]=agg_Funksjonell4" \
  --data-urlencode "valueCodes[Alder]=*" --data-urlencode "outputValues[Alder]=aggregated" \
  --data-urlencode "valueCodes[ContentsCode]=Personer,Personer1,Personer2" --data-urlencode "valueCodes[Tid]=*"

# Klass 112 KOSTRA-grupper koblet til kommuner (Klass 131)
DATO="${KLASS_DATO:-$(date +%Y)-06-01}"
curl -sS --fail -m 60 -H "Accept: application/json" \
  "https://data.ssb.no/api/klass/v1/classifications/112/correspondsAt?targetClassificationId=131&date=$DATO" \
  -o grunnlag/klass.json -w "klass.json %{http_code} %{size_download} byte\n"

date +%Y-%m-%d > grunnlag/HENTET
