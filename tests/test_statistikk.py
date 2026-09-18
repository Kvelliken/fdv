"""Enhetstester uten nett: statistikk og avrunding."""

from __future__ import annotations

import math

import pytest

from kostra_fdv.beregning import kvantil, log_tukey_gjerde, median, trimmet_snitt
from kostra_fdv.utdata import avrund_naermeste, verdipar


def test_kvantil_interpolerer_som_type_7():
    verdier = [1, 2, 3, 4]
    assert kvantil(verdier, 0.0) == 1
    assert kvantil(verdier, 1.0) == 4
    assert kvantil(verdier, 0.5) == 2.5
    assert kvantil(verdier, 0.25) == pytest.approx(1.75)


def test_median_av_partall_og_oddetall():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 2, 3]) == 2.5


def test_trimmet_snitt_fjerner_begge_haler():
    verdier = list(range(1, 11)) + [1000]
    assert trimmet_snitt(verdier, 0.10) < sum(verdier) / len(verdier)
    # Uten trimming drar uteliggeren snittet langt over medianen.
    assert trimmet_snitt(verdier, 0.10) == pytest.approx(6.0, abs=1.5)


def test_log_tukey_er_asymmetrisk_i_lineaert_rom():
    # Lognormalt utvalg: gjerdet skal ligge nærmere medianen på lavsiden
    # enn på høysiden når det transformeres tilbake.
    verdier = [math.exp(x / 10) * 500 for x in range(-20, 21)]
    nedre, ovre = log_tukey_gjerde(verdier, 1.5)
    m = median(verdier)
    assert nedre < m < ovre
    assert (m - nedre) < (ovre - m)


def test_log_tukey_ignorerer_ikke_positive_verdier():
    nedre, ovre = log_tukey_gjerde([0, -5, 100, 110, 120, 130, 140], 1.5)
    assert nedre > 0
    assert ovre > 130


def test_log_tukey_gir_apent_gjerde_ved_for_fa_verdier():
    nedre, ovre = log_tukey_gjerde([100, 120], 1.5)
    assert (nedre, ovre) == (0.0, math.inf)


@pytest.mark.parametrize(
    "inn,ut",
    [(0, 0), (2, 0), (2.5, 5), (7.4, 5), (7.5, 10), (612, 610), (613, 615), (-7.5, -10)],
)
def test_avrunding_til_naermeste_fem_runder_halve_opp(inn, ut):
    assert avrund_naermeste(inn, 5) == ut


def test_verdipar_beholder_full_presisjon():
    par = verdipar(612.3456, 5)
    assert par["verdi"] == pytest.approx(612.3456)
    assert par["verdi_avrundet"] == 610


def test_verdipar_taaler_nan_og_none():
    assert verdipar(None, 5)["verdi"] is None
    assert verdipar(float("nan"), 5)["verdi_avrundet"] is None
