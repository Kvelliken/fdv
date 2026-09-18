"""Hele kjeden på syntetisk grunnlag: uttrekk -> rader -> normtall.json.

Testene her er blokkerende i den forstand at de dekker feilene som ikke gir
noen synlig feilmelding under kjøring: feil enhetsantakelse, feil sektorvalg,
vekstrater regnet på feil utvalg.
"""

from __future__ import annotations

import copy
import json

import pytest
import syntetisk

from kostra_fdv.beregning import beregn_funksjonsaar, intern_konsistens
from kostra_fdv.energi import beregn_energiaar, implisitt_pris_landsnivaa
from kostra_fdv.historikk import panelkommuner
from kostra_fdv.pipeline import beregn_alle, bygg_rader

AARGANG = [2021, 2022, 2023, 2024, 2025]


@pytest.fixture(scope="module")
def frosset(tmp_path_factory):
    rot = tmp_path_factory.mktemp("repo")
    syntetisk.frys_syntetisk(rot, AARGANG)
    return rot


@pytest.fixture(scope="module")
def normtall(frosset, konfig):
    return beregn_alle(frosset, copy.deepcopy(konfig), AARGANG)


def test_rader_bygges_med_riktige_enheter(frosset, konfig):
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    kostnad, energi = bygg_rader(grunnlag, konfig, 2025)
    rad = next(r for r in kostnad["222"] if r.areal and r.kroner["drift"])
    rad.beregn_per_m2()
    # 1000 kr -> kr og MWh -> kWh skal gi tall i rimelig størrelsesorden.
    assert 100 < rad.per_m2["drift"] < 3000
    from kostra_fdv.energi import beregn_rad

    erad = next(e for e in energi["222"] if e.areal and e.sum_kwh)
    beregn_rad(erad, konfig)
    assert 20 < erad.kwh_m2 < 800


def test_feil_enhetsantakelse_gir_avvik_paa_faktor_1000(frosset, konfig):
    """Vaktposten mot den klassiske feilen: beløp i 1000 kr lest som kroner."""
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    feil_konfig = copy.deepcopy(konfig)
    feil_konfig["enheter"]["kroner_faktor"] = 1
    kostnad, _ = bygg_rader(grunnlag, feil_konfig, 2025)
    rad = next(r for r in kostnad["222"] if r.areal and r.kroner["drift"])
    rad.beregn_per_m2()
    assert rad.per_m2["drift"] < 10  # verdier som 7 kr/m² er signaturen på feilen


def test_negative_restposter_fanges_og_holdes_utenfor_kjernen(frosset, konfig):
    """energi + renhold + øvrig drift == drift per kommune i kjernedatasettet.

    En negativ restpost betyr feil i uttrekket, ikke en billig kommune.
    Grunnlaget inneholder slike rader med vilje; ingen av dem skal overleve
    filtreringen.
    """
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    kostnad, _ = bygg_rader(grunnlag, konfig, 2025)
    for funksjon, rader in kostnad.items():
        resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
        assert resultat.frafall.get("drift_mindre_enn_delposter", 0) > 0
        kjerne = set(resultat.kommuner_kjerne)
        assert intern_konsistens([r for r in resultat.rader if r.kommune in kjerne]) == []


def test_sum_energivarer_er_lik_total(frosset, konfig):
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    _, energi = bygg_rader(grunnlag, konfig, 2025)
    for rad in energi["222"]:
        if rad.kwh:
            assert rad.sum_kwh == pytest.approx(sum(rad.kwh.values()))


def test_arealvektet_snitt_reproduserer_sum_delt_paa_sum(frosset, konfig):
    """Selve avstemmingsmekanismen. Mot levende API kjøres den i test_nett.py."""
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    kostnad, _ = bygg_rader(grunnlag, konfig, 2025)
    resultat = beregn_funksjonsaar(kostnad["222"], copy.deepcopy(konfig))
    kjerne = set(resultat.kommuner_kjerne)
    rader = [r for r in resultat.rader if r.kommune in kjerne]
    sum_kr = sum(r.kroner["drift"] + r.kroner["vedlikehold"] for r in rader)
    sum_areal = sum(r.areal for r in rader)
    assert resultat.egne["dv"].arealvektet == pytest.approx(sum_kr / sum_areal, rel=1e-9)


def test_implisitt_energipris_paa_landsnivaa_ligger_i_intervallet(frosset, konfig):
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    _, energi = bygg_rader(grunnlag, konfig, 2025)
    rader = [r for r in energi["222"] if r.sum_kwh]
    pris = implisitt_pris_landsnivaa(rader)
    gr = konfig["terskler"]["implisitt_energipris"]
    assert gr["lav"] <= pris <= gr["hoy"], (
        f"Implisitt energipris {pris:.2f} kr/kWh utenfor {gr}. "
        "Kostnads- og energiuttrekket er hentet for ulik årgang, sektor eller areal."
    )


def test_panelet_er_likt_i_alle_aar_og_delmengde_av_nivaautvalget(normtall):
    hist = normtall["funksjoner"]["222"]["kostnad"]["historikk"]["dv"]
    n_panel = {p["n_kommuner"] for p in hist["panelserie"]["punkter"]}
    assert len(n_panel) == 1, "Panelet skal ha like mange kommuner i alle år"
    for niv, pan in zip(hist["nivaaserie"]["punkter"], hist["panelserie"]["punkter"]):
        assert pan["n_kommuner"] <= niv["n_kommuner"]
        assert pan["aargang"] == niv["aargang"]


