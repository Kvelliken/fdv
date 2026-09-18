"""Energibruk per m² og kryssvalidering mot energiutgifter.

Samme metode som kostnadssiden: kWh fra skjema 35A/35B delt på eid areal fra
skjema 34A/34B, per funksjon, med log-Tukey og tre-punktsmodell.

Feilmodusen er en annen enn på kostnadssiden. Der oppstår nuller fordi
kostnaden er ført et annet sted. Her ber SSB rapportøren anslå tall når
fullstendige opplysninger mangler, så nuller er sjeldnere og estimater
vanligere. Flaggene fanger derfor urimelige nivåer, ikke bare hull.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .beregning import Fordeling, arealvektet, kvantil, log_tukey_gjerde, median, snitt, trimmet_snitt

# Grove ankerverdier fra SSBs undersøkelse av tjenesteytende næringer (2011).
# Brukes til størrelsesordenskontroll i loggen, aldri som fasit.
ANKERVERDIER_KWH_M2 = {
    "221": 177,  # barnehage
    "222": 150,  # barne- og videregående skole
    "261": 375,  # sykehus, brukes som øvre anker for institusjon
}


@dataclass
class Energirad:
    kommune: str
    kommunenavn: str
    aar: int
    funksjon: str
    areal: float | None = None
    kwh: dict[str, float] = field(default_factory=dict)  # energivare -> kWh
    energiutgift_kr: float | None = None
    flagg: list[str] = field(default_factory=list)
    kwh_m2: float | None = None
    andeler: dict[str, float] = field(default_factory=dict)
    fornybarandel: float | None = None
    implisitt_pris: float | None = None

    @property
    def sum_kwh(self) -> float | None:
        if not self.kwh:
            return None
        return sum(v for v in self.kwh.values() if v is not None)


def klassifiser_fornybar(navn: str, konfig: dict[str, Any]) -> bool | None:
    """Sier om en energivare regnes som fornybar. None = ukjent vare."""
    n = navn.lower()
    for nokkel in konfig["energivarer"]["fornybar"]:
        if nokkel in n:
            return True
    for nokkel in konfig["energivarer"]["ikke_fornybar"]:
        if nokkel in n:
            return False
    return None


def sett_energiflagg(rad: Energirad, konfig: dict[str, Any]) -> list[str]:
    t = konfig["terskler"]
    flagg: list[str] = []

    if rad.areal is None or rad.areal <= 0:
        flagg.append("areal_mangler")
    elif rad.areal < t["areal_for_lite_m2"]:
        flagg.append("areal_for_lite")

    sum_kwh = rad.sum_kwh
    if sum_kwh is None:
        flagg.append("kwh_mangler")
    elif sum_kwh <= 0:
        if rad.areal and rad.areal > 0:
            flagg.append("kwh_null")
        else:
            flagg.append("kwh_mangler")

    if rad.kwh_m2 is not None:
        if rad.kwh_m2 < t["kwh_urimelig_lav"]:
            flagg.append("kwh_urimelig_lav")
        elif rad.kwh_m2 > t["kwh_urimelig_hoy"]:
            flagg.append("kwh_urimelig_hoy")

    if rad.implisitt_pris is not None:
        gr = t["implisitt_energipris"]
        if not (gr["lav"] <= rad.implisitt_pris <= gr["hoy"]):
            # Ikke blokkerende: dette er en kvalitetsindikator som publiseres,
            # og avviket kan like gjerne ligge på kronesiden som på kWh-siden.
            flagg.append("implisitt_pris_utenfor")

    return flagg


def beregn_rad(rad: Energirad, konfig: dict[str, Any]) -> None:
    """Fyller kwh_m2, andeler, fornybarandel og implisitt pris."""
    sum_kwh = rad.sum_kwh
    if rad.areal and rad.areal > 0 and sum_kwh is not None:
        rad.kwh_m2 = sum_kwh / rad.areal
    if sum_kwh and sum_kwh > 0:
        rad.andeler = {vare: verdi / sum_kwh for vare, verdi in rad.kwh.items() if verdi is not None}
        fornybar = 0.0
        kjent = 0.0
        for vare, verdi in rad.kwh.items():
            klasse = klassifiser_fornybar(vare, konfig)
            if klasse is None:
                continue
            kjent += verdi
            if klasse:
                fornybar += verdi
        rad.fornybarandel = (fornybar / kjent) if kjent > 0 else None
    if rad.kwh_m2 and rad.kwh_m2 > 0 and rad.energiutgift_kr is not None and rad.areal:
        kr_m2 = rad.energiutgift_kr / rad.areal
        rad.implisitt_pris = kr_m2 / rad.kwh_m2
    rad.flagg = sett_energiflagg(rad, konfig)


@dataclass
class Energiaar:
    funksjon: str
    aar: int
    n_grunnlag: int
    n_kjerne: int
    frafall: dict[str, int]
    kwh_m2: Fordeling | None
    energivarer: dict[str, float]          # medianandel per vare
    fornybarandel_median: float | None
    implisitt_pris: dict[str, float]       # fordeling som kvalitetsindikator
    kommuner_kjerne: list[str]
    rader: list[Energirad] = field(default_factory=list)

    def som_dict(self) -> dict[str, Any]:
        return {
            "funksjon": self.funksjon,
            "aargang": self.aar,
            "n_grunnlag": self.n_grunnlag,
            "n_kjerne": self.n_kjerne,
            "frafall_per_aarsak": self.frafall,
            "kwh_per_m2": self.kwh_m2.som_dict() if self.kwh_m2 else None,
            "energivarefordeling": self.energivarer,
            "fornybarandel_median": self.fornybarandel_median,
            "implisitt_energipris": self.implisitt_pris,
            "temperaturkorrigert": False,
            "gratisvarme_inkludert": False,
            "kommuner_kjerne": self.kommuner_kjerne,
        }


def beregn_energiaar(
    rader: list[Energirad], konfig: dict[str, Any], terskler: dict[str, Any] | None = None
) -> Energiaar:
    if terskler is not None:
        konfig = {**konfig, "terskler": terskler}
    blokkerende = konfig["blokkerende_flagg_energi"]
    k = float(konfig["terskler"]["tukey_k"])
    trim = float(konfig["terskler"]["trimmet_snitt_andel"])

    for rad in rader:
        beregn_rad(rad, konfig)

    kandidater = [
        r for r in rader if not any(f in blokkerende for f in r.flagg) and r.kwh_m2 is not None
    ]
    nedre, ovre = log_tukey_gjerde([r.kwh_m2 for r in kandidater], k)
    for rad in kandidater:
        if rad.kwh_m2 < nedre or rad.kwh_m2 > ovre:
            rad.flagg.append("kwh_uteligger")

    kjerne = [
        r for r in rader if not any(f in blokkerende for f in r.flagg) and r.kwh_m2 is not None
    ]

    frafall: dict[str, int] = {}
    for rad in rader:
        for f in rad.flagg:
            if f in blokkerende:
                frafall[f] = frafall.get(f, 0) + 1

    fordeling = None
    if len(kjerne) >= 2:
        verdier = [r.kwh_m2 for r in kjerne]
        arealer = [r.areal for r in kjerne]
        fordeling = Fordeling(
            post="kwh_per_m2",
            n=len(verdier),
            p10=kvantil(verdier, 0.10),
            median=median(verdier),
            p90=kvantil(verdier, 0.90),
            snitt=snitt(verdier),
            trimmet_snitt=trimmet_snitt(verdier, trim),
            arealvektet=arealvektet([v * a for v, a in zip(verdier, arealer)], arealer),
        )

    varer: dict[str, float] = {}
    alle_varer = sorted({vare for r in kjerne for vare in r.andeler})
    for vare in alle_varer:
        andeler = [r.andeler.get(vare, 0.0) for r in kjerne]
        if andeler:
            varer[vare] = median(andeler)
    # Medianandelene normaliseres slik at de summerer til 1.
    sum_andeler = sum(varer.values())
    if sum_andeler > 0:
        varer = {v: a / sum_andeler for v, a in varer.items()}

    fornybar = [r.fornybarandel for r in kjerne if r.fornybarandel is not None]
    priser = [r.implisitt_pris for r in kjerne if r.implisitt_pris is not None]
    gr = konfig["terskler"]["implisitt_energipris"]
    pris = {}
    if priser:
        pris = {
            "n": len(priser),
            "p10": kvantil(priser, 0.10),
            "median": median(priser),
            "p90": kvantil(priser, 0.90),
            "andel_utenfor_intervall": sum(
                1 for p in priser if not (gr["lav"] <= p <= gr["hoy"])
            )
            / len(priser),
            "intervall": [gr["lav"], gr["hoy"]],
        }

    return Energiaar(
        funksjon=rader[0].funksjon if rader else "",
        aar=rader[0].aar if rader else 0,
        n_grunnlag=len(rader),
        n_kjerne=len(kjerne),
        frafall=dict(sorted(frafall.items())),
        kwh_m2=fordeling,
        energivarer=varer,
        fornybarandel_median=median(fornybar) if fornybar else None,
        implisitt_pris=pris,
        kommuner_kjerne=sorted(r.kommune for r in kjerne),
        rader=rader,
    )


def implisitt_pris_landsnivaa(rader: Sequence[Energirad]) -> float | None:
    """sum(energiutgifter) / sum(kWh). Blokkerende test på landsnivå.

    Fanger at kostnads- og energiuttrekkene er hentet for ulik årgang, ulik
    sektor eller ulikt arealgrunnlag: de to kommer fra hvert sitt skjema, så
    et avvik her isolerer hvilken side feilen ligger på.
    """
    sum_kr = sum(r.energiutgift_kr for r in rader if r.energiutgift_kr is not None)
    sum_kwh = sum(r.sum_kwh or 0.0 for r in rader)
    if sum_kwh <= 0:
        return None
    return sum_kr / sum_kwh
