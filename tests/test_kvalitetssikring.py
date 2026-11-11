"""Kvalitetssikring av beregningen, uten nett.

Tre typer tester:

* Enhetstester for feilene som ble funnet i gjennomgangen november 2026:
  kommunenummer som skiftet i 2024, forvaltning som ble regnet inn som null,
  og delposter som ikke summerte etter avrunding.
* Avstemming av det frosne grunnlaget mot landsaggregatet som ligger i de
  samme filene. Dette er den blokkerende avstemmingen fra `test_nett.py`,
  men kjørt på det som faktisk er publisert, ved hver push.
* Uavhengig etterregning: publiserte normtall regnes på nytt fra
  revisjonsfilene med en egen, enkel implementasjon.
"""

from __future__ import annotations

import csv
import itertools
import json
import re
import statistics
from pathlib import Path

import pytest

from kostra_fdv import utdata
from kostra_fdv.beregning import Kommunerad, forvaltning_per_kommune
from kostra_fdv.pipeline import _panelnokkel, kommunenummer_overgang

FUNKSJONER = ("130", "221", "222", "261", "381", "386")


# -- Kommunenummer ----------------------------------------------------------


ETIKETTER = {
    "0301": "Oslo - Oslove",
    "3001": "Halden (2020-2023)",
    "3101": "Halden",
    "3018": "Våler (Viken) (2020-2023)",
    "3114": "Våler (Østfold)",
    "3419": "Våler (Innlandet)",
    "5412": "Tjeldsund (2020-2023)",
    "5512": "Dielddanuorri - Tjeldsund",
    "5437": "Kárásjohka-Karasjok (2020-2023)",
    "5610": "Kárásjohka - Karasjok",
    "1507": "Ålesund (2020-2023)",
    "1508": "Ålesund",
    "EAK": "Landet",
}


def test_nummerendring_kobles_paa_navn_innenfor_fylkesparene(konfig):
    overgang = kommunenummer_overgang(ETIKETTER, konfig)[2024]
    assert overgang["3001"] == "3101"
    # Parentesen med fylkesnavn skal ikke hindre treff, og Våler i Innlandet
    # skal ikke forveksles med Våler i Østfold.
    assert overgang["3018"] == "3114"
    # Samiske og kvenske parallellnavn kom til i 2024.
    assert overgang["5412"] == "5512"
    assert overgang["5437"] == "5610"


def test_reell_grenseendring_kobles_ikke(konfig):
    """Ålesund 2023 og Ålesund 2024 er ikke samme kommune: Haram ble skilt ut."""
    overgang = kommunenummer_overgang(ETIKETTER, konfig)[2024]
    assert "1507" not in overgang


def test_panelnokkel_gjelder_bare_aar_foer_endringen(konfig):
    overganger = kommunenummer_overgang(ETIKETTER, konfig)
    assert _panelnokkel("3001", 2023, overganger) == "3101"
    assert _panelnokkel("3101", 2024, overganger) == "3101"
    assert _panelnokkel("0301", 2023, overganger) == "0301"


def test_alle_113_kommuner_kobles_i_frosset_grunnlag(konfig, repo_rot):
    sti = repo_rot / "data" / "grunnlag" / "2025" / "areal.json"
    if not sti.exists():
        pytest.skip("Ingen frosset grunnlag")
    ds = json.loads(sti.read_text(encoding="utf-8"))
    etiketter = ds["dimension"]["KOKkommuneregion0000"]["category"]["label"]
    overgang = kommunenummer_overgang(etiketter, konfig)[2024]
    # Viken 51, Vestfold og Telemark 23, Troms og Finnmark 39.
    assert len(overgang) == 113
    assert len(set(overgang.values())) == 113


# -- Forvaltning ------------------------------------------------------------


def _rad(**kw) -> Kommunerad:
    grunn = dict(
        kommune="0001", kommunenavn="Test", aar=2025, funksjon="222", areal=10_000.0,
        portefoljeareal=40_000.0,
        kroner={"drift": 8_000_000.0, "energi": 1_500_000.0, "renhold": 2_500_000.0,
                "vedlikehold": 1_000_000.0},
        forvaltning_kroner=3_200_000.0,
    )
    grunn.update(kw)
    return Kommunerad(**grunn)


