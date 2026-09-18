"""Skriving av JSON, CSV og frosset grunnlag.

Avrunding skjer kun her, i presentasjonslaget. All mellomregning går i full
presisjon. JSON bærer både `verdi` og `verdi_avrundet`, slik at den som vil
etterprøve et publisert tall kan regne seg tilbake til kroner, kWh og areal.

Andeler, vekstrater og implisitte priser avrundes ikke i JSON. Nettsiden
formaterer prosent med én desimal ved visning.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .beregning import Kommunerad
from .energi import Energirad

MERKING = (
    "Løpende kroner per årgang. Ingen prisjustering. "
    "Grunnlag: KOSTRA {aargang}, revidert utgave."
)

MERKING_FORELOPIG = (
    "Løpende kroner per årgang. Ingen prisjustering. "
    "Grunnlag: KOSTRA {aargang}, FORELØPIG utgave. Foreløpige tall inneholder "
    "imputerte verdier for kommuner som ikke har rapportert."
)

FORBEHOLD = [
    "Tallene er i løpende kroner og ikke prisjustert. Vekst er nominell og "
    "inkluderer generell prisstigning.",
    "Forvaltning er et porteføljetall. Funksjon 121 dekker forvaltning av hele "
    "eiendomsmassen og har ikke eget areal, så leddet er likt for alle "
    "bygningstyper. Dette er en egenskap ved KOSTRA, ikke ved beregningen.",
    "Vedlikehold viser faktisk forbruk, ikke normativt behov. Årlige utslag i "
    "medianen kan skyldes vedlikeholdssyklus framfor prisvekst.",
    "Drift og vedlikehold er rene aktivitetsarter, og inneholder verken "
    "avskrivninger eller merverdiavgift. Forvaltningsleddet er derimot hentet "
    "som korrigerte brutto driftsutgifter på funksjon 121, fordi KOSTRA ikke "
    "publiserer en ren forvaltningsart. Det leddet inneholder avskrivninger og "
    "mva-utgift, og er altså målt på en annen måte enn de øvrige. FDV-summen "
    "er derfor ikke et rent FDV-tall.",
    "Lav og høy for delpostene kan ikke summeres. Bruk det forankrede settet, "
    "som er brutt ned fra spennet for drift og vedlikehold samlet.",
    "Energibruk er ikke temperaturkorrigert. Endring mellom år inneholder også "
    "værvariasjon, og nordlige kommuner ligger systematisk høyere enn sørlige.",
    "Gratisvarme fra varmepumper og solfangere er ikke med, bare elektrisiteten "
    "som driver dem. Tallene er tilført energi, ikke energibehov, og kan ikke "
    "sammenlignes med energikrav i TEK.",
    "Har kommunen eget nærvarmeanlegg, rapporteres innsatsenergien. "
    "Konverteringstapet ligger da inne i kWh-tallet, men ikke for kommuner som "
    "kjøper fjernvarme.",
    "Fordelingen av energibruk mellom formål kan være skjønnsmessig. "
    "Rapporteringsinstruksen ber om anslag der fullstendige opplysninger "
    "mangler, så funksjonssplitten på energi er svakere enn på kostnad.",
]


# -- Avrunding --------------------------------------------------------------


def avrund_naermeste(verdi: float | None, naermeste: int) -> float | None:
    """Avrunder til nærmeste multiplum, halve oppover fra null.

    Python runder 2,5 til 2 (banker's rounding). Her brukes vanlig avrunding,
    slik at 7,5 blir 10 og ikke 5 ved nærmeste 5.
    """
    if verdi is None or (isinstance(verdi, float) and math.isnan(verdi)):
        return None
    tegn = -1 if verdi < 0 else 1
    return tegn * math.floor(abs(verdi) / naermeste + 0.5) * naermeste


def verdipar(verdi: float | None, naermeste: int) -> dict[str, float | None]:
    if verdi is None or (isinstance(verdi, float) and math.isnan(verdi)):
        return {"verdi": None, "verdi_avrundet": None}
    return {"verdi": verdi, "verdi_avrundet": avrund_naermeste(verdi, naermeste)}


def avrund_tre_punkt(punkt: Mapping[str, float], naermeste: int) -> dict[str, Any]:
    return {navn: verdipar(verdi, naermeste) for navn, verdi in punkt.items()}


# -- Frosset grunnlag -------------------------------------------------------


def grunnlagssti(rot: Path, aar: int, navn: str) -> Path:
    return rot / "data" / "grunnlag" / str(aar) / f"{navn}.json"


def frys_grunnlag(rot: Path, aar: int, navn: str, innhold: dict[str, Any]) -> Path:
    """Skriver rått uttrekk til data/grunnlag/<år>/<navn>.json.

    Dette er ikke cache, det er revisjonsspor. SSB reviderer tabeller også
    utenom de faste publiseringsdatoene, og uten frosset grunnlag i git kan
    ingen se om en endring skyldtes ny årgang eller en stille revisjon.
    """
    sti = grunnlagssti(rot, aar, navn)
    sti.parent.mkdir(parents=True, exist_ok=True)
    sti.write_text(json.dumps(innhold, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return sti


def les_grunnlag(rot: Path, aar: int, navn: str) -> dict[str, Any] | None:
    sti = grunnlagssti(rot, aar, navn)
    if not sti.exists():
        return None
    return json.loads(sti.read_text(encoding="utf-8"))


def diff_grunnlag(gammelt: Mapping[str, Any] | None, nytt: Mapping[str, Any]) -> list[str]:
    """Kort tekstlig diff som skrives til jobbloggen før overskriving."""
    if gammelt is None:
        return ["Ingen tidligere frosset versjon."]
    g = json.dumps(gammelt, sort_keys=True, ensure_ascii=False)
    n = json.dumps(nytt, sort_keys=True, ensure_ascii=False)
    if g == n:
        return ["Identisk med frosset versjon."]
    linjer = [f"Endret: {len(g)} tegn -> {len(n)} tegn."]
    g_verdier = gammelt.get("value") or []
    n_verdier = nytt.get("value") or []
    if isinstance(g_verdier, list) and isinstance(n_verdier, list):
        endret = sum(1 for a, b in zip(g_verdier, n_verdier) if a != b)
        linjer.append(
            f"Verdier: {len(g_verdier)} -> {len(n_verdier)}, {endret} celler endret i overlappet."
        )
    return linjer


# -- Revisjonsfil -----------------------------------------------------------


def skriv_revisjonsfil(
    rot: Path,
    aar: int,
    funksjon: str,
    kostnadsrader: Sequence[Kommunerad],
    energirader: Sequence[Energirad] = (),
) -> Path:
    """Per kommune: kroner, kWh, areal og flagg. Ett publisert tall skal kunne
    spores hit, og herfra videre til statistikkbanken."""
    sti = rot / "data" / "revisjon" / str(aar) / f"{funksjon}.csv"
    sti.parent.mkdir(parents=True, exist_ok=True)
    energi_per_kommune = {r.kommune: r for r in energirader}
    felt = [
        "kommune",
        "kommunenavn",
        "aargang",
        "funksjon",
        "eid_areal_m2",
        "portefoljeareal_m2",
        "drift_kr",
        "energi_kr",
        "renhold_kr",
        "vedlikehold_kr",
        "forvaltning_kr",
        "drift_kr_m2",
        "energi_kr_m2",
        "renhold_kr_m2",
        "ovrig_drift_kr_m2",
        "vedlikehold_kr_m2",
        "forvaltning_kr_m2",
        "dv_kr_m2",
        "fdv_kr_m2",
        "energibruk_kwh",
        "kwh_m2",
        "fornybarandel",
        "implisitt_energipris_kr_kwh",
        "flagg_kostnad",
        "flagg_energi",
    ]
    with sti.open("w", newline="", encoding="utf-8") as fil:
        skriver = csv.DictWriter(fil, fieldnames=felt, delimiter=";")
        skriver.writeheader()
        for rad in sorted(kostnadsrader, key=lambda r: r.kommune):
            e = energi_per_kommune.get(rad.kommune)
            skriver.writerow(
                {
                    "kommune": rad.kommune,
                    "kommunenavn": rad.kommunenavn,
                    "aargang": rad.aar,
                    "funksjon": rad.funksjon,
                    "eid_areal_m2": rad.areal,
                    "portefoljeareal_m2": rad.portefoljeareal,
                    "drift_kr": rad.kroner.get("drift"),
                    "energi_kr": rad.kroner.get("energi"),
                    "renhold_kr": rad.kroner.get("renhold"),
                    "vedlikehold_kr": rad.kroner.get("vedlikehold"),
                    "forvaltning_kr": rad.forvaltning_kroner,
                    "drift_kr_m2": rad.per_m2.get("drift"),
                    "energi_kr_m2": rad.per_m2.get("energi"),
                    "renhold_kr_m2": rad.per_m2.get("renhold"),
                    "ovrig_drift_kr_m2": rad.per_m2.get("ovrig_drift"),
                    "vedlikehold_kr_m2": rad.per_m2.get("vedlikehold"),
                    "forvaltning_kr_m2": rad.per_m2.get("forvaltning"),
                    "dv_kr_m2": rad.per_m2.get("dv"),
                    "fdv_kr_m2": rad.per_m2.get("fdv"),
                    "energibruk_kwh": e.sum_kwh if e else None,
                    "kwh_m2": e.kwh_m2 if e else None,
                    "fornybarandel": e.fornybarandel if e else None,
                    "implisitt_energipris_kr_kwh": e.implisitt_pris if e else None,
                    "flagg_kostnad": "|".join(rad.flagg),
                    "flagg_energi": "|".join(e.flagg) if e else "",
                }
            )
    return sti


# -- normtall.json ----------------------------------------------------------


def bygg_normtall(
    konfig: Mapping[str, Any],
    aargang_frosne: Sequence[int],
    aargang_vist: Sequence[int],
    kodevalg: Sequence[Mapping[str, Any]],
    funksjoner: Mapping[str, Any],
    datakvalitet: Mapping[str, Any],
    forelopig: bool = False,
    generert: dt.datetime | None = None,
) -> dict[str, Any]:
    siste = max(aargang_vist)
    mal = MERKING_FORELOPIG if forelopig else MERKING
    return {
        "skjemaversjon": 1,
        "generert": (generert or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds"),
        "grunnlag": {
            "kilde": "SSB statistikkbanken, KOSTRA",
            "tabeller": dict(konfig["tabeller"]),
            "aargang_frosne": list(aargang_frosne),
            "aargang_vist": list(aargang_vist),
            "siste_aargang": siste,
            "utgave": "forelopig" if forelopig else "revidert",
            "prisjustering": "ingen",
            "enheter": dict(konfig["enheter"]),
        },
        "merking": mal.format(aargang=siste),
        "kodevalg": [dict(k) for k in kodevalg],
        "terskler": dict(konfig["terskler"]),
        "brudd": list(konfig.get("brudd") or []),
        "funksjoner": dict(funksjoner),
        "datakvalitet": dict(datakvalitet),
        "forbehold": FORBEHOLD,
    }


def skriv_json(sti: Path, innhold: Mapping[str, Any]) -> Path:
    sti.parent.mkdir(parents=True, exist_ok=True)
    sti.write_text(json.dumps(innhold, ensure_ascii=False, indent=1), encoding="utf-8")
    return sti


def kopier_revisjonsfiler(rot: Path) -> list[Path]:
    """Legger revisjonsfilene under docs/ så de kan lastes ned fra nettsiden.

    GitHub Pages serverer bare docs/, så filene må ligge der. Kilden i
    data/revisjon/ er fortsatt den versjonerte originalen.
    """
    import shutil

    kilde = rot / "data" / "revisjon"
    mal = rot / "docs" / "nedlasting"
    if mal.exists():
        shutil.rmtree(mal)
    if not kilde.exists():
        return []
    shutil.copytree(kilde, mal)
    return sorted(mal.rglob("*.csv"))


def publiser(rot: Path, normtall: Mapping[str, Any]) -> list[Path]:
    """Skriver normtall.json til data/publisert og til docs/, med revisjonsfiler."""
    stier = [
        skriv_json(rot / "data" / "publisert" / "normtall.json", normtall),
        skriv_json(rot / "docs" / "normtall.json", normtall),
    ]
    stier += kopier_revisjonsfiler(rot)
    return stier
