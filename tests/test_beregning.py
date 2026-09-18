"""Kostnadsberegning: flagg, nøstede kolonner og forankret nedbryting."""

from __future__ import annotations

import copy

import pytest

from kostra_fdv.beregning import (
    Kommunerad,
    beregn_funksjonsaar,
    intern_konsistens,
    sett_flagg,
)


def rad(kommune="K-1", areal=10_000.0, drift=6_000_000.0, energi=1_700_000.0,
        renhold=1_500_000.0, vedlikehold=1_200_000.0, forvaltning=1_000_000.0,
        portefolje=50_000.0, funksjon="222", aar=2025) -> Kommunerad:
    r = Kommunerad(
        kommune=kommune,
        kommunenavn=kommune,
        aar=aar,
        funksjon=funksjon,
        areal=areal,
        portefoljeareal=portefolje,
        kroner={"drift": drift, "energi": energi, "renhold": renhold, "vedlikehold": vedlikehold},
        forvaltning_kroner=forvaltning,
    )
    r.beregn_per_m2()
    return r


def test_ovrig_drift_er_restpost_ikke_egen_kolonne():
    r = rad()
    assert r.per_m2["drift"] == pytest.approx(600)
    assert r.per_m2["ovrig_drift"] == pytest.approx(600 - 170 - 150)
    # Summering av energi + renhold + drift ville gitt dobbelttelling:
    assert r.per_m2["dv"] == pytest.approx(600 + 120)


def test_forvaltning_deles_paa_portefoljeareal():
    r = rad(areal=10_000.0, portefolje=50_000.0, forvaltning=1_000_000.0)
    assert r.per_m2["forvaltning"] == pytest.approx(20)
    assert r.per_m2["fdv"] == pytest.approx(r.per_m2["dv"] + 20)


def test_forvaltning_er_likt_for_alle_bygningstyper(konfig):
    skole = rad(funksjon="222", areal=10_000.0, portefolje=50_000.0)
    barnehage = rad(funksjon="221", areal=4_000.0, portefolje=50_000.0)
    assert skole.per_m2["forvaltning"] == barnehage.per_m2["forvaltning"]


def test_flagg_settes_paa_raastorrelser(konfig):
    assert "areal_mangler" in sett_flagg(rad(areal=None), konfig)
    assert "areal_for_lite" in sett_flagg(rad(areal=300.0), konfig)
    assert "drift_mangler" in sett_flagg(rad(drift=None), konfig)
    assert "drift_null" in sett_flagg(rad(drift=0.0), konfig)
    assert "vedlikehold_negativ" in sett_flagg(rad(vedlikehold=-5.0), konfig)


def test_billig_kommune_skilles_fra_kommune_uten_rapportert_kostnad(konfig):
    billig = rad(drift=2_500_000.0, energi=600_000.0, renhold=500_000.0)  # 250 kr/m²
    ikke_rapportert = rad(drift=150_000.0, energi=40_000.0, renhold=30_000.0)  # 15 kr/m²
    assert sett_flagg(billig, konfig) == []
    assert "drift_urimelig_lav" in sett_flagg(ikke_rapportert, konfig)


def test_negativ_restpost_flagges(konfig):
    r = rad(drift=3_000_000.0, energi=2_000_000.0, renhold=1_500_000.0)
    assert "drift_mindre_enn_delposter" in sett_flagg(r, konfig)
    assert intern_konsistens([r])


def test_uteliggere_beregnes_etter_ovrige_flagg(konfig):
    """Rapporteringsfeil skal ikke trekke kvartilene ned og beskytte seg selv."""
    rader = [rad(kommune=f"K-{i}", drift=6_000_000.0 + i * 20_000) for i in range(40)]
    # Femten kommuner med kostnaden ført et annet sted:
    rader += [rad(kommune=f"F-{i}", drift=60_000.0, energi=20_000.0, renhold=15_000.0,
                  vedlikehold=10_000.0) for i in range(15)]
    resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
    # Alle femten faller ut på drift_urimelig_lav, ingen ekte kommune skal
    # bli uteligger fordi feilene lå i utvalget da gjerdet ble regnet.
    assert resultat.frafall.get("drift_urimelig_lav") == 15
    assert resultat.n_kjerne == 40
    assert "DV_uteligger_lav" not in resultat.frafall