def test_forvaltning_null_er_ikke_rapportert_og_gir_ingen_fdv():
    """Null kroner på funksjon 121 er ført et annet sted, ikke gratis."""
    rad = _rad(forvaltning_kroner=0.0)
    rad.beregn_per_m2()
    assert "forvaltning" not in rad.per_m2
    assert "fdv" not in rad.per_m2
    assert rad.per_m2["dv"] == pytest.approx(900.0)


def test_fdv_er_dv_pluss_forvaltning_paa_portefoljeareal():
    rad = _rad()
    rad.beregn_per_m2()
    assert rad.per_m2["forvaltning"] == pytest.approx(80.0)
    assert rad.per_m2["fdv"] == pytest.approx(980.0)


def test_forvaltning_utenfor_kjernen_holdes_ute_av_fdv():
    rad = _rad(forvaltning_i_kjerne=False)
    rad.beregn_per_m2()
    assert "fdv" not in rad.per_m2
    assert rad.per_m2["forvaltning"] == pytest.approx(80.0)


def test_forvaltning_avhenger_ikke_av_areal_i_funksjonen():
    """En kommune uten administrasjonslokaler har fortsatt et forvaltningstall."""
    rad = _rad(funksjon="130", areal=None)
    assert forvaltning_per_kommune([rad]) == {"0001": pytest.approx(80.0)}


# -- Avrunding --------------------------------------------------------------


def test_delposter_summerer_til_avrundet_total():
    deler = {"energi": 151.9, "renhold": 204.9, "ovrig_drift": 421.0, "vedlikehold": 80.5}
    # Hver for seg til nærmeste 5 gir 150 + 205 + 420 + 80 = 855, mot 860.
    assert sum(utdata.avrund_naermeste(v, 5) for v in deler.values()) == 855
    avrundet = utdata.avrund_summerbart(deler, 5)
    assert sum(avrundet.values()) == utdata.avrund_naermeste(sum(deler.values()), 5) == 860
    for post, verdi in deler.items():
        assert abs(avrundet[post] - verdi) < 5


# -- Avstemming av frosset grunnlag -----------------------------------------


def _celler(datasett):
    ider = datasett["id"]
    koder = [
        [k for k, _ in sorted(datasett["dimension"][i]["category"]["index"].items(), key=lambda kv: kv[1])]
        for i in ider
    ]
    for n, kombinasjon in enumerate(itertools.product(*koder)):
        yield dict(zip(ider, kombinasjon)), datasett["value"][n]


def _frosne_aar(rot: Path) -> list[int]:
    katalog = rot / "data" / "grunnlag"
    if not katalog.exists():
        return []
    return sorted(int(p.name) for p in katalog.iterdir() if p.name.isdigit())


def test_frosset_grunnlag_stemmer_med_landsaggregatet(konfig, repo_rot):
    """sum(kommuner) mot «Landet» i samme fil, for kroner, areal og kWh.

    Feil enhet gir faktor 1000. Aggregater som har sluppet inn i
    kommuneutvalget gir faktor 2 eller mer. Begge fanges her.
    """
    aar_liste = _frosne_aar(repo_rot)
    if not aar_liste:
        pytest.skip("Ingen frosset grunnlag")
    er_kommune = re.compile(konfig["region"]["kommune_monster"]).match
    grense = float(konfig["avstemming"]["toleranse_blokkerende"])
    avvik = []
    for aar in aar_liste:
        for navn in ("kostnad", "areal", "energi"):
            ds = utdata.les_grunnlag(repo_rot, aar, navn)
            reg = next(i for i in ds["id"] if "region" in i.lower())
            fun = next(i for i in ds["id"] if "funksjon" in i.lower())
            andre = [i for i in ds["id"] if i not in (reg, fun)]
            summer: dict[tuple, float] = {}
            land: dict[tuple, float] = {}
            for koder, verdi in _celler(ds):
                if verdi is None:
                    continue
                nokkel = (koder[fun], *(koder[a] for a in andre))
                if er_kommune(koder[reg]):
                    summer[nokkel] = summer.get(nokkel, 0.0) + verdi
                elif koder[reg] == "EAK":
                    land[nokkel] = verdi
            assert land, f"{aar}/{navn}: fant ikke landsaggregatet"
            for nokkel, landsverdi in land.items():
                if not landsverdi or landsverdi < 50_000:
                    continue  # små energivarer: enkeltkommuner dominerer
                forhold = summer.get(nokkel, 0.0) / landsverdi
                if abs(forhold - 1.0) > grense:
                    avvik.append(f"{aar}/{navn}/{nokkel}: sum/land = {forhold:.3f}")
    assert not avvik, "\n".join(avvik)


