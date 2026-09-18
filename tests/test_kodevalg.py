"""json-stat2-parsing, kodegjenkjenning, sektorvakt og årgangsvalg."""

from __future__ import annotations

import datetime as dt

import pytest
import syntetisk

from kostra_fdv.kodevalg import (
    KodevalgFeil,
    SektorFeil,
    er_forelopig,
    finn_arter,
    finn_kode,
    revidert_aargang_tilgjengelig,
    sektorvakt,
    velg_aargang,
)
from kostra_fdv.ssb_api import lag_sporring, parse_jsonstat2


# -- json-stat2 -------------------------------------------------------------


def test_parser_radmajor_rekkefolge():
    datasett = {
        "class": "dataset",
        "id": ["A", "B"],
        "size": [2, 3],
        "dimension": {
            "A": {"category": {"index": {"a1": 0, "a2": 1}, "label": {"a1": "A1", "a2": "A2"}}},
            "B": {"category": {"index": {"b1": 0, "b2": 1, "b3": 2}}},
        },
        "value": [1, 2, 3, 4, 5, 6],
    }
    rader = parse_jsonstat2(datasett)
    assert len(rader) == 6
    assert rader[0].koder == {"A": "a1", "B": "b1"} and rader[0].verdi == 1
    assert rader[3].koder == {"A": "a2", "B": "b1"} and rader[3].verdi == 4
    assert rader[0].etiketter["A"] == "A1"
    assert rader[0].etiketter["B"] == "b1"  # faller tilbake til koden


def test_parser_haandterer_sparse_verdier_og_status():
    datasett = {
        "class": "dataset",
        "id": ["A"],
        "size": [3],
        "dimension": {"A": {"category": {"index": {"a": 0, "b": 1, "c": 2}}}},
        "value": {"0": 10, "2": 30},
        "status": {"1": ":"},
    }
    rader = parse_jsonstat2(datasett)
    assert [r.verdi for r in rader] == [10.0, None, 30.0]
    assert rader[1].status == ":"


def test_parser_krever_komplett_datasett():
    with pytest.raises(Exception):
        parse_jsonstat2({"class": "dataset", "id": ["A"], "size": [1]})


def test_sporring_bruker_stjernefilter_for_alle_verdier():
    sporring = lag_sporring({"Region": [], "Tid": ["2024"]})
    valg = {d["code"]: d["selection"] for d in sporring["query"]}
    assert valg["Region"] == {"filter": "all", "values": ["*"]}
    assert valg["Tid"] == {"filter": "item", "values": ["2024"]}
    assert sporring["response"]["format"] == "json-stat2"


# -- Kodevalg ---------------------------------------------------------------


def test_finner_artskoder_automatisk(konfig):
    metadata = syntetisk.lag_metadata_kostnad()
    arter = finn_arter(metadata, konfig, ["drift", "vedlikehold", "renhold", "energi"])
    assert arter["drift"].kode == "AGD39"
    assert arter["vedlikehold"].kode == "AGD36"
    assert arter["renhold"].kode == "AGD38"
    assert all(v.kilde == "automatisk" for v in arter.values())


def test_overstyring_merkes_som_overstyrt(konfig):
    metadata = syntetisk.lag_metadata_kostnad()
    valg = finn_kode(metadata, "art:drift", konfig["kodesok"]["art"]["drift"], "AGD36")
    assert valg.kode == "AGD36"
    assert valg.kilde == "overstyrt"


def test_ukjent_overstyring_gir_feil_med_gyldige_koder(konfig):
    metadata = syntetisk.lag_metadata_kostnad()
    with pytest.raises(KodevalgFeil) as feil:
        finn_kode(metadata, "art:drift", konfig["kodesok"]["art"]["drift"], "FINNES_IKKE")
    assert "AGD39" in str(feil.value)


def test_flertydig_treff_stopper_jobben(konfig):
    metadata = syntetisk.lag_metadata_kostnad()
    regel = {"dimensjon_krev": ["art"], "krev": ["utgifter"], "unnta": []}
    with pytest.raises(KodevalgFeil):
        finn_kode(metadata, "art:drift", regel)


