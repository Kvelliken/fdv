"""Kjeden fra uttrekk til publiserte tall.

Ett sted per steg: hent og frys, bygg rader, beregn, skriv. Alle valg av
verdikoder logges og følger med ut i normtall.json.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import beregning, energi as energimodul, historikk, utdata
from .beregning import Kommunerad
from .energi import Energirad
from .kodevalg import Valg, finn_arter, finn_kode, sektorvakt
from .ssb_api import Rad, SSBFeil, SSBKlient, lag_sporring, parse_jsonstat2

logg = logging.getLogger(__name__)

KOSTNADSLEDD = ("drift", "vedlikehold", "renhold", "energi")

# Kandidatnavn for dimensjoner. Statistikkbanken bruker ulike kodenavn i
# ulike tabeller, så dimensjonen slås opp på navn, ikke på posisjon.
DIM_REGION = ("region", "kommune", "kommunenr")
DIM_FUNKSJON = ("funksjon", "kostrafunksjon")
DIM_TID = ("tid", "time", "aar", "år")
DIM_ART = ("art", "regnskapsbegrep", "kontoklasse")
DIM_SEKTOR = ("sektor",)
DIM_EIEFORM = ("eieform", "eier")
DIM_ENERGIVARE = ("energitype", "energivare", "energiprodukt")
DIM_CONTENTS = ("contentscode", "statistikkvariabel")


class UttrekkFeil(RuntimeError):
    """Uttrekket er ikke som metoden forutsetter. Publiser aldri delvise tall."""


def finn_dim(datasett: Mapping[str, Any], kandidater: Sequence[str], paakrevd: bool = True) -> str | None:
    """Finner dimensjons-ID i et json-stat2-datasett på navn."""
    ider = list(datasett.get("id", []))
    for kandidat in kandidater:
        for ident in ider:
            if kandidat.lower() in ident.lower():
                return ident
        for ident in ider:
            etikett = datasett["dimension"].get(ident, {}).get("label", "")
            if kandidat.lower() in str(etikett).lower():
                return ident
    if paakrevd:
        raise UttrekkFeil(f"Fant ingen dimensjon blant {kandidater} i {ider}")
    return None


def velg_entydig_contents(
    metadata: Mapping[str, Any],
    regel: Mapping[str, Any],
    formaal: str,
    overstyring: str | None = None,
) -> Valg:
    """Statistikkvariabelen. Har tabellen bare én, brukes den uten søk."""
    from .ssb_api import dimensjonsverdier

    for kode, tekst, verdier in dimensjonsverdier(metadata):
        if kode.lower() in ("contentscode",) and len(verdier) == 1:
            return Valg(formaal, kode, verdier[0][0], verdier[0][1], "automatisk")
    return finn_kode(metadata, formaal, regel, overstyring)


# -- Henting ----------------------------------------------------------------


def hent_og_frys(
    klient: SSBKlient, konfig: Mapping[str, Any], rot: Path, aar: int
) -> tuple[dict[str, Any], list[Valg]]:
    """Henter kostnad, forvaltning, areal og energi for én årgang og fryser det."""
    tabeller = konfig["tabeller"]
    funksjoner = list(konfig["funksjoner"])
    valg: list[Valg] = []
    grunnlag: dict[str, Any] = {}

    # Kostnad
    meta_kost = klient.hent_metadata(tabeller["kostnad"])
    sektor = sektorvakt(meta_kost, konfig)
    arter = finn_arter(meta_kost, konfig, KOSTNADSLEDD)
    overstyringer = konfig.get("overstyring") or {}
    kroner = velg_entydig_contents(
        meta_kost, konfig["kodesok"]["kroner"], "contents:kroner", overstyringer.get("kroner")
    )
    valg += [sektor, kroner, *arter.values()]
    utvalg = {
        _dimkode(meta_kost, DIM_REGION): [],
        _dimkode(meta_kost, DIM_FUNKSJON): funksjoner,
        arter["drift"].dimensjon: [a.kode for a in arter.values()],
        sektor.dimensjon: [sektor.kode],
        kroner.dimensjon: [kroner.kode],
        _dimkode(meta_kost, DIM_TID): [str(aar)],
    }
    grunnlag["kostnad"] = klient.hent_data(tabeller["kostnad"], lag_sporring(_rens(utvalg)))

    # Forvaltning, funksjon 121. Hentes fra tabellen config peker på: funksjon
    # 121 er tom i kostnadstabellen, så leddet kommer fra 12367 med korrigerte
    # brutto driftsutgifter. Det er et annet målebegrep enn D og V, og
    # forbeholdet følger med ut i normtall.json og på nettsiden.
    forv_tabell = tabeller[konfig["forvaltning"]["tabell"]]
    if forv_tabell == tabeller["kostnad"]:
        meta_forv, sektor_f, kroner_f = meta_kost, sektor, kroner
        arter_forv = arter
    else:
        meta_forv = klient.hent_metadata(forv_tabell)
        sektor_f = sektorvakt(meta_forv, konfig)
        kroner_f = velg_entydig_contents(
            meta_forv, konfig["kodesok"]["kroner"], "contents:kroner_forvaltning",
            overstyringer.get("kroner"),
        )
        arter_forv = finn_arter(meta_forv, konfig, [konfig["forvaltning"]["art"]])
        valg += [sektor_f, kroner_f, *arter_forv.values()]
    forvaltningsart = arter_forv[konfig["forvaltning"]["art"]]
    utvalg = {
        _dimkode(meta_forv, DIM_REGION): [],
        _dimkode(meta_forv, DIM_FUNKSJON): [konfig["forvaltning"]["funksjon"]],
        forvaltningsart.dimensjon: [forvaltningsart.kode],
        sektor_f.dimensjon: [sektor_f.kode],
        kroner_f.dimensjon: [kroner_f.kode],
        _dimkode(meta_forv, DIM_TID): [str(aar)],
    }
    grunnlag["forvaltning"] = klient.hent_data(forv_tabell, lag_sporring(_rens(utvalg)))

    # Areal
    meta_areal = klient.hent_metadata(tabeller["areal"])
    eieform = finn_kode(
        meta_areal, "eieform", konfig["kodesok"]["eieform"],
        (konfig.get("overstyring") or {}).get("eieform"),
    )
    areal_contents = velg_entydig_contents(meta_areal, konfig["kodesok"]["areal"], "contents:areal")
    valg += [eieform, areal_contents]
    sektor_a = sektorvakt(meta_areal, konfig)
    valg.append(sektor_a)
    utvalg = {
        _dimkode(meta_areal, DIM_REGION): [],
        _dimkode(meta_areal, DIM_FUNKSJON): funksjoner,
        sektor_a.dimensjon: [sektor_a.kode],
        eieform.dimensjon: [eieform.kode],
        areal_contents.dimensjon: [areal_contents.kode],
        _dimkode(meta_areal, DIM_TID): [str(aar)],
    }
    grunnlag["areal"] = klient.hent_data(tabeller["areal"], lag_sporring(_rens(utvalg)))

    # Energi
    meta_energi = klient.hent_metadata(tabeller["energi"])
    energibruk = finn_kode(
        meta_energi, "contents:energibruk", konfig["kodesok"]["energibruk"],
        (konfig.get("overstyring") or {}).get("energibruk"),
    )
    sektor_e = sektorvakt(meta_energi, konfig)
    valg += [energibruk, sektor_e]
    utvalg = {
        _dimkode(meta_energi, DIM_REGION): [],
        _dimkode(meta_energi, DIM_FUNKSJON): funksjoner,
        sektor_e.dimensjon: [sektor_e.kode],
        _dimkode(meta_energi, DIM_ENERGIVARE): [],
        energibruk.dimensjon: [energibruk.kode],
        _dimkode(meta_energi, DIM_TID): [str(aar)],
    }
    grunnlag["energi"] = klient.hent_data(tabeller["energi"], lag_sporring(_rens(utvalg)))

    grunnlag["kodevalg"] = [v.som_dict() for v in valg]
    grunnlag["hentet"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for navn in ("kostnad", "forvaltning", "areal", "energi", "kodevalg"):
        innhold = grunnlag[navn] if navn != "kodevalg" else {"kodevalg": grunnlag["kodevalg"]}
        gammelt = utdata.les_grunnlag(rot, aar, navn)
        for linje in utdata.diff_grunnlag(gammelt, innhold):
            logg.info("grunnlag/%s/%s: %s", aar, navn, linje)
        utdata.frys_grunnlag(rot, aar, navn, innhold)

    return grunnlag, valg


def sjekk_ingen_ufrie_dimensjoner(
    datasett: Mapping[str, Any], handtert: Sequence[str], navn: str
) -> None:
    """Stopper hvis datasettet har en dimensjon vi verken valgte i eller fordeler på.

    En slik dimensjon summeres stilltiende av beregningen. Det er nøyaktig
    feilen som oppstår hvis en tabell har en regnskapsomfang-dimensjon vi ikke
    kjenner: kommune og konsern legges sammen, og alle tall blir for høye uten
    at noe feiler. Sjekken er generell, så den fanger også dimensjoner SSB
    innfører senere.
    """
    ider = list(datasett.get("id", []))
    storrelser = list(datasett.get("size", []))
    for ident, storrelse in zip(ider, storrelser):
        if ident in handtert or storrelse <= 1:
            continue
        kategori = datasett["dimension"][ident].get("category", {})
        etiketter = kategori.get("label") or {}
        verdier = list(etiketter.items())[:10] or list(kategori.get("index", []))[:10]
        raise UttrekkFeil(
            f"{navn}: dimensjonen {ident!r} har {storrelse} verdier, og uttrekket "
            f"verken velger i den eller fordeler på den. Beregningen ville summert "
            f"over den og dobbelttelt. Verdier: {verdier}. "
            "Legg dimensjonen inn i spørringen i pipeline.py, eller i kodesok i "
            "config.yaml hvis det skal velges én verdi."
        )


def _rens(utvalg: dict[str, Any]) -> dict[str, Any]:
    """Fjerner dimensjoner som ikke finnes i tabellen.

    Et kodevalg med tom dimensjon betyr at dimensjonen ikke er aktuell, for
    eksempel en sektordimensjon som er bakt inn i tabellens definisjon. Den
    skal da ikke med i spørringen.
    """
    return {dimensjon: verdier for dimensjon, verdier in utvalg.items() if dimensjon}


def _dimkode(metadata: Mapping[str, Any], kandidater: Sequence[str]) -> str:
    """Finner dimensjonskode i metadata (ikke i datasettet)."""
    from .ssb_api import dimensjonsverdier

    for kandidat in kandidater:
        for kode, tekst, _ in dimensjonsverdier(metadata):
            if kandidat.lower() in kode.lower() or kandidat.lower() in tekst.lower():
                return kode
    raise UttrekkFeil(
        f"Fant ingen dimensjon blant {list(kandidater)}. "
        f"Tabellen har: {[k for k, _, _ in dimensjonsverdier(metadata)]}"
    )


def les_frosset(rot: Path, aar: int) -> dict[str, Any]:
    grunnlag = {}
    for navn in ("kostnad", "forvaltning", "areal", "energi", "kodevalg"):
        innhold = utdata.les_grunnlag(rot, aar, navn)
        if innhold is None:
            raise UttrekkFeil(
                f"Mangler frosset grunnlag for {aar}/{navn}. Kjør grunnlag.yml for årgangen."
            )
        grunnlag[navn] = innhold["kodevalg"] if navn == "kodevalg" else innhold
    return grunnlag


# -- Bygging av rader -------------------------------------------------------


def bygg_rader(
    grunnlag: Mapping[str, Any], konfig: Mapping[str, Any], aar: int
) -> tuple[dict[str, list[Kommunerad]], dict[str, list[Energirad]]]:
    """Setter sammen kroner, kWh og areal til rader per kommune og funksjon."""
    import re

    faktor_kr = float(konfig["enheter"]["kroner_faktor"])
    faktor_kwh = float(konfig["enheter"]["energi_faktor"])
    faktor_areal = float(konfig["enheter"]["areal_faktor"])
    funksjoner = list(konfig["funksjoner"])
    # Regionsdimensjonen inneholder også landet, fylker og KOSTRA-grupper.
    # Aggregatene skal aldri inn i kommuneutvalget: de ville telt med i både
    # medianen og det arealvektede snittet.
    er_kommune = re.compile(konfig["region"]["kommune_monster"]).match

    # Areal
    areal_ds = grunnlag["areal"]
    d_reg = finn_dim(areal_ds, DIM_REGION)
    d_fun = finn_dim(areal_ds, DIM_FUNKSJON)
    sjekk_ingen_ufrie_dimensjoner(areal_ds, [d_reg, d_fun], "areal")
    areal: dict[tuple[str, str], float] = {}
    navn: dict[str, str] = {}
    for rad in parse_jsonstat2(areal_ds):
        kommune = rad.koder[d_reg]
        if not er_kommune(kommune):
            continue
        funksjon = rad.koder[d_fun]
        navn[kommune] = rad.etiketter[d_reg]
        if rad.verdi is not None:
            areal[(kommune, funksjon)] = rad.verdi * faktor_areal
    portefolje: dict[str, float] = {}
    for (kommune, funksjon), verdi in areal.items():
        if funksjon in funksjoner:
            portefolje[kommune] = portefolje.get(kommune, 0.0) + verdi

    # Kostnad
    kost_ds = grunnlag["kostnad"]
    d_reg_k = finn_dim(kost_ds, DIM_REGION)
    d_fun_k = finn_dim(kost_ds, DIM_FUNKSJON)
    d_art = finn_dim(kost_ds, DIM_ART)
    sjekk_ingen_ufrie_dimensjoner(kost_ds, [d_reg_k, d_fun_k, d_art], "kostnad")
    kodevalg = {v["formaal"]: v["kode"] for v in grunnlag["kodevalg"]}
    art_til_ledd = {kodevalg[f"art:{ledd}"]: ledd for ledd in KOSTNADSLEDD if f"art:{ledd}" in kodevalg}
    kroner: dict[tuple[str, str], dict[str, float | None]] = {}
    for rad in parse_jsonstat2(kost_ds):
        ledd = art_til_ledd.get(rad.koder[d_art])
        if ledd is None:
            continue
        if not er_kommune(rad.koder[d_reg_k]):
            continue
        nokkel = (rad.koder[d_reg_k], rad.koder[d_fun_k])
        kroner.setdefault(nokkel, {})[ledd] = None if rad.verdi is None else rad.verdi * faktor_kr

    # Forvaltning
    forv_ds = grunnlag["forvaltning"]
    d_reg_f = finn_dim(forv_ds, DIM_REGION)
    d_art_f = finn_dim(forv_ds, DIM_ART, paakrevd=False)
    onsket_art = kodevalg.get(f"art:{konfig['forvaltning']['art']}")
    forvaltning: dict[str, float | None] = {}
    per_art: dict[str, tuple[str, int]] = {}
    for rad in parse_jsonstat2(forv_ds):
        if not er_kommune(rad.koder[d_reg_f]):
            continue
        art = rad.koder.get(d_art_f) if d_art_f else None
        if art is not None and rad.verdi:
            etikett = rad.etiketter.get(d_art_f, art)
            antall = per_art.get(art, (etikett, 0))[1]
            per_art[art] = (etikett, antall + 1)
        if d_art_f and onsket_art and art != onsket_art:
            continue
        forvaltning[rad.koder[d_reg_f]] = None if rad.verdi is None else rad.verdi * faktor_kr

    # Energi
    energi_ds = grunnlag["energi"]
    d_reg_e = finn_dim(energi_ds, DIM_REGION)
    d_fun_e = finn_dim(energi_ds, DIM_FUNKSJON)
    d_vare = finn_dim(energi_ds, DIM_ENERGIVARE, paakrevd=False)
    sjekk_ingen_ufrie_dimensjoner(
        energi_ds, [d for d in (d_reg_e, d_fun_e, d_vare) if d], "energi"
    )
    kwh: dict[tuple[str, str], dict[str, float]] = {}
    for rad in parse_jsonstat2(energi_ds):
        if rad.verdi is None or not er_kommune(rad.koder[d_reg_e]):
            continue
        vare = rad.etiketter.get(d_vare, "samlet") if d_vare else "samlet"
        nokkel = (rad.koder[d_reg_e], rad.koder[d_fun_e])
        kwh.setdefault(nokkel, {})[vare] = kwh.setdefault(nokkel, {}).get(vare, 0.0) + rad.verdi * faktor_kwh

    # Nevneren er kommunene som faktisk finnes i årgangen, ikke alle koder som
    # ser ut som kommunenumre. Regionsdimensjonen inneholder også kommuner som
    # ble slått sammen i 2020, og de er tomme i nyere årganger. Deles det på
    # dem, ser dekningen halvparten så god ut som den er.
    aktive = {kommune for (kommune, _), verdi in areal.items() if verdi}

    # Funksjon 121 skal finnes for de aller fleste kommuner. Gjør den ikke det,
    # er arten eller funksjonen feil, og forvaltningsleddet blir et tomt tall
    # som ingen oppdager før nettsiden er publisert.
    med_forvaltning = sum(1 for kommune in aktive if forvaltning.get(kommune))
    dekning = med_forvaltning / max(len(aktive), 1)
    minste = float(konfig["forvaltning"].get("minste_dekning", 0.6))
    # Også et helt tomt forvaltningsledd skal stoppe jobben. Det er nettopp
    # tilfellet der arten er feil, og det ville ellers passert i stillhet.
    if dekning < minste:
        if per_art:
            linjer = "\n".join(
                f"    {kode} = {etikett}  ({antall} kommuner med tall)"
                for kode, (etikett, antall) in sorted(
                    per_art.items(), key=lambda kv: -kv[1][1]
                )
            )
            funnet = (
                f"\nFunksjon {konfig['forvaltning']['funksjon']} publiseres med "
                f"disse artene:\n{linjer}\n"
                "Sett `forvaltning.art` i config.yaml til leddet som peker på "
                "riktig kode. Er ingen av dem en ren aktivitetsart, må valget "
                "dokumenteres i METODE.md: korrigerte brutto driftsutgifter "
                "inneholder avskrivninger og mva-utgift."
            )
        else:
            funnet = (
                f"\nFunksjon {konfig['forvaltning']['funksjon']} har ingen tall "
                "i det hele tatt i denne tabellen. Forvaltningsleddet må hentes "
                "et annet sted."
            )
        raise UttrekkFeil(
            f"Forvaltning (funksjon {konfig['forvaltning']['funksjon']}, art "
            f"{konfig['forvaltning']['art']}) finnes for {med_forvaltning} av "
            f"{len(aktive)} kommuner med areal i {aar}, altså {dekning:.0%}. "
            f"Kravet er {minste:.0%}." + funnet
        )
    logg.info("Forvaltning funnet for %.0f %% av kommunene", dekning * 100)

    # Radene bygges for kommuner som har rapportert noe i årgangen, enten
    # areal eller kroner. En kommune som har ført kostnader men ikke areal skal
    # med, og få flagget `areal_mangler` - ikke forsvinne i stillhet.
    med_kroner = {
        kommune
        for (kommune, _), poster in kroner.items()
        if any(v is not None for v in poster.values())
    }
    kommuner = sorted(aktive | med_kroner)
    # Får vi nesten ingen kommuner med areal, har uttrekket kommet tilbake på
    # feil nivå, og alt som følger ville vært regnet på noen få aggregater.
    minste_kommuner = int(konfig["region"].get("minste_antall_kommuner", 300))
    if len(kommuner) < minste_kommuner:
        raise UttrekkFeil(
            f"Bare {len(kommuner)} kommuner i uttrekket for {aar}, kravet er "
            f"{minste_kommuner}. Norge har rundt 350. Kontroller at "
            "regionsdimensjonen leverer kommuner og ikke bare "
            f"aggregater. Kodene som ble lest: {sorted(set(k for k, _ in areal))[:12]}"
        )
    logg.info("%s: %d kommuner i grunnlaget", aar, len(kommuner))
    kostnadsrader: dict[str, list[Kommunerad]] = {f: [] for f in funksjoner}
    energirader: dict[str, list[Energirad]] = {f: [] for f in funksjoner}
    for funksjon in funksjoner:
        for kommune in kommuner:
            beløp = kroner.get((kommune, funksjon), {})
            kostnadsrader[funksjon].append(
                Kommunerad(
                    kommune=kommune,
                    kommunenavn=navn.get(kommune, kommune),
                    aar=aar,
                    funksjon=funksjon,
                    areal=areal.get((kommune, funksjon)),
                    portefoljeareal=portefolje.get(kommune),
                    kroner={ledd: beløp.get(ledd) for ledd in KOSTNADSLEDD},
                    forvaltning_kroner=forvaltning.get(kommune),
                )
            )
            energirader[funksjon].append(
                Energirad(
                    kommune=kommune,
                    kommunenavn=navn.get(kommune, kommune),
                    aar=aar,
                    funksjon=funksjon,
                    areal=areal.get((kommune, funksjon)),
                    kwh=dict(kwh.get((kommune, funksjon), {})),
                    energiutgift_kr=beløp.get("energi"),
                )
            )
    return kostnadsrader, energirader


# -- Beregning for alle årganger -------------------------------------------


def beregn_alle(
    rot: Path,
    konfig: Mapping[str, Any],
    aargang: Sequence[int],
    terskler: Mapping[str, Any] | None = None,
    skriv_revisjon: bool = True,
) -> dict[str, Any]:
    """Leser frosset grunnlag, beregner alt og returnerer normtall-strukturen."""
    funksjoner = dict(konfig["funksjoner"])
    vist = list(aargang)[-int(konfig["aargang"]["antall_vist"]) :]
    kr_naer = int(konfig["avrunding"]["kroner_naermeste"])
    kwh_naer = int(konfig["avrunding"]["kwh_naermeste"])

    kost: dict[int, dict[str, beregning.Funksjonsaar]] = {}
    ener: dict[int, dict[str, energimodul.Energiaar]] = {}
    kodevalg: list[dict[str, Any]] = []

    for aar in aargang:
        grunnlag = les_frosset(rot, aar)
        kodevalg = grunnlag["kodevalg"]
        kostnadsrader, energirader = bygg_rader(grunnlag, konfig, aar)
        kost[aar] = {}
        ener[aar] = {}
        for funksjon in funksjoner:
            kost[aar][funksjon] = beregning.beregn_funksjonsaar(
                kostnadsrader[funksjon], dict(konfig), dict(terskler) if terskler else None
            )
            ener[aar][funksjon] = energimodul.beregn_energiaar(
                energirader[funksjon], dict(konfig), dict(terskler) if terskler else None
            )
            if skriv_revisjon:
                utdata.skriv_revisjonsfil(
                    rot, aar, funksjon, kostnadsrader[funksjon], energirader[funksjon]
                )

    ut_funksjoner: dict[str, Any] = {}
    for funksjon, funksjonsnavn in funksjoner.items():
        siste = vist[-1]
        siste_kost = kost[siste][funksjon]
        siste_energi = ener[siste][funksjon]

        normtall = {}
        for post, punkt in siste_kost.forankret.items():
            if post == "forvaltning":
                continue  # publiseres én gang, på porteføljenivå
            normtall[post] = utdata.avrund_tre_punkt(punkt, kr_naer)
        egne = {
            post: {
                "n": f.n,
                "p10": utdata.verdipar(f.p10, kr_naer),
                "median": utdata.verdipar(f.median, kr_naer),
                "p90": utdata.verdipar(f.p90, kr_naer),
                "snitt": utdata.verdipar(f.snitt, kr_naer),
                "trimmet_snitt": utdata.verdipar(f.trimmet_snitt, kr_naer),
                "arealvektet_snitt": utdata.verdipar(f.arealvektet, kr_naer),
            }
            for post, f in siste_kost.egne.items()
        }

        # Historikk per post, kostnad
        hist: dict[str, Any] = {}
        kjerne_per_aar = {a: kost[a][funksjon].kommuner_kjerne for a in vist}
        arealer_per_aar = {
            a: {r.kommune: r.areal or 0.0 for r in kost[a][funksjon].rader} for a in vist
        }
        for post in beregning.POSTER:
            verdier = {
                a: {
                    r.kommune: r.per_m2[post]
                    for r in kost[a][funksjon].rader
                    if r.kommune in set(kost[a][funksjon].kommuner_kjerne) and post in r.per_m2
                }
                for a in vist
            }
            if not any(verdier.values()):
                continue
            hist[post] = historikk.bygg_historikk(
                verdier, kjerne_per_aar, funksjon, post, konfig.get("brudd") or [], arealer_per_aar
            )

        # Historikk, energi
        energi_kjerne = {a: ener[a][funksjon].kommuner_kjerne for a in vist}
        energi_verdier = {
            a: {
                r.kommune: r.kwh_m2
                for r in ener[a][funksjon].rader
                if r.kommune in set(ener[a][funksjon].kommuner_kjerne) and r.kwh_m2 is not None
            }
            for a in vist
        }
        energi_arealer = {
            a: {r.kommune: r.areal or 0.0 for r in ener[a][funksjon].rader} for a in vist
        }
        energihistorikk = historikk.bygg_historikk(
            energi_verdier, energi_kjerne, funksjon, "kwh_per_m2",
            konfig.get("brudd") or [], energi_arealer,
        )

        ut_funksjoner[funksjon] = {
            "navn": funksjonsnavn,
            "kostnad": {
                "normtall_forankret": normtall,
                "fordeling_egen": egne,
                "medianandeler_av_dv": siste_kost.medianandeler,
                "standard_sentralmaal_vedlikehold": "trimmet_snitt",
                "n_grunnlag": siste_kost.n_grunnlag,
                "n_kjerne": siste_kost.n_kjerne,
                "frafall_per_aarsak": siste_kost.frafall,
                "historikk": hist,
            },
            "energi": {
                "siste": _energi_ut(siste_energi, kwh_naer),
                "historikk": energihistorikk,
                "per_aargang": {str(a): _energi_ut(ener[a][funksjon], kwh_naer) for a in vist},
            },
        }

    # Forvaltning er ett porteføljetall. Det beregnes én gang, ikke som seks
    # nesten like tall som bare skiller seg fordi kjerneutvalget varierer.
    forste_funksjon = next(iter(funksjoner))
    forvaltning_per_aar = {
        a: beregning.forvaltning_per_kommune(kost[a][forste_funksjon].rader) for a in vist
    }
    fordeling_forvaltning, kjerne_forvaltning = beregning.beregn_forvaltning(
        forvaltning_per_aar[vist[-1]], dict(konfig)
    )
    kjerne_forvaltning_per_aar = {
        a: beregning.beregn_forvaltning(forvaltning_per_aar[a], dict(konfig))[1] for a in vist
    }
    forvaltning_blokk = {
        "forklaring": (
            "Funksjon 121 dekker forvaltning av hele eiendomsmassen og har ikke eget "
            "areal. Leddet er derfor identisk for alle bygningstyper og publiseres "
            "som ett porteføljetall, delt på eid areal for alle seks funksjonene."
        ),
        "n_kjerne": fordeling_forvaltning.n if fordeling_forvaltning else 0,
        "tre_punkt": utdata.avrund_tre_punkt(
            {
                "lav": fordeling_forvaltning.p10 if fordeling_forvaltning else None,
                "sannsynlig": fordeling_forvaltning.median if fordeling_forvaltning else None,
                "hoy": fordeling_forvaltning.p90 if fordeling_forvaltning else None,
            },
            kr_naer,
        ),
        "historikk": historikk.bygg_historikk(
            forvaltning_per_aar,
            kjerne_forvaltning_per_aar,
            "121",
            "forvaltning",
            konfig.get("brudd") or [],
        ),
    }

    datakvalitet = {
        "per_aargang": {
            str(a): {
                "kostnad": {
                    f: {
                        "n_grunnlag": kost[a][f].n_grunnlag,
                        "n_kjerne": kost[a][f].n_kjerne,
                        "frafall_per_aarsak": kost[a][f].frafall,
                    }
                    for f in funksjoner
                },
                "energi": {
                    f: {
                        "n_grunnlag": ener[a][f].n_grunnlag,
                        "n_kjerne": ener[a][f].n_kjerne,
                        "frafall_per_aarsak": ener[a][f].frafall,
                        "implisitt_energipris": ener[a][f].implisitt_pris,
                    }
                    for f in funksjoner
                },
            }
            for a in vist
        }
    }

    datakvalitet["forvaltning"] = {
        "n_kjerne": forvaltning_blokk["n_kjerne"],
        "n_grunnlag": len(forvaltning_per_aar[vist[-1]]),
    }

    normtall = utdata.bygg_normtall(
        konfig=konfig,
        aargang_frosne=list(aargang),
        aargang_vist=vist,
        kodevalg=kodevalg,
        funksjoner=ut_funksjoner,
        datakvalitet=datakvalitet,
        forelopig=bool(konfig["aargang"].get("tillat_forelopig")),
    )
    normtall["forvaltning"] = forvaltning_blokk
    return normtall


def _energi_ut(e: energimodul.Energiaar, kwh_naer: int) -> dict[str, Any]:
    fordeling = e.kwh_m2
    return {
        "aargang": e.aar,
        "n_kjerne": e.n_kjerne,
        "kwh_per_m2": {
            "lav": utdata.verdipar(fordeling.p10 if fordeling else None, kwh_naer),
            "sannsynlig": utdata.verdipar(fordeling.median if fordeling else None, kwh_naer),
            "hoy": utdata.verdipar(fordeling.p90 if fordeling else None, kwh_naer),
            "arealvektet_snitt": utdata.verdipar(fordeling.arealvektet if fordeling else None, kwh_naer),
        },
        "energivarefordeling": e.energivarer,
        "fornybarandel_median": e.fornybarandel_median,
        "implisitt_energipris": e.implisitt_pris,
        "temperaturkorrigert": False,
    }
