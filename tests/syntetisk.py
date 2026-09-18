"""Syntetisk KOSTRA-grunnlag for tester og lokal forhåndsvisning.

Tallene er oppdiktede. De skal aldri publiseres. Formålet er at hele kjeden
fra json-stat2 til normtall.json kan kjøres uten nett, og at de kjente
feilmodusene i KOSTRA-data faktisk finnes i testgrunnlaget: manglende areal,
kostnad ført på tjenestefunksjon, foretak utenfor sektorvalget, en kommune med
et stort takarbeid, og en kommune med urimelig lav kWh/m².
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

FUNKSJONER = ["130", "221", "222", "261", "381", "386"]
ENERGIVARER = [
    ("01", "Elektrisitet"),
    ("02", "Fjernvarme"),
    ("03", "Olje og parafin"),
    ("04", "Bioenergi"),
]

# Nivåer per funksjon: (drift kr/m², vedlikehold kr/m², kWh/m²)
NIVAA = {
    "130": (620, 110, 180),
    "221": (700, 120, 190),
    "222": (640, 130, 160),
    "261": (900, 150, 260),
    "381": (580, 140, 230),
    "386": (560, 120, 170),
}


def _datasett(
    dimensjoner: Sequence[tuple[str, str, Sequence[tuple[str, str]]]],
    verdi_for: Any,
) -> dict[str, Any]:
    """Bygger et json-stat2-datasett med dense verdiliste i radmajor rekkefølge."""
    ider = [d[0] for d in dimensjoner]
    storrelser = [len(d[2]) for d in dimensjoner]
    dimensjon: dict[str, Any] = {}
    for kode, etikett, verdier in dimensjoner:
        dimensjon[kode] = {
            "label": etikett,
            "category": {
                "index": {k: i for i, (k, _) in enumerate(verdier)},
                "label": {k: t for k, t in verdier},
            },
        }
    antall = math.prod(storrelser)
    verdier: list[float | None] = []
    for i in range(antall):
        koder = {}
        rest = i
        for d in range(len(ider) - 1, -1, -1):
            pos = rest % storrelser[d]
            rest //= storrelser[d]
            koder[ider[d]] = dimensjoner[d][2][pos][0]
        verdier.append(verdi_for(koder))
    return {
        "class": "dataset",
        "id": ider,
        "size": storrelser,
        "dimension": dimensjon,
        "value": verdier,
    }


def lag_grunnlag(aar: int, antall_kommuner: int = 350, fro: int = 42) -> dict[str, Any]:
    rng = random.Random(fro + aar)
    kommuner = [(f"K-{1000 + i}", f"Testkommune {i:02d}") for i in range(antall_kommuner)]
    # Regionsdimensjonen inneholder også aggregater. De skal filtreres bort av
    # uttrekket, og ligger derfor med i testgrunnlaget.
    kommuner += [("EAK", "Landet"), ("EKG05", "KOSTRA-gruppe 05")]
    vekst = 1.03 ** (aar - 2021)  # nominell prisvekst i testgrunnlaget

    # Per kommune og funksjon: areal og kostnadsnivå
    areal: dict[tuple[str, str], float | None] = {}
    drift: dict[tuple[str, str], float | None] = {}
    vedlikehold: dict[tuple[str, str], float | None] = {}
    renhold: dict[tuple[str, str], float | None] = {}
    energikr: dict[tuple[str, str], float | None] = {}
    kwh: dict[tuple[str, str, str], float | None] = {}

    for indeks, (kode, _) in enumerate(kommuner):
        # Kommunen har et vedvarende nivå over år, slik virkelige kommuner har.
        # Uten det ville panelserien vært like støyete som nivåserien, og
        # panelkravet hadde ikke gitt mening.
        fast = random.Random(fro * 1000 + indeks)
        aarlig = random.Random(fro * 1000 + indeks * 101 + aar)
        storrelse = math.exp(fast.gauss(math.log(9000), 0.7))
        for funksjon in FUNKSJONER:
            nivaa_drift, nivaa_vedl, nivaa_kwh = NIVAA[funksjon]
            a = storrelse * fast.uniform(0.4, 1.6)
            d = nivaa_drift * math.exp(fast.gauss(0.0, 0.22) + aarlig.gauss(0.0, 0.05)) * vekst
            # Vedlikehold er periodisk: stor årsvariasjon rundt kommunens nivå.
            v = nivaa_vedl * math.exp(fast.gauss(0.0, 0.35) + aarlig.gauss(0.0, 0.60)) * vekst
            k = nivaa_kwh * math.exp(fast.gauss(0.0, 0.18) + aarlig.gauss(0.0, 0.07))
            paaslag_delposter = 1.0

            # Kjente feilmoduser, plantet bevisst:
            if indeks % 23 == 0:
                a = None                      # areal ikke rapportert
            elif (indeks + aar) % 47 == 0:
                a = None                      # rapporterte ikke akkurat dette året
            elif indeks % 29 == 0:
                d = d * 0.01                  # kostnaden ført på tjenestefunksjonen
            elif indeks % 31 == 0:
                v = -abs(v)                   # negativ vedlikeholdspost
            elif indeks % 37 == 0:
                v = v * 9                     # stort takarbeid, ekte høyhale
            elif indeks % 41 == 0:
                k = k * 0.15                  # urimelig lav kWh/m²
            elif indeks % 43 == 0:
                paaslag_delposter = 2.2       # delposter større enn drift

            e = d * rng.uniform(0.22, 0.34)
            r = d * rng.uniform(0.20, 0.30)
            if paaslag_delposter > 1.0:
                # Delpostene skaleres slik at restposten garantert blir negativ.
                skala = 1.25 * d / (e + r)
                e, r = e * skala, r * skala

            areal[(kode, funksjon)] = None if a is None else round(a, 1)
            if a:
                drift[(kode, funksjon)] = d * a / 1000.0            # 1000 kr
                vedlikehold[(kode, funksjon)] = v * a / 1000.0
                renhold[(kode, funksjon)] = r * a / 1000.0
                energikr[(kode, funksjon)] = e * a / 1000.0
                samlet_kwh = k * a / 1000.0                         # MWh
                andeler = {"01": 0.72, "02": 0.16, "03": 0.04, "04": 0.08}
                if indeks % 7 == 0:
                    andeler = {"01": 0.55, "02": 0.34, "03": 0.02, "04": 0.09}
                for vare, andel in andeler.items():
                    kwh[(kode, funksjon, vare)] = samlet_kwh * andel
            else:
                for nokkel in (drift, vedlikehold, renhold, energikr):
                    nokkel[(kode, funksjon)] = None
                for vare, _ in ENERGIVARER:
                    kwh[(kode, funksjon, vare)] = None

    forvaltning = {}
    for kode, _ in kommuner:
        samlet_areal = sum(
            areal[(kode, f)] or 0.0 for f in FUNKSJONER
        )
        forvaltning[kode] = samlet_areal * rng.uniform(25, 60) * vekst / 1000.0  # 1000 kr

    kommunedim = ("Region", "region", kommuner)
    funksjonsdim = ("KOSTRAFunksjon", "funksjon", [(f, f) for f in FUNKSJONER])
    tidsdim = ("Tid", "år", [(str(aar), str(aar))])
    sektordim = ("Sektor", "sektor", [("EKG", "Kommunekonsern")])

    artdim = (
        "ArtGrupperingKostra",
        "art",
        [
            ("AGD39", "Utgifter til driftsaktiviteter"),
            ("AGD36", "Utgifter til vedlikeholdsaktiviteter"),
            ("AGD38", "Utgifter til renholdsaktiviteter"),
            ("AGD37", "Utgifter til energi"),
        ],
    )
    kildepost = {"AGD39": drift, "AGD36": vedlikehold, "AGD38": renhold, "AGD37": energikr}

    kostnad = _datasett(
        [kommunedim, funksjonsdim, artdim, sektordim,
         ("ContentsCode", "statistikkvariabel", [("KOSbelop0000", "Beløp (1000 kr)")]), tidsdim],
        lambda k: kildepost[k["ArtGrupperingKostra"]].get((k["Region"], k["KOSTRAFunksjon"])),
    )

    # Forvaltning ligger i en egen tabell, med korrigerte brutto
    # driftsutgifter som art.
    forvaltningsdata = _datasett(
        [kommunedim, ("KOSTRAFunksjon", "funksjon", [("121", "121")]),
         ("ArtGrupperingKostra", "art",
          [("AGD4", "Korrigerte brutto driftsutgifter på funksjon/tjenesteområde")]),
         sektordim,
         ("ContentsCode", "statistikkvariabel", [("KOSbelop0000", "Beløp (1000 kr)")]), tidsdim],
        lambda k: forvaltning.get(k["Region"]),
    )

    arealdata = _datasett(
        [kommunedim, funksjonsdim,
         ("Eieform", "eieform", [("EID", "Eid areal")]),
         ("ContentsCode", "statistikkvariabel", [("Areal", "Areal (m2)")]), tidsdim],
        lambda k: areal.get((k["Region"], k["KOSTRAFunksjon"])),
    )

    energidata = _datasett(
        [kommunedim, funksjonsdim,
         ("EnergiType", "energitype", ENERGIVARER),
         ("ContentsCode", "statistikkvariabel", [("Energibruk", "Energibruk (MWh)")]), tidsdim],
        lambda k: kwh.get((k["Region"], k["KOSTRAFunksjon"], k["EnergiType"])),
    )

    kodevalg = [
        {"formaal": "sektor", "dimensjon": "Sektor", "kode": "EKG", "tekst": "Kommunekonsern", "kilde": "automatisk"},
        {"formaal": "art:drift", "dimensjon": "ArtGrupperingKostra", "kode": "AGD39", "tekst": "Utgifter til driftsaktiviteter", "kilde": "automatisk"},
        {"formaal": "art:vedlikehold", "dimensjon": "ArtGrupperingKostra", "kode": "AGD36", "tekst": "Utgifter til vedlikeholdsaktiviteter", "kilde": "automatisk"},
        {"formaal": "art:renhold", "dimensjon": "ArtGrupperingKostra", "kode": "AGD38", "tekst": "Utgifter til renholdsaktiviteter", "kilde": "automatisk"},
        {"formaal": "art:energi", "dimensjon": "ArtGrupperingKostra", "kode": "AGD37", "tekst": "Utgifter til energi", "kilde": "automatisk"},
        {"formaal": "art:forvaltning", "dimensjon": "ArtGrupperingKostra", "kode": "AGD4", "tekst": "Korrigerte brutto driftsutgifter på funksjon/tjenesteområde", "kilde": "automatisk"},
        {"formaal": "eieform", "dimensjon": "Eieform", "kode": "EID", "tekst": "Eid areal", "kilde": "automatisk"},
        {"formaal": "contents:energibruk", "dimensjon": "ContentsCode", "kode": "Energibruk", "tekst": "Energibruk (MWh)", "kilde": "automatisk"},
    ]

    return {
        "kostnad": kostnad,
        "forvaltning": forvaltningsdata,
        "areal": arealdata,
        "energi": energidata,
        "kodevalg": kodevalg,
    }


def frys_syntetisk(rot: Path, aargang: Iterable[int], antall_kommuner: int = 350) -> list[int]:
    """Skriver syntetisk grunnlag til data/grunnlag/<år>/ under `rot`."""
    from kostra_fdv import utdata

    ut = []
    for aar in aargang:
        grunnlag = lag_grunnlag(aar, antall_kommuner)
        for navn in ("kostnad", "forvaltning", "areal", "energi"):
            utdata.frys_grunnlag(rot, aar, navn, grunnlag[navn])
        utdata.frys_grunnlag(rot, aar, "kodevalg", {"kodevalg": grunnlag["kodevalg"]})
        ut.append(aar)
    return ut


def lag_metadata_kostnad() -> dict[str, Any]:
    """Metadata slik PxWebApi returnerer dem, for kodevalgstester."""
    return {
        "title": "12905: Utgifter til forvaltning, drift og vedlikehold av utvalgte kommunale formålsbygg",
        "variables": [
            {"code": "Region", "text": "region", "values": ["K-1000"], "valueTexts": ["Testkommune"]},
            {
                "code": "KOSTRAFunksjon",
                "text": "funksjon",
                "values": FUNKSJONER,
                "valueTexts": FUNKSJONER,
            },
            {
                "code": "ArtGrupperingKostra",
                "text": "art",
                "values": ["AGD39", "AGD36", "AGD38", "AGD37", "AGD4"],
                "valueTexts": [
                    "Utgifter til driftsaktiviteter",
                    "Utgifter til vedlikeholdsaktiviteter",
                    "Utgifter til renholdsaktiviteter",
                    "Utgifter til energi",
                    "Forvaltningsutgifter i eiendomsforvaltning",
                ],
            },
            {
                "code": "Sektor",
                "text": "sektor",
                "values": ["EKA", "EKG", "EKK"],
                "valueTexts": ["Kommune", "Kommunekonsern", "Kommunekasse"],
            },
            {
                "code": "ContentsCode",
                "text": "statistikkvariabel",
                "values": ["KOSbelop0000", "KOSbelopperkvm0000"],
                "valueTexts": ["Beløp (1000 kr)", "Utgifter per kvadratmeter bygg (kr)"],
            },
            {"code": "Tid", "text": "år", "values": ["2021", "2022", "2023", "2024", "2025"], "valueTexts": ["2021", "2022", "2023", "2024", "2025"]},
        ],
    }