def test_sektorvakt_finner_konsern(konfig):
    valg = sektorvakt(syntetisk.lag_metadata_kostnad(), konfig)
    assert valg.kode == "EKG"
    assert "konsern" in valg.tekst.lower()


def test_uavklart_sektor_gir_hard_feil_med_liste_over_gyldige_koder(konfig):
    metadata = syntetisk.lag_metadata_kostnad()
    for variabel in metadata["variables"]:
        if variabel["code"] == "Sektor":
            variabel["values"] = ["EKA", "EKK"]
            variabel["valueTexts"] = ["Kommune", "Kommunekasse"]
    with pytest.raises(SektorFeil) as feil:
        sektorvakt(metadata, konfig)
    tekst = str(feil.value)
    assert "EKA" in tekst and "EKK" in tekst
    assert "summerer aldri over sektor" in tekst


# -- Årgangsvalg ------------------------------------------------------------


@pytest.mark.parametrize(
    "dato,forventet",
    [
        (dt.date(2026, 3, 16), 2024),   # foreløpige 2025-tall finnes, men brukes ikke
        (dt.date(2026, 6, 14), 2024),
        (dt.date(2026, 6, 15), 2025),   # revidert årgang publisert
        (dt.date(2026, 12, 31), 2025),
    ],
)
def test_revidert_aargang_folger_15_juni(konfig, dato, forventet):
    assert revidert_aargang_tilgjengelig(dato, konfig) == forventet


def test_velger_fem_siste_reviderte_aargang(konfig):
    tilgjengelig = [str(a) for a in range(2015, 2026)]
    valgte = velg_aargang(tilgjengelig, dt.date(2026, 9, 17), konfig)
    assert valgte == [2021, 2022, 2023, 2024, 2025]


def test_forelopig_aargang_holdes_utenfor(konfig):
    tilgjengelig = [str(a) for a in range(2015, 2026)]
    valgte = velg_aargang(tilgjengelig, dt.date(2026, 4, 1), konfig)
    assert 2025 not in valgte
    assert valgte[-1] == 2024
    assert er_forelopig(2025, dt.date(2026, 4, 1), konfig)


def test_tillat_forelopig_tar_med_nyeste(konfig):
    tilgjengelig = [str(a) for a in range(2015, 2026)]
    valgte = velg_aargang(tilgjengelig, dt.date(2026, 4, 1), konfig, tillat_forelopig=True)
    assert valgte[-1] == 2025


def test_manglende_sektordimensjon_er_ikke_det_samme_som_uavklart(konfig):
    """Tabell 12905 har ingen sektordimensjon: sektoren ligger i definisjonen."""
    import copy

    metadata = syntetisk.lag_metadata_kostnad()
    metadata["variables"] = [v for v in metadata["variables"] if v["code"] != "Sektor"]

    valg = sektorvakt(metadata, konfig)
    assert valg.kilde == "ikke_aktuell"
    assert valg.dimensjon == ""
    assert "konserntall" in valg.tekst

    # Uten den eksplisitte tillatelsen i config skal jobben fortsatt stoppe.
    streng = copy.deepcopy(konfig)
    streng["kodesok"]["sektor"]["tillat_manglende_dimensjon"] = False
    with pytest.raises(SektorFeil, match="ingen sektordimensjon"):
        sektorvakt(metadata, streng)


def test_skiller_belop_fra_ssbs_ferdigberegnede_kr_per_m2(konfig):
    """Tabellen har to kronevariabler. Vi skal ha beløpet, ikke kr/m²-tallet.

    SSBs egen kr/m²-indikator har en nevner vi ikke kontrollerer. Regner vi
    selv mot eid areal, kan hvert publiserte tall spores tilbake.
    """
    metadata = syntetisk.lag_metadata_kostnad()
    valg = finn_kode(metadata, "contents:kroner", konfig["kodesok"]["kroner"])
    assert valg.kode == "KOSbelop0000"
    assert "1000 kr" in valg.tekst
