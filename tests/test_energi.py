"""Energibruk per m², energivarer og kryssvalidering mot energiutgifter."""

from __future__ import annotations

import copy

import pytest

from kostra_fdv.energi import (
    Energirad,
    beregn_energiaar,
    beregn_rad,
    implisitt_pris_landsnivaa,
    klassifiser_fornybar,
)


def erad(kommune="K-1", areal=10_000.0, el=1_200_000.0, fjernvarme=300_000.0,
         olje=100_000.0, bio=0.0, energiutgift=2_400_000.0, funksjon="222", aar=2025):
    kwh = {"Elektrisitet": el, "Fjernvarme": fjernvarme, "Olje og parafin": olje, "Bioenergi": bio}
    return Energirad(
        kommune=kommune,
        kommunenavn=kommune,
        aar=aar,
        funksjon=funksjon,
        areal=areal,
        kwh={k: v for k, v in kwh.items() if v is not None},
        energiutgift_kr=energiutgift,
    )


def test_kwh_per_m2_og_andeler(konfig):
    r = erad()
    beregn_rad(r, konfig)
    assert r.kwh_m2 == pytest.approx(160.0)
    assert r.andeler["Elektrisitet"] == pytest.approx(1_200_000 / 1_600_000)
    assert sum(r.andeler.values()) == pytest.approx(1.0)


def test_fornybarandel_klassifiserer_energivarer(konfig):
    assert klassifiser_fornybar("Elektrisitet", konfig) is True
    assert klassifiser_fornybar("Fjernvarme", konfig) is True
    assert klassifiser_fornybar("Olje og parafin", konfig) is False
    assert klassifiser_fornybar("Ukjent vare", konfig) is None

    r = erad()
    beregn_rad(r, konfig)
    assert r.fornybarandel == pytest.approx(1_500_000 / 1_600_000)


def test_implisitt_pris_er_kroner_delt_paa_kwh(konfig):
    r = erad(energiutgift=2_400_000.0)  # 240 kr/m² mot 160 kWh/m²
    beregn_rad(r, konfig)
    assert r.implisitt_pris == pytest.approx(1.5)
    assert "implisitt_pris_utenfor" not in r.flagg


def test_urimelig_implisitt_pris_flagges_men_blokkerer_ikke(konfig):
    r = erad(energiutgift=12_000_000.0)  # 1200 kr/m² mot 160 kWh/m² = 7,5 kr/kWh
    beregn_rad(r, konfig)
    assert "implisitt_pris_utenfor" in r.flagg
    assert "implisitt_pris_utenfor" not in konfig["blokkerende_flagg_energi"]


def test_energiflagg_fanger_urimelige_nivaaer(konfig):
    lav = erad(el=200_000.0, fjernvarme=0.0, olje=0.0)   # 20 kWh/m²
    hoy = erad(el=6_000_000.0, fjernvarme=0.0, olje=0.0)  # 600 kWh/m²
    null = erad(el=0.0, fjernvarme=0.0, olje=0.0)
    for r in (lav, hoy, null):
        beregn_rad(r, konfig)
    assert "kwh_urimelig_lav" in lav.flagg
    assert "kwh_urimelig_hoy" in hoy.flagg
    assert "kwh_null" in null.flagg


def test_uteligger_i_log_rom_settes_etter_ovrige_flagg(konfig):
    rader = [erad(kommune=f"K-{i}", el=1_200_000.0 + i * 5_000) for i in range(40)]
    rader += [erad(kommune=f"L-{i}", el=150_000.0, fjernvarme=0.0, olje=0.0) for i in range(8)]
    resultat = beregn_energiaar(rader, copy.deepcopy(konfig))
    assert resultat.frafall.get("kwh_urimelig_lav") == 8
    assert resultat.n_kjerne == 40


def test_energivarefordeling_summerer_til_en(konfig):
    rader = [erad(kommune=f"K-{i}") for i in range(20)]
    resultat = beregn_energiaar(rader, copy.deepcopy(konfig))
    assert sum(resultat.energivarer.values()) == pytest.approx(1.0)
    assert resultat.som_dict()["temperaturkorrigert"] is False


def test_implisitt_pris_landsnivaa_er_sum_delt_paa_sum():
    rader = [
        erad(kommune="A", el=1_000_000.0, fjernvarme=0.0, olje=0.0, energiutgift=1_500_000.0),
        erad(kommune="B", el=3_000_000.0, fjernvarme=0.0, olje=0.0, energiutgift=3_000_000.0),
    ]
    assert implisitt_pris_landsnivaa(rader) == pytest.approx(4_500_000 / 4_000_000)


def test_publisert_fordeling_av_implisitt_pris_er_kvalitetsindikator(konfig):
    rader = [erad(kommune=f"K-{i}") for i in range(30)]
    rader.append(erad(kommune="FEIL", energiutgift=30_000_000.0))
    resultat = beregn_energiaar(rader, copy.deepcopy(konfig))
    pris = resultat.implisitt_pris
    assert pris["median"] == pytest.approx(1.5, abs=0.2)
    assert pris["andel_utenfor_intervall"] > 0
    assert pris["intervall"] == [0.5, 3.0]


def test_fornybarandel_tas_fra_ssbs_egen_gruppering(konfig):
    """Tabellen har en «Fornybar energi»-gruppering. Den er bedre enn å gjette.

    Uten den måtte fornybarandelen utledes av varenavnene, og da må man ta
    stilling til hvor fornybar fjernvarmen er. Det varierer mellom anlegg.
    """
    r = erad(el=1_000_000.0, fjernvarme=0.0, olje=500_000.0, bio=0.0)
    r.fornybar_kwh = 1_000_000.0
    beregn_rad(r, konfig)
    assert r.fornybarandel == pytest.approx(1_000_000 / 1_500_000)


def test_fornybarandel_faller_tilbake_paa_varenavn(konfig):
    """Mangler grupperingen, brukes klassifiseringen i config."""
    r = erad(el=1_000_000.0, fjernvarme=0.0, olje=500_000.0, bio=0.0)
    r.fornybar_kwh = None
    beregn_rad(r, konfig)
    assert r.fornybarandel == pytest.approx(1_000_000 / 1_500_000)


def test_fornybarandel_kan_ikke_overstige_hundre_prosent(konfig):
    r = erad(el=1_000_000.0, fjernvarme=0.0, olje=0.0, bio=0.0)
    r.fornybar_kwh = 1_200_000.0  # avrunding i kilden
    beregn_rad(r, konfig)
    assert r.fornybarandel == 1.0
