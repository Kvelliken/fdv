"""Tidsserier med balansert panel.

Kvalitetsflaggene slår ut på ulike kommuner hvert år. Regnes medianen på hele
det rensede utvalget per år, blander tidsserien prisvekst med
sammensetningsendring: en kommune som faller ut i ett år og inn igjen i neste
flytter medianen uten at noen pris har endret seg.

Derfor to serier:

* nivåserien, som svarer på «hva er nivået i år X»
* panelserien, som svarer på «hvor mye har det steget»

Vekstrater regnes utelukkende på panelserien. Feilen ved å regne dem på
nivåserien gir ingen feilmelding, bare et litt galt tall, så den fanges av
test og ikke av kjøringen.

Ingen indeksjustering noe sted. Alle tall er i løpende kroner for årgangen de
gjelder, slik de står i KOSTRA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .beregning import arealvektet, kvantil, median


@dataclass
class Aarspunkt:
    aar: int
    n: int
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    arealvektet: float | None = None

    def som_dict(self) -> dict[str, Any]:
        return {
            "aargang": self.aar,
            "n_kommuner": self.n,
            "median": self.median,
            "p10": self.p10,
            "p90": self.p90,
            "arealvektet_snitt": self.arealvektet,
        }


@dataclass
class Serie:
    navn: str
    punkter: list[Aarspunkt] = field(default_factory=list)

    def som_dict(self) -> dict[str, Any]:
        return {"utvalg": self.navn, "punkter": [p.som_dict() for p in self.punkter]}


def panelkommuner(kjerne_per_aar: Mapping[int, Sequence[str]]) -> list[str]:
    """Kommunene som er rene i alle årganger."""
    if not kjerne_per_aar:
        return []
    felles: set[str] | None = None
    for kommuner in kjerne_per_aar.values():
        s = set(kommuner)
        felles = s if felles is None else (felles & s)
    return sorted(felles or [])


def _punkt(aar: int, verdier: Sequence[float], arealer: Sequence[float] | None) -> Aarspunkt:
    if not verdier:
        return Aarspunkt(aar=aar, n=0)
    av = None
    if arealer and len(arealer) == len(verdier) and sum(arealer) > 0:
        av = arealvektet([v * a for v, a in zip(verdier, arealer)], arealer)
    return Aarspunkt(
        aar=aar,
        n=len(verdier),
        median=median(verdier),
        p10=kvantil(verdier, 0.10),
        p90=kvantil(verdier, 0.90),
        arealvektet=av,
    )


def nivaaserie(
    verdier_per_aar: Mapping[int, Mapping[str, float]],
    arealer_per_aar: Mapping[int, Mapping[str, float]] | None = None,
) -> Serie:
    """Alle rene kommuner det året. Brukes til nivåtall per årgang."""
    serie = Serie(navn="nivaa")
    for aar in sorted(verdier_per_aar):
        verdier = list(verdier_per_aar[aar].values())
        arealer = None
        if arealer_per_aar and aar in arealer_per_aar:
            arealer = [arealer_per_aar[aar].get(k, 0.0) for k in verdier_per_aar[aar]]
        serie.punkter.append(_punkt(aar, verdier, arealer))
    return serie


def panelserie(
    verdier_per_aar: Mapping[int, Mapping[str, float]],
    panel: Sequence[str],
    arealer_per_aar: Mapping[int, Mapping[str, float]] | None = None,
) -> Serie:
    """Kun kommuner som er rene i alle år. Brukes til vekstrater."""
    serie = Serie(navn="panel")
    panel = list(panel)
    for aar in sorted(verdier_per_aar):
        kilde = verdier_per_aar[aar]
        verdier = [kilde[k] for k in panel if k in kilde]
        arealer = None
        if arealer_per_aar and aar in arealer_per_aar:
            arealer = [arealer_per_aar[aar].get(k, 0.0) for k in panel if k in kilde]
        serie.punkter.append(_punkt(aar, verdier, arealer))
    return serie


# -- Brudd ------------------------------------------------------------------


def brudd_som_gjelder(
    brudd: Sequence[Mapping[str, Any]], funksjon: str, post: str, fra: int, til: int
) -> list[dict[str, Any]]:
    """Brudd som faller i intervallet (fra, til] og berører denne serien.

    `gjelder` er «alle», «funksjon:222» eller «post:vedlikehold».
    """
    treff = []
    for b in brudd or []:
        aar = int(b["aar"])
        if not (fra < aar <= til):
            continue
        gjelder = str(b.get("gjelder", "alle")).strip().lower()
        if gjelder in ("alle", "*"):
            pass
        elif gjelder.startswith("funksjon:") and gjelder.split(":", 1)[1] != funksjon:
            continue
        elif gjelder.startswith("post:") and gjelder.split(":", 1)[1] != post:
            continue
        elif gjelder.startswith("art:"):
            pass  # artsbrudd slår ut på alle poster som bruker arten
        treff.append(dict(b))
    return treff


@dataclass
class Vekst:
    fra_aar: int
    til_aar: int
    n_panel: int
    endring_prosent: float | None
    aarlig_endring_prosent: float | None
    skjult_grunnet_brudd: bool
    brudd: list[dict[str, Any]] = field(default_factory=list)

    def som_dict(self) -> dict[str, Any]:
        return {
            "fra_aargang": self.fra_aar,
            "til_aargang": self.til_aar,
            "n_panel": self.n_panel,
            "nominell_endring_prosent": self.endring_prosent,
            "aarlig_gjennomsnittlig_endring_prosent": self.aarlig_endring_prosent,
            "skjult_grunnet_brudd": self.skjult_grunnet_brudd,
            "brudd": self.brudd,
            "merknad": "Løpende kroner. Nominell vekst inkluderer generell prisstigning.",
        }


def vekstrater(
    serie: Serie,
    funksjon: str,
    post: str,
    brudd: Sequence[Mapping[str, Any]] = (),
) -> Vekst | None:
    """Nominell endring og årlig gjennomsnitt, regnet på panelserien.

    Kaster hvis den får en nivåserie: vekstrater skal ikke regnes på et utvalg
    som endrer sammensetning mellom år.
    """
    if serie.navn != "panel":
        raise ValueError(
            f"Vekstrater skal regnes på panelserien, ikke på {serie.navn!r}. "
            "Se METODE.md kap. 4.2."
        )
    gyldige = [p for p in serie.punkter if p.median is not None and p.n > 0]
    if len(gyldige) < 2:
        return None
    forste, siste = gyldige[0], gyldige[-1]
    truffet = brudd_som_gjelder(brudd, funksjon, post, forste.aar, siste.aar)
    if truffet:
        return Vekst(
            fra_aar=forste.aar,
            til_aar=siste.aar,
            n_panel=min(p.n for p in gyldige),
            endring_prosent=None,
            aarlig_endring_prosent=None,
            skjult_grunnet_brudd=True,
            brudd=truffet,
        )
    if not forste.median:
        return None
    endring = (siste.median / forste.median - 1.0) * 100.0
    aar_mellom = siste.aar - forste.aar
    aarlig = ((siste.median / forste.median) ** (1.0 / aar_mellom) - 1.0) * 100.0 if aar_mellom else None
    return Vekst(
        fra_aar=forste.aar,
        til_aar=siste.aar,
        n_panel=min(p.n for p in gyldige),
        endring_prosent=endring,
        aarlig_endring_prosent=aarlig,
        skjult_grunnet_brudd=False,
        brudd=[],
    )


def bygg_historikk(
    verdier_per_aar: Mapping[int, Mapping[str, float]],
    kjerne_per_aar: Mapping[int, Sequence[str]],
    funksjon: str,
    post: str,
    brudd: Sequence[Mapping[str, Any]] = (),
    arealer_per_aar: Mapping[int, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """Setter sammen nivåserie, panelserie og vekstrater for én post."""
    panel = panelkommuner(kjerne_per_aar)
    niv = nivaaserie(verdier_per_aar, arealer_per_aar)
    pan = panelserie(verdier_per_aar, panel, arealer_per_aar)
    vekst = vekstrater(pan, funksjon, post, brudd)
    return {
        "post": post,
        "nivaaserie": niv.som_dict(),
        "panelserie": pan.som_dict(),
        "n_panel": len(panel),
        "vekst": vekst.som_dict() if vekst else None,
    }
