"""Balansert panel, vekstrater og brudd i sammenlignbarhet."""

from __future__ import annotations

import pytest

from kostra_fdv.historikk import (
    brudd_som_gjelder,
    bygg_historikk,
    nivaaserie,
    panelkommuner,
    panelserie,
    vekstrater,
)


def test_panelet_er_snittet_av_de_rene_utvalgene():
    kjerne = {2023: ["A", "B", "C"], 2024: ["A", "C", "D"], 2025: ["A", "C"]}
    assert panelkommuner(kjerne) == ["A", "C"]


def test_panelet_er_delmengde_av_hvert_aars_nivaautvalg():
    kjerne = {2023: ["A", "B", "C"], 2024: ["A", "C", "D"], 2025: ["A", "C", "E"]}
    panel = set(panelkommuner(kjerne))
    for kommuner in kjerne.values():
        assert panel <= set(kommuner)


def test_panelet_har_like_mange_kommuner_i_alle_aar():
    verdier = {
        2023: {"A": 100, "B": 90, "C": 110},
        2024: {"A": 105, "C": 115, "D": 80},
        2025: {"A": 110, "C": 120},
    }
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    serie = panelserie(verdier, panelkommuner(kjerne))
    assert {p.n for p in serie.punkter} == {2}


def test_sammensetningsendring_flytter_nivaaserien_men_ikke_panelet():
    """En dyr kommune som faller ut ett år flytter medianen uten prisendring."""
    verdier = {
        2024: {"A": 100, "B": 200, "C": 300},
        2025: {"A": 100, "B": 200},  # C falt ut på et kvalitetsflagg
    }
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    niv = nivaaserie(verdier)
    pan = panelserie(verdier, panelkommuner(kjerne))
    assert niv.punkter[0].median != niv.punkter[1].median
    assert pan.punkter[0].median == pan.punkter[1].median
    vekst = vekstrater(pan, "222", "dv")
    assert vekst.endring_prosent == pytest.approx(0.0)


def test_vekstrate_paa_nivaaserien_er_en_feil_som_stoppes():
    verdier = {2024: {"A": 100}, 2025: {"A": 110}}
    niv = nivaaserie(verdier)
    with pytest.raises(ValueError, match="panelserien"):
        vekstrater(niv, "222", "dv")


def test_aarlig_gjennomsnittlig_endring():
    verdier = {
        2023: {"A": 100.0, "B": 100.0},
        2024: {"A": 110.0, "B": 110.0},
        2025: {"A": 121.0, "B": 121.0},
    }
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    vekst = vekstrater(panelserie(verdier, panelkommuner(kjerne)), "222", "dv")
    assert vekst.endring_prosent == pytest.approx(21.0)
    assert vekst.aarlig_endring_prosent == pytest.approx(10.0)


def test_brudd_skjuler_vekstraten_over_bruddpunktet():
    verdier = {2023: {"A": 100.0}, 2024: {"A": 110.0}, 2025: {"A": 121.0}}
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    brudd = [{"aar": 2024, "gjelder": "funksjon:386", "beskrivelse": "Endret avgrensning"}]
    vekst = vekstrater(panelserie(verdier, panelkommuner(kjerne)), "386", "dv", brudd)
    assert vekst.skjult_grunnet_brudd is True
    assert vekst.endring_prosent is None
    assert vekst.brudd[0]["beskrivelse"] == "Endret avgrensning"


def test_brudd_for_annen_funksjon_paavirker_ikke_serien():
    verdier = {2023: {"A": 100.0}, 2024: {"A": 110.0}}
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    brudd = [{"aar": 2024, "gjelder": "funksjon:386"}]
    vekst = vekstrater(panelserie(verdier, panelkommuner(kjerne)), "222", "dv", brudd)
    assert vekst.skjult_grunnet_brudd is False
    assert vekst.endring_prosent == pytest.approx(10.0)


def test_brudd_utenfor_intervallet_ignoreres():
    assert brudd_som_gjelder([{"aar": 2020, "gjelder": "alle"}], "222", "dv", 2023, 2025) == []
    assert brudd_som_gjelder([{"aar": 2023, "gjelder": "alle"}], "222", "dv", 2023, 2025) == []
    assert brudd_som_gjelder([{"aar": 2024, "gjelder": "alle"}], "222", "dv", 2023, 2025)


def test_bygg_historikk_oppgir_antall_kommuner_i_begge_utvalg():
    verdier = {2024: {"A": 100.0, "B": 120.0, "C": 90.0}, 2025: {"A": 110.0, "B": 130.0}}
    kjerne = {aar: list(v) for aar, v in verdier.items()}
    hist = bygg_historikk(verdier, kjerne, "222", "dv")
    assert hist["n_panel"] == 2
    assert hist["nivaaserie"]["punkter"][0]["n_kommuner"] == 3
    assert hist["panelserie"]["punkter"][0]["n_kommuner"] == 2


def test_arealvektet_snitt_i_serien():
    verdier = {2025: {"A": 100.0, "B": 200.0}}
    arealer = {2025: {"A": 1000.0, "B": 3000.0}}
    serie = nivaaserie(verdier, arealer)
    assert serie.punkter[0].arealvektet == pytest.approx((100 * 1000 + 200 * 3000) / 4000)
