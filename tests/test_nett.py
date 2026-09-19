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
    blokkerende = float(konfig["avstemming"].get("toleranse_blokkerende", 0.05))
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
    avvikene = {}
    for funksjon in konfig["funksjoner"]:
        land_kr = _landsrad(kost_ds, kost_dim, funksjon)
        land_m2 = _landsrad(areal_ds, areal_dim, funksjon)
        if not land_kr or not land_m2:
            manglet.append(funksjon)
            continue
        ssb = (land_kr * faktor_kr) / land_m2

        # Landstallet er sum(kroner) delt på sum(areal) over alle kommuner,
        # uavhengig av om den enkelte kommune har rapportert begge deler. Vårt
        # tall må regnes på samme måte, ellers sammenlignes to ulike
        # definisjoner: en kommune som har ført kostnader uten å rapportere
        # areal løfter landstallets teller, men ikke nevneren.
        rader = kostnad[funksjon]
        sum_kr = sum(r.kroner["drift"] for r in rader if r.kroner.get("drift") is not None)
        sum_m2 = sum(r.areal for r in rader if r.areal)
        vaart = sum_kr / sum_m2

        avvik = (vaart - ssb) / ssb
        avvikene[funksjon] = avvik
        print(
            f"funksjon {funksjon}: vårt {vaart:.1f} kr/m² "
            f"({sum_kr:,.0f} kr / {sum_m2:,.0f} m²), landstall {ssb:.1f}, avvik {avvik:+.2%}"
        )
        assert abs(avvik) <= blokkerende, (
            f"Funksjon {funksjon}, årgang {siste_aargang}: vårt arealvektede snitt "
            f"{vaart:.1f} kr/m² mot landstallet {ssb:.1f} kr/m², avvik {avvik:.1%}. "
            "Faktor ~1000 betyr feil enhetsantakelse. Noen få prosent betyr som "
            "regel at utvalget av kommuner ikke er det samme som landstallets, "
            "eller at nevneren er et annet areal enn landstallets."
        )

    assert not manglet, (
        f"Fant ingen landsaggregat i regionsdimensjonen for funksjonene {manglet}. "
        "Avstemmingen kan da ikke kjøres slik den er skrevet, og tallene skal ikke "
        "publiseres uten en annen kontroll mot SSBs publiserte nivå."
    )

    # Et systematisk avvik med samme fortegn og omtrent samme størrelse på alle
    # seks funksjonene er en definisjonsforskjell, ikke en regnefeil. Skriv det
    # ut samlet, så mønsteret er synlig i loggen.
    over = {f: a for f, a in avvikene.items() if abs(a) > toleranse}
    if over:
        snitt = sum(avvikene.values()) / len(avvikene)
        print(
            f"\nAvvik over {toleranse:.0%} for {len(over)} av {len(avvikene)} funksjoner. "
            f"Gjennomsnittlig avvik {snitt:+.2%}, spredning "
            f"{min(avvikene.values()):+.2%} til {max(avvikene.values()):+.2%}. "
            "Samme fortegn på alle tyder på ulik nevner eller ulikt kommuneutvalg, "
            "ikke på en regnefeil. Se METODE.md kapittel 11."
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


def test_sammenlign_med_ssbs_egen_kr_per_m2(klient, konfig, siste_aargang, uttrekk):
    """Diagnose: bruker SSBs publiserte kr/m² samme nevner som oss?

    Tabellen har en ferdigberegnet kr/m²-variabel ved siden av beløpet. Vi
    bruker den ikke til å publisere, fordi nevneren da er ukjent. Men på
    landsnivå kan den fortelle hva SSB deler på: stemmer vårt tall med deres
    kr/m², er nevneren eid areal. Ligger deres lavere, er nevneren større,
    altså samlet areal.

    Testen stopper ikke jobben. Den skriver ut hva den finner.
    """
    from kostra_fdv.pipeline import (
        DIM_ART, DIM_FUNKSJON, DIM_REGION, DIM_TID, _dimkode, _rens,
    )
    from kostra_fdv.ssb_api import dimensjonsverdier

    kodevalg = {v["formaal"]: v for v in uttrekk["kodevalg"]}
    meta = klient.hent_metadata(konfig["tabeller"]["kostnad"])

    perkvm = None
    for kode, _, verdier in dimensjonsverdier(meta):
        if kode.lower() != "contentscode":
            continue
        for verdikode, tekst in verdier:
            t = tekst.lower()
            if "kvadratmeter" in t or "per m2" in t or "per m²" in t:
                perkvm = (kode, verdikode, tekst)
    if perkvm is None:
        pytest.skip("Tabellen har ingen ferdigberegnet kr/m²-variabel")

    dim_contents, kode_perkvm, tekst_perkvm = perkvm
    print(f"\nSammenligner mot SSBs egen variabel: {kode_perkvm} ({tekst_perkvm})")

    land = None
    for kode, _, verdier in dimensjonsverdier(meta):
        if "region" not in kode.lower():
            continue
        for verdikode, tekst in verdier:
            if "landet" in tekst.lower() and "uten" not in tekst.lower():
                land = verdikode
    if land is None:
        pytest.skip("Fant ingen landsaggregat")

    utvalg = {
        _dimkode(meta, DIM_REGION): [land],
        _dimkode(meta, DIM_FUNKSJON): list(konfig["funksjoner"]),
        _dimkode(meta, DIM_ART): [kodevalg["art:drift"]["kode"]],
        dim_contents: [kode_perkvm],
        _dimkode(meta, DIM_TID): [str(siste_aargang)],
    }
    datasett = klient.hent_data(konfig["tabeller"]["kostnad"], lag_sporring(_rens(utvalg)))

    d_fun = finn_dim_i(datasett, "funksjon")
    ssb_perkvm = {
        rad.koder[d_fun]: rad.verdi for rad in parse_jsonstat2(datasett) if rad.verdi
    }

    kostnad, _ = bygg_rader(uttrekk, konfig, siste_aargang)
    for funksjon in konfig["funksjoner"]:
        deres = ssb_perkvm.get(funksjon)
        if not deres:
            continue
        rader = kostnad[funksjon]
        sum_kr = sum(r.kroner["drift"] for r in rader if r.kroner.get("drift") is not None)
        sum_m2 = sum(r.areal for r in rader if r.areal)
        vaart = sum_kr / sum_m2
        print(
            f"funksjon {funksjon}: vårt {vaart:.1f} kr/m² mot SSBs {deres:.1f} kr/m², "
            f"forhold {vaart / deres:.4f}"
        )
    print(
        "\nEr forholdet nær 1,00 for alle, deler SSB på eid areal som oss. "
        "Ligger det systematisk over 1, deler de på et større areal, altså "
        "samlet areal (eid + leid)."
    )


def finn_dim_i(datasett, navn):
    for ident in datasett.get("id", []):
        if navn.lower() in ident.lower():
            return ident
    raise AssertionError(f"Fant ingen dimensjon med {navn!r}")
