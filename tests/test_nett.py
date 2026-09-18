"""Blokkerende tester mot det levende API-et.

Kjøres ikke i vanlig testkjøring. Slå dem på med

    KOSTRA_NETT=1 python -m pytest tests/test_nett.py -q

Testene her er de eneste som kan avkrefte antakelsene i METODE.md kapittel 9.
De skal kjøres første gang grunnlaget hentes, og av grunnlag.yml ved hver
rehenting.
"""

from __future__ import annotations

import copy
import datetime as dt
import os

import pytest

from kostra_fdv.beregning import beregn_funksjonsaar
from kostra_fdv.energi import implisitt_pris_landsnivaa
from kostra_fdv.kodevalg import velg_aargang
from kostra_fdv.pipeline import bygg_rader, hent_og_frys
from kostra_fdv.ssb_api import (
    SSBKlient,
    dimensjonsverdier,
    lag_sporring,
    parse_jsonstat2,
    tilgjengelige_aargang,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("KOSTRA_NETT") != "1",
    reason="Krever nett mot data.ssb.no. Sett KOSTRA_NETT=1.",
)


@pytest.fixture(scope="module")
def klient(konfig):
    return SSBKlient(konfig)


@pytest.fixture(scope="module")
def siste_aargang(klient, konfig):
    metadata = klient.hent_metadata(konfig["tabeller"]["kostnad"])
    return velg_aargang(tilgjengelige_aargang(metadata), dt.date.today(), konfig)[-1]


@pytest.fixture(scope="module")
def uttrekk(klient, konfig, siste_aargang, tmp_path_factory):
    rot = tmp_path_factory.mktemp("nett")
    grunnlag, valg = hent_og_frys(klient, konfig, rot, siste_aargang)
    for v in valg:
        print(f"kodevalg: {v.formaal} = {v.kode} ({v.tekst}) [{v.kilde}]")
    return grunnlag


def _landsrad(datasett, dimensjoner: dict[str, str], funksjon: str) -> float | None:
    """Landstallet fra det frosne uttrekket, uten nye kall mot SSB.

    Regionsdimensjonen inneholder aggregatene i samme uttrekk som kommunene,
    så landstallet ligger allerede i det frosne grunnlaget. Å hente det på nytt
    ville dessuten sammenlignet mot et annet tidspunkt.
    """
    kandidater = []
    for rad in parse_jsonstat2(datasett):
        etikett = rad.etiketter.get(dimensjoner["region"], "").lower()
        if "landet" not in etikett or "uten" in etikett:
            continue
        if rad.koder.get(dimensjoner["funksjon"]) != funksjon:
            continue
        if dimensjoner.get("art") and rad.koder.get(dimensjoner["art"]) != dimensjoner["artkode"]:
            continue
        kandidater.append(rad.verdi)
    if not kandidater:
        return None
    return sum(v for v in kandidater if v is not None)


def test_avstemming_mot_landstall(konfig, siste_aargang, uttrekk):
    """sum(kroner)/sum(areal) skal reprodusere SSBs landstall innenfor 1 %.

    Avvik på omtrent faktor 1000 betyr feil enhetsantakelse: statistikkbanken
    oppgir beløp i 1000 kr. Moderat avvik betyr feil sektorvalg eller feil
    arealgrunnlag.
    """
    from kostra_fdv.pipeline import DIM_ART, DIM_FUNKSJON, DIM_REGION, finn_dim

    toleranse = float(konfig["avstemming"]["toleranse_landstall"])
    kodevalg = {v["formaal"]: v for v in uttrekk["kodevalg"]}
    faktor_kr = float(konfig["enheter"]["kroner_faktor"])
    kostnad, _ = bygg_rader(uttrekk, konfig, siste_aargang)

    kost_ds, areal_ds = uttrekk["kostnad"], uttrekk["areal"]
    kost_dim = {
        "region": finn_dim(kost_ds, DIM_REGION),
        "funksjon": finn_dim(kost_ds, DIM_FUNKSJON),
        "art": finn_dim(kost_ds, DIM_ART),
        "artkode": kodevalg["art:drift"]["kode"],
    }
    areal_dim = {
        "region": finn_dim(areal_ds, DIM_REGION),
        "funksjon": finn_dim(areal_ds, DIM_FUNKSJON),
    }

    manglet = []
    for funksjon in konfig["funksjoner"]:
        land_kr = _landsrad(kost_ds, kost_dim, funksjon)
        land_m2 = _landsrad(areal_ds, areal_dim, funksjon)
        if not land_kr or not land_m2:
            manglet.append(funksjon)
            continue
        ssb = (land_kr * faktor_kr) / land_m2

        rader = [r for r in kostnad[funksjon] if r.areal and r.kroner.get("drift") is not None]
        vaart = sum(r.kroner["drift"] for r in rader) / sum(r.areal for r in rader)

        avvik = abs(vaart - ssb) / ssb
        print(f"funksjon {funksjon}: vårt {vaart:.1f} kr/m², landstall {ssb:.1f}, avvik {avvik:.2%}")
        assert avvik <= toleranse, (
            f"Funksjon {funksjon}, årgang {siste_aargang}: vårt arealvektede snitt "
            f"{vaart:.1f} kr/m² mot landstallet {ssb:.1f} kr/m², avvik {avvik:.1%}. "
            "Faktor ~1000 betyr feil enhetsantakelse, moderat avvik betyr feil "
            "sektorvalg eller at nevneren er et annet areal enn landstallets."
        )

    assert not manglet, (
        f"Fant ingen landsaggregat i regionsdimensjonen for funksjonene {manglet}. "
        "Avstemmingen kan da ikke kjøres slik den er skrevet, og tallene skal ikke "
        "publiseres uten en annen kontroll mot SSBs publiserte nivå."
    )


