"""Kostnadsberegning: kr/m², kvalitetsflagg, uteliggere og tre-punktsmodell.

Regelverket denne modulen håndhever:

* Kostnadskolonnene er nøstet. Drift = energi + renhold + øvrig drift.
  Bare drift og vedlikehold kan summeres. Øvrig drift er en restpost.
* Flagg settes på råstørrelsene, ikke på forholdstallet, slik at en billig
  kommune skilles fra en kommune som ikke har rapportert kostnaden.
* Tukey-gjerdet regnes i log-rom, og først etter at de øvrige flaggene er
  satt. Ellers trekker rapporteringsfeilene kvartilene nedover og beskytter
  seg selv.
* Lav/sannsynlig/høy settes på D+V og brytes ned med medianandeler.
  Delpostenes egne P10/P90 kan ikke summeres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# Delpostene av drift, i den rekkefølgen de vises.
DELPOSTER = ("energi", "renhold", "ovrig_drift")
# Alle poster som publiseres per bygningstype.
POSTER = ("forvaltning", "energi", "renhold", "ovrig_drift", "vedlikehold", "dv", "fdv")


# -- Statistikk -------------------------------------------------------------


def kvantil(verdier: Sequence[float], p: float) -> float:
    """Lineært interpolert kvantil (samme definisjon som numpy og R type 7)."""
    if not verdier:
        raise ValueError("Tomt utvalg")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p utenfor [0,1]: {p}")
    s = sorted(verdier)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * p
    under = math.floor(pos)
    over = math.ceil(pos)
    if under == over:
        return float(s[int(pos)])
    return float(s[under] + (s[over] - s[under]) * (pos - under))


def median(verdier: Sequence[float]) -> float:
    return kvantil(verdier, 0.5)


def snitt(verdier: Sequence[float]) -> float:
    return sum(verdier) / len(verdier)


def trimmet_snitt(verdier: Sequence[float], andel: float) -> float:
    """Aritmetisk snitt etter at `andel` er fjernet i hver hale.

    Standard sentralmål for vedlikehold: vedlikehold er periodisk, så
    medianen fanger mange kommuner i en lavperiode og undervurderer
    årsnivået systematisk.
    """
    if not verdier:
        raise ValueError("Tomt utvalg")
    s = sorted(verdier)
    kutt = int(len(s) * andel)
    kjerne = s[kutt : len(s) - kutt] or s
    return sum(kjerne) / len(kjerne)


def arealvektet(tellere: Sequence[float], arealer: Sequence[float]) -> float:
    """sum(kroner) / sum(areal). Størrelsen som avstemmes mot landstall."""
    sum_areal = sum(arealer)
    if sum_areal <= 0:
        raise ValueError("Samlet areal er null")
    return sum(tellere) / sum_areal


def log_tukey_gjerde(verdier: Iterable[float], k: float = 1.5) -> tuple[float, float]:
    """Tukey-gjerde regnet på ln(x), transformert tilbake.

    Fordelingene av kr/m² er lognormale. Et gjerde i lineært rom kutter for
    hardt i høyhalen og for mykt i lavhalen. Lavhalen er nesten alltid
    rapporteringsfeil, høyhalen er ofte ekte.
    """
    positive = [math.log(v) for v in verdier if v is not None and v > 0]
    if len(positive) < 4:
        return (0.0, math.inf)
    q1 = kvantil(positive, 0.25)
    q3 = kvantil(positive, 0.75)
    iqr = q3 - q1
    if iqr <= 1e-12:
        # Degenerert fordeling: alle verdier praktisk talt like. Et gjerde her
        # ville klassifisert flyttallsstøy som uteliggere.
        return (0.0, math.inf)
    # Marginen tar høyde for at exp(ln(x)) ikke er eksakt lik x.
    return (math.exp(q1 - k * iqr) * (1 - 1e-9), math.exp(q3 + k * iqr) * (1 + 1e-9))


# -- Datamodell -------------------------------------------------------------


@dataclass
class Kommunerad:
    """Én kommune, ett år, én bygningsfunksjon. Alle beløp i kroner, ikke 1000 kr."""

    kommune: str
    kommunenavn: str
    aar: int
    funksjon: str
    areal: float | None = None
    portefoljeareal: float | None = None
    kroner: dict[str, float | None] = field(default_factory=dict)
    forvaltning_kroner: float | None = None
    flagg: list[str] = field(default_factory=list)
    per_m2: dict[str, float] = field(default_factory=dict)

    # -- avledede størrelser --

    def beregn_per_m2(self) -> None:
        self.per_m2 = {}
        areal = self.areal
        if not areal or areal <= 0:
            return
        drift = self.kroner.get("drift")
        energi = self.kroner.get("energi")
        renhold = self.kroner.get("renhold")
        vedlikehold = self.kroner.get("vedlikehold")

        if drift is not None:
            self.per_m2["drift"] = drift / areal
        if energi is not None:
            self.per_m2["energi"] = energi / areal
        if renhold is not None:
            self.per_m2["renhold"] = renhold / areal
        if vedlikehold is not None:
            self.per_m2["vedlikehold"] = vedlikehold / areal
        if None not in (drift, energi, renhold):
            self.per_m2["ovrig_drift"] = (drift - energi - renhold) / areal
        if None not in (drift, vedlikehold):
            self.per_m2["dv"] = (drift + vedlikehold) / areal

        # Forvaltning er et porteføljetall: funksjon 121 har ikke eget areal,
        # og deles derfor på eid areal for alle seks funksjonene. Leddet blir
        # identisk for alle bygningstyper i samme kommune.
        if self.forvaltning_kroner is not None and self.portefoljeareal:
            forvaltning = self.forvaltning_kroner / self.portefoljeareal
            self.per_m2["forvaltning"] = forvaltning
            if "dv" in self.per_m2:
                self.per_m2["fdv"] = self.per_m2["dv"] + forvaltning

    @property
    def ren(self) -> bool:
        return not self.flagg


def sett_flagg(rad: Kommunerad, konfig: dict[str, Any]) -> list[str]:
    """Kvalitetsflagg på råstørrelser. Uteliggerflagg settes senere."""
    t = konfig["terskler"]
    flagg: list[str] = []

    if rad.areal is None or rad.areal <= 0:
        flagg.append("areal_mangler")
    elif rad.areal < t["areal_for_lite_m2"]:
        flagg.append("areal_for_lite")

    drift = rad.kroner.get("drift")
    if drift is None:
        flagg.append("drift_mangler")
    elif drift <= 0:
        flagg.append("drift_null")

    vedlikehold = rad.kroner.get("vedlikehold")
    if vedlikehold is not None and vedlikehold < 0:
        flagg.append("vedlikehold_negativ")

    energi = rad.kroner.get("energi")
    renhold = rad.kroner.get("renhold")
    if None not in (drift, energi, renhold) and (drift - energi - renhold) < 0:
        flagg.append("drift_mindre_enn_delposter")

    p = rad.per_m2
    if "drift" in p and p["drift"] < t["drift_urimelig_lav_kr_m2"]:
        flagg.append("drift_urimelig_lav")
    if "energi" in p and p["energi"] < t["energi_urimelig_lav_kr_m2"]:
        flagg.append("energi_urimelig_lav")
    if "renhold" in p and p["renhold"] < t["renhold_urimelig_lav_kr_m2"]:
        flagg.append("renhold_urimelig_lav")

    return flagg


def _blokkerer(flagg: Sequence[str], blokkerende: Sequence[str]) -> bool:
    return any(f in blokkerende for f in flagg)


# -- Resultatstrukturer -----------------------------------------------------


@dataclass
class Fordeling:
    post: str
    n: int
    p10: float
    median: float
    p90: float
    snitt: float
    trimmet_snitt: float
    arealvektet: float

    def som_dict(self) -> dict[str, Any]:
        return {
            "post": self.post,
            "n": self.n,
            "p10": self.p10,
            "median": self.median,
            "p90": self.p90,
            "snitt": self.snitt,
            "trimmet_snitt": self.trimmet_snitt,
            "arealvektet_snitt": self.arealvektet,
        }


@dataclass
class Funksjonsaar:
    funksjon: str
    aar: int
    n_grunnlag: int
    n_kjerne: int
    frafall: dict[str, int]
    egne: dict[str, Fordeling]
    forankret: dict[str, dict[str, float]]
    medianandeler: dict[str, float]
    kommuner_kjerne: list[str]
    rader: list[Kommunerad] = field(default_factory=list)

    def som_dict(self) -> dict[str, Any]:
        return {
            "funksjon": self.funksjon,
            "aargang": self.aar,
            "n_grunnlag": self.n_grunnlag,
            "n_kjerne": self.n_kjerne,
            "frafall_per_aarsak": self.frafall,
            "fordeling_egen": {k: v.som_dict() for k, v in self.egne.items()},
            "forankret_paa_dv": self.forankret,
            "medianandeler_av_dv": self.medianandeler,
            "skal_summeres": "forankret_paa_dv",
            "kommuner_kjerne": self.kommuner_kjerne,
        }


def beregn_funksjonsaar(
    rader: list[Kommunerad],
    konfig: dict[str, Any],
    terskler: dict[str, Any] | None = None,
) -> Funksjonsaar:
    """Flagger, renser og beregner fordelingene for én funksjon og ett år.

    `terskler` lar sensitivitetskjøringen bytte ut terskelverdiene uten å røre
    resten av konfigurasjonen.
    """
    if terskler is not None:
        konfig = {**konfig, "terskler": terskler}
    blokkerende = konfig["blokkerende_flagg"]
    k = float(konfig["terskler"]["tukey_k"])
    trim = float(konfig["terskler"]["trimmet_snitt_andel"])

    for rad in rader:
        rad.beregn_per_m2()
        rad.flagg = sett_flagg(rad, konfig)

    # Gjerdet regnes på de radene som allerede har passert de øvrige flaggene.
    kandidater = [r for r in rader if not _blokkerer(r.flagg, blokkerende) and "dv" in r.per_m2]
    nedre, ovre = log_tukey_gjerde([r.per_m2["dv"] for r in kandidater], k)
    for rad in kandidater:
        verdi = rad.per_m2["dv"]
        if verdi < nedre:
            rad.flagg.append("DV_uteligger_lav")
        elif verdi > ovre:
            rad.flagg.append("DV_uteligger_hoy")

    kjerne = [r for r in rader if not _blokkerer(r.flagg, blokkerende) and "dv" in r.per_m2]

    frafall: dict[str, int] = {}
    for rad in rader:
        for f in rad.flagg:
            if f in blokkerende:
                frafall[f] = frafall.get(f, 0) + 1

    egne: dict[str, Fordeling] = {}
    for post in POSTER:
        verdier = [r.per_m2[post] for r in kjerne if post in r.per_m2]
        arealer = [r.areal for r in kjerne if post in r.per_m2 and r.areal]
        if len(verdier) < 2:
            continue
        # Forvaltning måles mot porteføljearealet, ikke funksjonsarealet.
        if post == "forvaltning":
            arealer = [r.portefoljeareal for r in kjerne if post in r.per_m2 and r.portefoljeareal]
        egne[post] = Fordeling(
            post=post,
            n=len(verdier),
            p10=kvantil(verdier, 0.10),
            median=median(verdier),
            p90=kvantil(verdier, 0.90),
            snitt=snitt(verdier),
            trimmet_snitt=trimmet_snitt(verdier, trim),
            arealvektet=arealvektet([v * a for v, a in zip(verdier, arealer)], arealer)
            if len(arealer) == len(verdier) and arealer
            else float("nan"),
        )

    forankret, andeler = forankre_paa_dv(kjerne, egne)

    return Funksjonsaar(
        funksjon=rader[0].funksjon if rader else "",
        aar=rader[0].aar if rader else 0,
        n_grunnlag=len(rader),
        n_kjerne=len(kjerne),
        frafall=dict(sorted(frafall.items())),
        egne=egne,
        forankret=forankret,
        medianandeler=andeler,
        kommuner_kjerne=sorted(r.kommune for r in kjerne),
        rader=rader,
    )


def forankre_paa_dv(
    kjerne: Sequence[Kommunerad], egne: dict[str, Fordeling]
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Bryter ned D+V-spennet med medianandeler.

    Delpostene er nesten ukorrelerte mellom kommuner. Summen av delpostenes
    egne P10 blir derfor lavere enn P10 for totalen, og summen av P90 høyere.
    Det settet som skal summeres er dette, ikke `egne`.
    """
    if "dv" not in egne:
        return {}, {}
    dv = egne["dv"]
    andeler: dict[str, float] = {}
    for post in ("energi", "renhold", "ovrig_drift", "vedlikehold"):
        forhold = [
            r.per_m2[post] / r.per_m2["dv"]
            for r in kjerne
            if post in r.per_m2 and r.per_m2.get("dv", 0) > 0
        ]
        if forhold:
            andeler[post] = median(forhold)

    # Andelene summerer seg ikke nødvendigvis til 1, fordi hver er en median
    # over kommuner. De normaliseres slik at nedbrytingen summerer til D+V.
    sum_andeler = sum(andeler.values())
    if sum_andeler > 0:
        andeler = {p: a / sum_andeler for p, a in andeler.items()}

    forankret: dict[str, dict[str, float]] = {
        "dv": {"lav": dv.p10, "sannsynlig": dv.median, "hoy": dv.p90}
    }
    for post, andel in andeler.items():
        forankret[post] = {
            "lav": dv.p10 * andel,
            "sannsynlig": dv.median * andel,
            "hoy": dv.p90 * andel,
        }
    if "forvaltning" in egne:
        f = egne["forvaltning"]
        forankret["forvaltning"] = {"lav": f.p10, "sannsynlig": f.median, "hoy": f.p90}
    if "fdv" in egne:
        fdv = egne["fdv"]
        forankret["fdv"] = {"lav": fdv.p10, "sannsynlig": fdv.median, "hoy": fdv.p90}
    return forankret, andeler