def test_ekte_hoyhale_overlever_gjerdet(konfig):
    """Et stort takarbeid er en faktisk kostnad, ikke en rapporteringsfeil.

    Vedlikehold er periodisk, så fordelingen har en lang høyhale. Gjerdet i
    log-rom skal tåle en kommune som ligger dobbelt så høyt som medianen.
    """
    import math
    import random

    rng = random.Random(3)
    rader = []
    for i in range(120):
        drift = 600 * math.exp(rng.gauss(0, 0.25)) * 10_000
        vedl = 120 * math.exp(rng.gauss(0, 0.70)) * 10_000
        rader.append(
            rad(kommune=f"K-{i}", drift=drift, energi=drift * 0.28, renhold=drift * 0.25,
                vedlikehold=vedl)
        )
    # Kommune med et stort takarbeid: D+V på 1150 kr/m², drøyt 1,5 ganger medianen.
    rader.append(rad(kommune="TAK", drift=6_000_000.0, energi=1_700_000.0,
                     renhold=1_500_000.0, vedlikehold=5_500_000.0))
    resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
    assert "TAK" in resultat.kommuner_kjerne

    # Et lineært Tukey-gjerde på de samme tallene kutter hardere i høyhalen.
    from kostra_fdv.beregning import kvantil, log_tukey_gjerde

    dv = [r.per_m2["dv"] for r in rader]
    q1, q3 = kvantil(dv, 0.25), kvantil(dv, 0.75)
    lineaert_ovre = q3 + 1.5 * (q3 - q1)
    _, log_ovre = log_tukey_gjerde(dv, 1.5)
    assert log_ovre > lineaert_ovre


def test_forankret_nedbryting_summerer_til_dv(konfig):
    import random

    rng = random.Random(7)
    rader = []
    for i in range(80):
        rader.append(
            rad(
                kommune=f"K-{i}",
                drift=rng.uniform(5_000_000, 8_000_000),
                energi=rng.uniform(1_200_000, 2_400_000),
                renhold=rng.uniform(1_000_000, 2_000_000),
                vedlikehold=rng.uniform(400_000, 3_000_000),
            )
        )
    resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
    forankret = resultat.forankret
    delposter = ("energi", "renhold", "ovrig_drift", "vedlikehold")
    for nivaa in ("lav", "sannsynlig", "hoy"):
        sum_deler = sum(forankret[p][nivaa] for p in delposter)
        assert sum_deler == pytest.approx(forankret["dv"][nivaa], rel=1e-9)


def test_delpostenes_egne_spenn_er_videre_enn_det_forankrede(konfig):
    import random

    rng = random.Random(11)
    rader = []
    for i in range(120):
        rader.append(
            rad(
                kommune=f"K-{i}",
                drift=rng.uniform(4_500_000, 9_000_000),
                energi=rng.uniform(1_000_000, 2_800_000),
                renhold=rng.uniform(900_000, 2_400_000),
                vedlikehold=rng.uniform(300_000, 3_500_000),
            )
        )
    resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
    delposter = ("energi", "renhold", "ovrig_drift", "vedlikehold")
    sum_egne_p10 = sum(resultat.egne[p].p10 for p in delposter)
    sum_egne_p90 = sum(resultat.egne[p].p90 for p in delposter)
    assert sum_egne_p10 < resultat.egne["dv"].p10
    assert sum_egne_p90 > resultat.egne["dv"].p90


def test_arealvektet_snitt_er_sum_kroner_delt_paa_sum_areal(konfig):
    rader = [
        rad(kommune="A", areal=10_000.0, drift=6_000_000.0, vedlikehold=1_000_000.0),
        rad(kommune="B", areal=30_000.0, drift=21_000_000.0, vedlikehold=3_000_000.0),
    ]
    resultat = beregn_funksjonsaar(rader, copy.deepcopy(konfig))
    forventet = (6_000_000 + 1_000_000 + 21_000_000 + 3_000_000) / 40_000
    assert resultat.egne["dv"].arealvektet == pytest.approx(forventet)