def test_implisitt_energipris_paa_landsnivaa(konfig, siste_aargang, uttrekk):
    """sum(energiutgifter)/sum(kWh) skal ligge i konfigurert intervall."""
    _, energi = bygg_rader(uttrekk, konfig, siste_aargang)
    gr = konfig["terskler"]["implisitt_energipris"]
    for funksjon in konfig["funksjoner"]:
        rader = [r for r in energi[funksjon] if r.sum_kwh and r.energiutgift_kr is not None]
        assert rader, f"Ingen energirader for funksjon {funksjon}"
        pris = implisitt_pris_landsnivaa(rader)
        assert gr["lav"] <= pris <= gr["hoy"], (
            f"Funksjon {funksjon}: implisitt energipris {pris:.2f} kr/kWh utenfor "
            f"[{gr['lav']}, {gr['hoy']}]. Kostnads- og energiuttrekket kommer fra ulike "
            "skjema, så avviket kan isoleres til én av sidene."
        )


def test_energi_publiseres_per_funksjon(konfig, uttrekk):
    """Antakelse 6: statistikkbanken publiserer kWh fordelt på de seks funksjonene."""
    from kostra_fdv.pipeline import DIM_FUNKSJON, finn_dim

    dim = finn_dim(uttrekk["energi"], DIM_FUNKSJON, paakrevd=False)
    assert dim is not None, (
        "Energitabellen har ingen funksjonsdimensjon. Da gjelder samme begrensning "
        "som for forvaltning: ett porteføljetall som ikke kan splittes per "
        "bygningstype. Si det eksplisitt på nettsiden."
    )
    koder = set(uttrekk["energi"]["dimension"][dim]["category"]["index"])
    mangler = set(konfig["funksjoner"]) - koder
    assert not mangler, f"Energitabellen mangler funksjonene {sorted(mangler)}"


def test_kjernedatasettet_har_nok_kommuner(konfig, siste_aargang, uttrekk):
    kostnad, _ = bygg_rader(uttrekk, konfig, siste_aargang)
    for funksjon in konfig["funksjoner"]:
        resultat = beregn_funksjonsaar(kostnad[funksjon], copy.deepcopy(konfig))
        andel = resultat.n_kjerne / max(resultat.n_grunnlag, 1)
        print(
            f"funksjon {funksjon}: {resultat.n_kjerne} av {resultat.n_grunnlag} kommuner, "
            f"frafall {resultat.frafall}"
        )
        assert andel > 0.4, (
            f"Bare {andel:.0%} av kommunene i kjernedatasettet for funksjon {funksjon}. "
            "Sjekk sektorvalg og terskler før tallene publiseres."
        )


def test_forvaltning_har_dekning_og_baerer_forbeholdet(konfig, siste_aargang, uttrekk):
    """Forvaltningsleddet er korrigerte brutto driftsutgifter, og det skal sies.

    Funksjon 121 er tom i kostnadstabellen, så leddet hentes fra 12367 med
    AGD4. Den arten inneholder avskrivninger (art 590) og mva-utgift (art 429),
    og er dermed målt på en annen måte enn drift og vedlikehold. Summen er
    derfor ikke et rent FDV-tall, og forbeholdet må følge med ut.
    """
    from kostra_fdv.utdata import FORBEHOLD

    kostnad, _ = bygg_rader(uttrekk, konfig, siste_aargang)
    rader = kostnad[next(iter(konfig["funksjoner"]))]
    med = [r for r in rader if r.forvaltning_kroner]
    assert len(med) / len(rader) >= float(konfig["forvaltning"]["minste_dekning"])

    tekst = " ".join(FORBEHOLD).lower()
    assert "avskrivninger" in tekst
    assert "korrigerte brutto" in tekst