def test_vekstrater_regnes_paa_panelet(normtall):
    hist = normtall["funksjoner"]["222"]["kostnad"]["historikk"]["dv"]
    vekst = hist["vekst"]
    assert vekst["n_panel"] == hist["n_panel"]
    # Testgrunnlaget har 3 % nominell vekst per år innebygd.
    assert vekst["aarlig_gjennomsnittlig_endring_prosent"] == pytest.approx(3.0, abs=1.0)


def test_tre_aargang_vises_fem_er_frosset(normtall):
    assert len(normtall["grunnlag"]["aargang_vist"]) == 3
    assert len(normtall["grunnlag"]["aargang_frosne"]) == 5
    assert normtall["grunnlag"]["prisjustering"] == "ingen"


def test_normtall_er_avrundet_til_naermeste_fem_kun_i_presentasjonslaget(normtall):
    dv = normtall["funksjoner"]["222"]["kostnad"]["normtall_forankret"]["dv"]
    for nivaa in ("lav", "sannsynlig", "hoy"):
        assert dv[nivaa]["verdi_avrundet"] % 5 == 0
        assert dv[nivaa]["verdi"] != dv[nivaa]["verdi_avrundet"] or float(
            dv[nivaa]["verdi"]
        ).is_integer()


def test_forvaltning_er_identisk_for_alle_bygningstyper(frosset, konfig, normtall):
    """Funksjon 121 har ikke eget areal, så leddet er likt for alle bygg.

    På kommunenivå er tallet eksakt likt. De publiserte medianene kan skille
    seg marginalt fordi kjerneutvalget av kommuner er ulikt per bygningstype,
    og det er forklart i forbeholdet på nettsiden.
    """
    from kostra_fdv.pipeline import les_frosset

    grunnlag = les_frosset(frosset, 2025)
    kostnad, _ = bygg_rader(grunnlag, konfig, 2025)
    per_kommune: dict[str, set] = {}
    for funksjon, rader in kostnad.items():
        for r in rader:
            r.beregn_per_m2()
            if "forvaltning" in r.per_m2:
                per_kommune.setdefault(r.kommune, set()).add(round(r.per_m2["forvaltning"], 9))
    assert per_kommune
    assert all(len(verdier) == 1 for verdier in per_kommune.values())

    publisert = normtall["forvaltning"]
    assert publisert["n_kjerne"] > 0
    assert publisert["tre_punkt"]["sannsynlig"]["verdi"] > 0
    assert "porteføljetall" in publisert["forklaring"] or "porteføljenivå" in publisert["forklaring"]
    # Leddet skal ikke dukke opp som seks nesten like tall per bygningstype.
    for innhold in normtall["funksjoner"].values():
        assert "forvaltning" not in innhold["kostnad"]["normtall_forankret"]


def test_energitall_er_merket_som_ikke_temperaturkorrigert(normtall):
    for innhold in normtall["funksjoner"].values():
        assert innhold["energi"]["siste"]["temperaturkorrigert"] is False
        for aargang in innhold["energi"]["per_aargang"].values():
            assert aargang["temperaturkorrigert"] is False
    assert any("temperaturkorrigert" in f for f in normtall["forbehold"])


def test_forbehold_og_merking_folger_med_ut(normtall):
    assert "Ingen prisjustering" in normtall["merking"]
    assert any("porteføljetall" in f for f in normtall["forbehold"])
    assert any("summeres" in f for f in normtall["forbehold"])
    assert normtall["funksjoner"]["222"]["kostnad"]["normtall_forankret"]


def test_kodevalg_folger_med_i_publisert_json(normtall):
    formaal = {k["formaal"] for k in normtall["kodevalg"]}
    assert "sektor" in formaal
    assert "art:drift" in formaal
    assert all(k["kilde"] in ("automatisk", "overstyrt", "ikke_aktuell") for k in normtall["kodevalg"])


def test_datakvalitet_viser_frafall_per_aarsak(normtall):
    siste = str(normtall["grunnlag"]["siste_aargang"])
    kvalitet = normtall["datakvalitet"]["per_aargang"][siste]["kostnad"]["222"]
    assert kvalitet["n_grunnlag"] > kvalitet["n_kjerne"]
    assert "areal_mangler" in kvalitet["frafall_per_aarsak"]


def test_normtall_er_serialiserbart(normtall):
    tekst = json.dumps(normtall, ensure_ascii=False)
    assert len(tekst) > 1000
    assert json.loads(tekst)["skjemaversjon"] == 1


def test_revisjonsfil_skrives_per_funksjon_og_aargang(frosset, normtall):
    sti = frosset / "data" / "revisjon" / "2025" / "222.csv"
    assert sti.exists()
    linjer = sti.read_text(encoding="utf-8").splitlines()
    assert linjer[0].startswith("kommune;kommunenavn;aargang")
    assert len(linjer) > 50


def test_tom_forvaltningsart_gir_feil_som_lister_artene_med_tall(frosset, konfig):
    """Et tomt forvaltningsledd skal si hvilke arter som faktisk har tall.

    Uten det blir feilmeldingen «leddet er tomt», og den som feilsøker må
    gjette hvorfor.
    """
    from kostra_fdv.pipeline import UttrekkFeil, les_frosset

    grunnlag = les_frosset(frosset, 2025)
    feil_konfig = copy.deepcopy(konfig)
    feil_konfig["forvaltning"]["art"] = "renhold"  # ikke publisert på funksjon 121
    with pytest.raises(UttrekkFeil) as feil:
        bygg_rader(grunnlag, feil_konfig, 2025)
    tekst = str(feil.value)
    assert "AGD4" in tekst
    assert "kommuner med tall" in tekst
    assert "forvaltning.art" in tekst
