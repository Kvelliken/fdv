"""Finner verdikoder ved tekstsøk i tabellens metadata.

Ingen verdikode er hardkodet i denne modulen. Alle søkemønstre og
overstyringer står i config.yaml. Hvert valg bærer med seg om det ble tatt
automatisk eller overstyrt, og det skrives til grunnlagsfilen slik at en
feilaktig antakelse blir synlig ved første kjøring i stedet for å forplante
seg til publiserte tall.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Sequence

from .ssb_api import dimensjonsverdier

logg = logging.getLogger(__name__)


class KodevalgFeil(RuntimeError):
    """Koden lot seg ikke bestemme entydig. Jobben skal stoppe."""


class SektorFeil(KodevalgFeil):
    """Sektordimensjonen er uavklart. Aldri summer over den."""


@dataclass(frozen=True)
class Valg:
    formaal: str
    dimensjon: str
    kode: str
    tekst: str
    kilde: str  # "automatisk" eller "overstyrt"

    def som_dict(self) -> dict[str, str]:
        return asdict(self)


def _normaliser(s: str) -> str:
    return " ".join(s.lower().replace("\u00a0", " ").split())


def _finn_dimensjon(metadata: dict[str, Any], krav: Sequence[str]) -> tuple[str, str, list[tuple[str, str]]]:
    krav_n = [_normaliser(k) for k in krav]
    for kode, tekst, verdier in dimensjonsverdier(metadata):
        merkelapp = _normaliser(f"{kode} {tekst}")
        if any(k in merkelapp for k in krav_n):
            return kode, tekst, verdier
    tilgjengelige = [f"{k} ({t})" for k, t, _ in dimensjonsverdier(metadata)]
    raise KodevalgFeil(
        f"Fant ingen dimensjon som matcher {list(krav)}. "
        f"Tabellen har: {tilgjengelige}"
    )


def har_dimensjon(metadata: dict[str, Any], krav: Sequence[str]) -> bool:
    """Sier om tabellen i det hele tatt har en dimensjon som matcher."""
    try:
        _finn_dimensjon(metadata, krav)
        return True
    except KodevalgFeil:
        return False


def finn_kode(
    metadata: dict[str, Any],
    formaal: str,
    regel: dict[str, Any],
    overstyring: str | None = None,
) -> Valg:
    """Slår opp én verdikode. Krever entydig treff."""
    dimensjon, dim_tekst, verdier = _finn_dimensjon(metadata, regel["dimensjon_krev"])

    if overstyring:
        for kode, tekst in verdier:
            if kode == overstyring:
                return Valg(formaal, dimensjon, kode, tekst, "overstyrt")
        raise KodevalgFeil(
            f"{formaal}: overstyrt kode {overstyring!r} finnes ikke i dimensjonen "
            f"{dimensjon} ({dim_tekst}). Gyldige koder: {[k for k, _ in verdier]}"
        )

    krev = [_normaliser(k) for k in regel.get("krev", [])]
    unnta = [_normaliser(k) for k in regel.get("unnta", [])]
    treff = []
    for kode, tekst in verdier:
        merkelapp = _normaliser(f"{kode} {tekst}")
        if all(k in merkelapp for k in krev) and not any(u in merkelapp for u in unnta):
            treff.append((kode, tekst))

    if len(treff) == 1:
        kode, tekst = treff[0]
        logg.info("Kodevalg %s: %s = %s (%s), automatisk", formaal, dimensjon, kode, tekst)
        return Valg(formaal, dimensjon, kode, tekst, "automatisk")
    if not treff:
        raise KodevalgFeil(
            f"{formaal}: ingen verdi i {dimensjon} ({dim_tekst}) matcher {regel.get('krev')}. "
            f"Gyldige koder: {[(k, t) for k, t in verdier]}"
        )
    raise KodevalgFeil(
        f"{formaal}: {len(treff)} verdier i {dimensjon} matcher {regel.get('krev')}: {treff}. "
        f"Skjerp søket eller sett overstyring i config.yaml."
    )


def sektorvakt(metadata: dict[str, Any], konfig: dict[str, Any]) -> Valg:
    """Løser sektordimensjonen til nøyaktig én kode, ellers hard feil.

    Kommunekasse på kostnadssiden mot areal med foretak er enkeltfeilen som
    produserer verdier som 7 kr/m². Summering over sektordimensjonen er
    dobbelttelling. Derfor: entydig kode, eller stopp.
    """
    regel = konfig["kodesok"]["sektor"]
    overstyring = (konfig.get("overstyring") or {}).get("sektor")

    # Noen KOSTRA-tabeller har ingen sektordimensjon: sektoren er bakt inn i
    # tabellens definisjon. Det er noe annet enn en uavklart dimensjon, og skal
    # ikke stoppe jobben - men det skal bare godtas når config sier det
    # eksplisitt, og det logges som et valg på linje med de andre.
    if not har_dimensjon(metadata, regel["dimensjon_krev"]):
        if regel.get("tillat_manglende_dimensjon"):
            begrunnelse = regel.get(
                "manglende_dimensjon_begrunnelse",
                "Tabellen har ingen sektordimensjon.",
            )
            logg.info("Kodevalg sektor: ikke aktuell. %s", begrunnelse)
            return Valg("sektor", "", "", begrunnelse, "ikke_aktuell")
        raise SektorFeil(
            "Tabellen har ingen sektordimensjon. Er den bakt inn i tabellens "
            "definisjon, sett `tillat_manglende_dimensjon: true` under "
            "kodesok.sektor i config.yaml og skriv begrunnelsen der. "
            "Jobben summerer aldri over sektor uten at det er dokumentert."
        )

    try:
        return finn_kode(metadata, "sektor", regel, overstyring)
    except KodevalgFeil as feil:
        raise SektorFeil(
            "Uavklart sektordimensjon. Jobben summerer aldri over sektor.\n" + str(feil)
        ) from feil


def finn_arter(metadata: dict[str, Any], konfig: dict[str, Any], ledd: Iterable[str]) -> dict[str, Valg]:
    """Slår opp artskodene for de etterspurte leddene."""
    regler = konfig["kodesok"]["art"]
    overstyringer = ((konfig.get("overstyring") or {}).get("art") or {})
    valg: dict[str, Valg] = {}
    for navn in ledd:
        if navn not in regler:
            raise KodevalgFeil(f"Mangler kodesøk for art {navn!r} i config.yaml")
        valg[navn] = finn_kode(metadata, f"art:{navn}", regler[navn], overstyringer.get(navn))
    return valg


# -- Årgangsvalg ------------------------------------------------------------


def revidert_aargang_tilgjengelig(i_dag: dt.date, konfig: dict[str, Any]) -> int:
    """Siste årgang som finnes i revidert utgave på gitt dato.

    KOSTRA publiserer foreløpige tall 15. mars og reviderte 15. juni. Fram til
    15. juni i år Y er siste reviderte årgang Y-2.
    """
    rev = konfig["aargang"]["revidert_publisering"]
    grense = dt.date(i_dag.year, rev["maaned"], rev["dag"])
    return i_dag.year - 1 if i_dag >= grense else i_dag.year - 2


def velg_aargang(
    tilgjengelige: Sequence[str],
    i_dag: dt.date,
    konfig: dict[str, Any],
    tillat_forelopig: bool | None = None,
) -> list[int]:
    """Velger årgangene som skal fryses, nyeste sist.

    Imputerte verdier i marspubliseringen ser normale ut og passerer alle
    kvalitetsfiltre. Derfor tas en ny årgang først inn etter 15. juni, med
    mindre `tillat_forelopig` er satt - og da merkes utdataene.
    """
    if tillat_forelopig is None:
        tillat_forelopig = bool(konfig["aargang"].get("tillat_forelopig"))
    antall = int(konfig["aargang"]["antall_frosne"])
    aar = sorted({int(a) for a in tilgjengelige if str(a).isdigit()})
    if not aar:
        raise KodevalgFeil("Tabellen oppgir ingen årganger")

    tak = revidert_aargang_tilgjengelig(i_dag, konfig)
    if tillat_forelopig:
        tak = max(aar)
        logg.warning(
            "tillat_forelopig er satt: tar med årgang %s, som kan inneholde "
            "imputerte verdier for kommuner som ikke har rapportert.",
            tak,
        )
    valgte = [a for a in aar if a <= tak][-antall:]
    if not valgte:
        raise KodevalgFeil(
            f"Ingen reviderte årganger tilgjengelig. Tabellen har {aar}, "
            f"grensen for revidert utgave er {tak}."
        )
    return valgte


def er_forelopig(aargang: int, i_dag: dt.date, konfig: dict[str, Any]) -> bool:
    """Sier om en årgang bare finnes som foreløpig utgave på gitt dato."""
    return aargang > revidert_aargang_tilgjengelig(i_dag, konfig)
