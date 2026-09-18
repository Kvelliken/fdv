"""Kodevalg mot metadata som speiler de faktiske tabellene.

Metadataene her er skrevet av etter loggen fra de første kjøringene mot SSB, og
tar vare på det vi lærte da. Hver av dem inneholdt en overraskelse:

* 12905 har ingen sektordimensjon. Sektoren ligger i tabellens definisjon.
* Energiarten heter AG1 og følger ikke AGD-serien.
* Renholdsarten heter «renholdsaktiviteter», ikke «renhold».
* Kostnadstabellen har to kronevariabler: beløpet og SSBs ferdigberegnede
  kr/m². Vi skal ha beløpet.
* 12367 har en regnskapsomfang-dimensjon, ikke en sektordimensjon.
* Energitabellen har både ukorrigert og temperaturkorrigert energibruk.

Testene kjører uten nett. De erstatter ikke `test_nett.py`, men de fanger opp
at et søkemønster endres slik at det ikke lenger treffer det vi vet finnes.
"""

from __future__ import annotations

import pytest

from kostra_fdv.kodevalg import finn_arter, finn_kode, sektorvakt
from kostra_fdv.pipeline import velg_entydig_contents


def _overstyring(konfig, navn):
    return (konfig.get("overstyring") or {}).get(navn)


@pytest.fixture
def meta_12905():
    """Utgifter til FDV av utvalgte kommunale formålsbygg."""
    return {
        "title": "12905: Utgifter til forvaltning, drift og vedlikehold av formålsbygg",
        "variables": [
            {
                "code": "KOKkommuneregion0000",
                "text": "region",
                "values": ["K-3001", "EAK", "EAKUO"],
                "valueTexts": ["Halden", "Landet", "Landet uten Oslo"],
            },
            {
                "code": "KOKfunksjon0000",
                "text": "funksjon",
                "values": ["121", "130", "221", "222", "261", "381", "386"],
                "valueTexts": ["121", "130", "221", "222", "261", "381", "386"],
            },
            {
                "code": "KOKart0000",
                "text": "art",
                "values": ["AGD39", "AGD36", "AGD38", "AG1"],
                "valueTexts": [
                    "Utgifter til driftsaktiviteter",
                    "Utgifter til vedlikeholdsaktiviteter",
                    "Utgifter til renholdsaktiviteter",
                    "Energiutgifter",
                ],
            },
            {
                "code": "ContentsCode",
                "text": "statistikkvariabel",
                "values": ["KOSbelop0000", "KOSbelopperkvm0000"],
                "valueTexts": ["Beløp (1000 kr)", "Utgifter per kvadratmeter bygg (kr)"],
            },
            {
                "code": "Tid",
                "text": "år",
                "values": ["2021", "2022", "2023", "2024", "2025"],
                "valueTexts": ["2021", "2022", "2023", "2024", "2025"],
            },
        ],
    }


@pytest.fixture
def meta_12367():
    """Forvaltningsutgifter, funksjon 121. To arter inneholder «korrigerte brutto»."""
    return {
        "title": "12367",
        "variables": [
            {
                "code": "KOKkommuneregion0000",
                "text": "region",
                "values": ["K-3001", "EAK"],
                "valueTexts": ["Halden", "Landet"],
            },
            {"code": "KOKfunksjon0000", "text": "funksjon", "values": ["121"], "valueTexts": ["121"]},
            {
                "code": "KOKart0000",
                "text": "art",
                "values": ["AGD4", "AGD11"],
                "valueTexts": [
                    "Korrigerte brutto driftsutgifter på funksjon/tjenesteområde",
                    "Korrigerte brutto driftsutgifter per innbygger",
                ],
            },
            {
                "code": "KOKregnskapsomfa0000",
                "text": "regnskapsomfang",
                "values": ["A", "B"],
                "valueTexts": ["Konsern", "Kommunekasse"],
            },
            {
                "code": "ContentsCode",
                "text": "statistikkvariabel",
                "values": ["KOSbelop0000", "KOSandel0000"],
                "valueTexts": ["Beløp (1000 kr)", "Andel (prosent)"],
            },
            {"code": "Tid", "text": "år", "values": ["2025"], "valueTexts": ["2025"]},
        ],
    }


@pytest.fixture
def meta_12150():
    """Energibruk i kommunal eiendomsforvaltning, med temperaturkorrigert variant."""
    return {
        "title": "12150",
        "variables": [
            {
                "code": "KOKkommuneregion0000",
                "text": "region",
                "values": ["K-3001"],
                "valueTexts": ["Halden"],
            },
            {
                "code": "KOKfunksjon0000",
                "text": "funksjon",
                "values": ["130", "221", "222", "261", "381", "386"],
                "valueTexts": ["130", "221", "222", "261", "381", "386"],
            },
            {
                "code": "KOKenergitype0000",
                "text": "energitype",
                "values": ["01", "02", "03", "04"],
                "valueTexts": ["Elektrisitet", "Fjernvarme", "Olje og parafin", "Bioenergi"],
            },
            {
                "code": "ContentsCode",
                "text": "statistikkvariabel",
                "values": ["KOSbruk1000kWh0000", "KOStemperaturkor0000", "KOSbrukperkvm0000"],
                "valueTexts": [
                    "Energibruk (MWh)",
                    "Temperaturkorrigert energibruk (MWh)",
                    "Energibruk per m2 eid areal (kWh)",
                ],
            },
            {"code": "Tid", "text": "år", "values": ["2025"], "valueTexts": ["2025"]},
        ],
    }