# -- Uavhengig etterregning --------------------------------------------------


def _kvantil(verdier, p):
    """Egen implementasjon, med vilje ikke den i beregning.py."""
    return statistics.quantiles(verdier, n=100, method="inclusive")[int(p * 100) - 1]


def test_publiserte_normtall_kan_etterregnes_fra_revisjonsfilene(konfig, repo_rot):
    sti = repo_rot / "docs" / "normtall.json"
    if not sti.exists():
        pytest.skip("Ingen publiserte tall")
    normtall = json.loads(sti.read_text(encoding="utf-8"))
    siste = normtall["grunnlag"]["siste_aargang"]
    blokkerende = set(konfig["blokkerende_flagg"])
    for funksjon in FUNKSJONER:
        fil = repo_rot / "data" / "revisjon" / str(siste) / f"{funksjon}.csv"
        with fil.open(encoding="utf-8") as f:
            rader = list(csv.DictReader(f, delimiter=";"))
        dv, fdv = [], []
        for r in rader:
            if set(filter(None, r["flagg_kostnad"].split("|"))) & blokkerende:
                continue
            # Regnet fra kroner og areal, ikke fra den ferdige kr/m²-kolonnen.
            verdi = (float(r["drift_kr"]) + float(r["vedlikehold_kr"])) / float(r["eid_areal_m2"])
            dv.append(verdi)
            if r["fdv_kr_m2"]:
                fdv.append(verdi + float(r["forvaltning_kr"]) / float(r["portefoljeareal_m2"]))
        publisert = normtall["funksjoner"][funksjon]["kostnad"]
        assert len(dv) == publisert["n_kjerne"]
        for navn, verdier in (("dv", dv), ("fdv", fdv)):
            punkt = publisert["normtall_forankret"][navn]
            assert punkt["lav"]["verdi"] == pytest.approx(_kvantil(verdier, 0.10), rel=1e-9)
            assert punkt["sannsynlig"]["verdi"] == pytest.approx(statistics.median(verdier), rel=1e-9)
            assert punkt["hoy"]["verdi"] == pytest.approx(_kvantil(verdier, 0.90), rel=1e-9)

        # Budsjettabellen skal gå opp, både uavrundet og avrundet.
        deler = ("energi", "renhold", "ovrig_drift", "vedlikehold")
        for nivaa in ("lav", "sannsynlig", "hoy"):
            f = publisert["normtall_forankret"]
            assert sum(f[p][nivaa]["verdi"] for p in deler) == pytest.approx(f["dv"][nivaa]["verdi"])
            assert sum(f[p][nivaa]["verdi_avrundet"] for p in deler) == f["dv"][nivaa]["verdi_avrundet"]


def test_panelet_mister_ikke_fylkene_som_ble_delt(repo_rot):
    """Vaktpost mot nummerendringen: panelet skal være nær nivåutvalget."""
    sti = repo_rot / "docs" / "normtall.json"
    if not sti.exists():
        pytest.skip("Ingen publiserte tall")
    normtall = json.loads(sti.read_text(encoding="utf-8"))
    for funksjon in ("221", "222", "261"):
        hist = normtall["funksjoner"][funksjon]["kostnad"]["historikk"]["dv"]
        minste_nivaa = min(p["n_kommuner"] for p in hist["nivaaserie"]["punkter"])
        assert hist["n_panel"] > 0.75 * minste_nivaa, (funksjon, hist["n_panel"], minste_nivaa)