def forvaltning_per_kommune(rader: Iterable[Kommunerad]) -> dict[str, float]:
    """Forvaltning kr/m² per kommune, én verdi uansett bygningstype.

    Funksjon 121 dekker hele porteføljen og har ikke eget areal, så leddet er
    det samme for alle bygningstyper i samme kommune. Det beregnes derfor én
    gang, på porteføljenivå, og ikke som seks nesten like tall.
    """
    ut: dict[str, float] = {}
    for rad in rader:
        verdi = rad.per_m2.get("forvaltning")
        if verdi is not None and verdi > 0:
            ut[rad.kommune] = verdi
    return ut


def beregn_forvaltning(
    verdier: Mapping[str, float], konfig: dict[str, Any]
) -> tuple[Fordeling | None, list[str]]:
    """Fordeling for forvaltningsleddet, med log-Tukey som for øvrige poster."""
    if len(verdier) < 4:
        return None, sorted(verdier)
    k = float(konfig["terskler"]["tukey_k"])
    trim = float(konfig["terskler"]["trimmet_snitt_andel"])
    nedre, ovre = log_tukey_gjerde(verdier.values(), k)
    kjerne = {k_: v for k_, v in verdier.items() if nedre <= v <= ovre}
    tall = list(kjerne.values())
    if len(tall) < 2:
        return None, sorted(kjerne)
    return (
        Fordeling(
            post="forvaltning",
            n=len(tall),
            p10=kvantil(tall, 0.10),
            median=median(tall),
            p90=kvantil(tall, 0.90),
            snitt=snitt(tall),
            trimmet_snitt=trimmet_snitt(tall, trim),
            arealvektet=float("nan"),
        ),
        sorted(kjerne),
    )


def intern_konsistens(rader: Sequence[Kommunerad], toleranse: float = 1.0) -> list[str]:
    """Sjekker at energi + renhold + øvrig drift == drift per kommune.

    Toleransen er i kroner og fanger avrundingsstøy, ikke feil oppsett.
    """
    avvik: list[str] = []
    for rad in rader:
        drift = rad.kroner.get("drift")
        energi = rad.kroner.get("energi")
        renhold = rad.kroner.get("renhold")
        if None in (drift, energi, renhold):
            continue
        rest = drift - energi - renhold
        if rest < -toleranse:
            avvik.append(f"{rad.kommune}/{rad.funksjon}/{rad.aar}: negativ restpost {rest:.0f} kr")
    return avvik