@pytest.fixture
def meta_11906():
    """Areal for kommunale formålsbygg, etter eieform."""
    return {
        "title": "11906",
        "variables": [
            {
                "code": "KOKkommuneregion0000",
                "text": "region",
                "values": ["K-3001", "EAK"],
                "valueTexts": ["Halden", "Landet"],
            },
            {
                "code": "KOKfunksjon0000",
                "text": "funksjon",
                "values": ["130", "221", "222", "261", "381", "386"],
                "valueTexts": ["130", "221", "222", "261", "381", "386"],
            },
            {
                "code": "KOKeieform0000",
                "text": "eieform",
                "values": ["eid", "leid", "samlet"],
                "valueTexts": ["Eid areal", "Leid areal", "Samlet areal"],
            },
            {
                "code": "ContentsCode",
                "text": "statistikkvariabel",
                "values": ["KOSareal0000"],
                "valueTexts": ["Areal på formålsbygg (m2)"],
            },
            {"code": "Tid", "text": "år", "values": ["2025"], "valueTexts": ["2025"]},
        ],
    }


# -- 12905 ------------------------------------------------------------------


def test_kostnadstabellen_har_ingen_sektordimensjon(konfig, meta_12905):
    valg = sektorvakt(meta_12905, konfig)
    assert valg.kilde == "ikke_aktuell"
    assert valg.dimensjon == ""


def test_alle_fire_artene_finnes_med_de_faktiske_navnene(konfig, meta_12905):
    arter = finn_arter(meta_12905, konfig, ["drift", "vedlikehold", "renhold", "energi"])
    assert {k: v.kode for k, v in arter.items()} == {
        "drift": "AGD39",
        "vedlikehold": "AGD36",
        "renhold": "AGD38",
        "energi": "AG1",  # følger ikke AGD-serien
    }


def test_belopet_velges_foran_ssbs_ferdigberegnede_kr_per_m2(konfig, meta_12905):
    valg = velg_entydig_contents(
        meta_12905, konfig["kodesok"]["kroner"], "contents:kroner", _overstyring(konfig, "kroner")
    )
    assert valg.kode == "KOSbelop0000"


# -- 12367 ------------------------------------------------------------------


def test_regnskapsomfang_gjenkjennes_som_sektordimensjon(konfig, meta_12367):
    """Dimensjonen heter «regnskapsomfang» her, ikke «sektor»."""
    valg = sektorvakt(meta_12367, konfig)
    assert valg.kode == "A"
    assert "konsern" in valg.tekst.lower()


def test_forvaltningsarten_er_last_fordi_tekstsoket_ikke_er_entydig(konfig, meta_12367):
    """To arter inneholder «korrigerte brutto». Overstyringen avgjør."""
    valg = finn_arter(meta_12367, konfig, ["forvaltning"])["forvaltning"]
    assert valg.kode == "AGD4"
    assert valg.kilde == "overstyrt"
    assert "funksjon/tjenesteområde" in valg.tekst


def test_belopet_finnes_ogsaa_i_forvaltningstabellen(konfig, meta_12367):
    valg = velg_entydig_contents(
        meta_12367, konfig["kodesok"]["kroner"], "contents:kroner", _overstyring(konfig, "kroner")
    )
    assert valg.kode == "KOSbelop0000"


# -- 12150 ------------------------------------------------------------------


def test_ukorrigert_energibruk_velges_foran_temperaturkorrigert(konfig, meta_12150):
    """Implisitt pris må regnes på faktisk forbruk, ikke på et normalisert tall."""
    valg = finn_kode(
        meta_12150, "contents:energibruk", konfig["kodesok"]["energibruk"],
        _overstyring(konfig, "energibruk"),
    )
    assert valg.kode == "KOSbruk1000kWh0000"
    assert "temperaturkorrigert" not in valg.tekst.lower()


def test_energitabellen_har_de_seks_byggfunksjonene(konfig, meta_12150):
    funksjoner = next(
        v for v in meta_12150["variables"] if v["code"] == "KOKfunksjon0000"
    )["values"]
    assert set(konfig["funksjoner"]) <= set(funksjoner)


# -- 11906 ------------------------------------------------------------------


def test_eid_areal_velges_foran_leid_og_samlet(konfig, meta_11906):
    valg = finn_kode(
        meta_11906, "eieform", konfig["kodesok"]["eieform"], _overstyring(konfig, "eieform")
    )
    assert valg.kode == "eid"
    assert valg.tekst == "Eid areal"
