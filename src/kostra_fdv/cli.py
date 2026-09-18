"""Kommandolinje. Alle GitHub Actions-jobbene går gjennom denne.

    python -m kostra_fdv.cli hent --aargang alle
    python -m kostra_fdv.cli beregn
    python -m kostra_fdv.cli sjekk
    python -m kostra_fdv.cli sensitivitet
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from . import les_konfig, rotkatalog, utdata
from .kodevalg import velg_aargang
from .pipeline import beregn_alle, hent_og_frys, les_frosset
from .ssb_api import SSBKlient, tilgjengelige_aargang

logg = logging.getLogger("kostra_fdv")


def _sett_opp_logg(nivaa: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, nivaa), format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )


def _aargang_som_skal_brukes(klient: SSBKlient, konfig: dict[str, Any], tillat_forelopig: bool) -> list[int]:
    metadata = klient.hent_metadata(konfig["tabeller"]["kostnad"])
    aar = tilgjengelige_aargang(metadata)
    return velg_aargang(aar, dt.date.today(), konfig, tillat_forelopig)


def kommando_hent(args: argparse.Namespace) -> int:
    rot = Path(args.rot)
    konfig = les_konfig(rot / "config.yaml")
    if args.tillat_forelopig:
        konfig["aargang"]["tillat_forelopig"] = True
    klient = SSBKlient(konfig)
    valgte = _aargang_som_skal_brukes(klient, konfig, args.tillat_forelopig)
    if args.aargang != "alle":
        onsket = int(args.aargang)
        if onsket not in valgte and not args.tillat_forelopig:
            logg.error(
                "Årgang %s er ikke tilgjengelig som revidert utgave. Reviderte årganger: %s. "
                "Bruk --tillat-forelopig hvis du bevisst vil ha foreløpige tall.",
                onsket, valgte,
            )
            return 2
        valgte = [onsket]
    logg.info("Henter årgangene %s", valgte)
    for aar in valgte:
        _, valg = hent_og_frys(klient, konfig, rot, aar)
        for v in valg:
            logg.info("  %s -> %s (%s) [%s]", v.formaal, v.kode, v.tekst, v.kilde)
    return 0


def kommando_beregn(args: argparse.Namespace) -> int:
    rot = Path(args.rot)
    konfig = les_konfig(rot / "config.yaml")
    if args.tillat_forelopig:
        konfig["aargang"]["tillat_forelopig"] = True
    aargang = _frosne_aargang(rot)
    if not aargang:
        logg.error("Ingen frosne årganger i data/grunnlag. Kjør `hent` først.")
        return 2
    normtall = beregn_alle(rot, konfig, aargang)
    stier = utdata.publiser(rot, normtall)
    for sti in stier:
        logg.info("Skrev %s", sti)
    return 0


def _frosne_aargang(rot: Path) -> list[int]:
    katalog = rot / "data" / "grunnlag"
    if not katalog.exists():
        return []
    return sorted(int(p.name) for p in katalog.iterdir() if p.is_dir() and p.name.isdigit())


def kommando_sjekk(args: argparse.Namespace) -> int:
    """Endringsdetektor for manedlig.yml.

    Skriver en JSON-rapport til stdout. Workflowen leser den og bestemmer om
    det skal opprettes issue. De fleste kjøringene skal ende uten funn.
    """
    rot = Path(args.rot)
    konfig = les_konfig(rot / "config.yaml")
    klient = SSBKlient(konfig)
    i_dag = dt.date.today()

    metadata = klient.hent_metadata(konfig["tabeller"]["kostnad"])
    tilgjengelig = [int(a) for a in tilgjengelige_aargang(metadata) if str(a).isdigit()]
    frosne = _frosne_aargang(rot)
    rev = konfig["aargang"]["revidert_publisering"]
    etter_revisjonsdato = i_dag >= dt.date(i_dag.year, rev["maaned"], rev["dag"])

    nye = [a for a in tilgjengelig if a not in frosne]
    rapport: dict[str, Any] = {
        "dato": i_dag.isoformat(),
        "frosne_aargang": frosne,
        "tilgjengelige_aargang": tilgjengelig,
        "nye_aargang": nye,
        "revidert_utgave_ventet": etter_revisjonsdato,
        "opprett_issue_ny_aargang": bool(nye) and etter_revisjonsdato,
        "revisjon_oppdaget": [],
    }

    # Stikkprøve: hent siste frosne årgang på nytt og sammenlign med frosset
    # versjon. Avvik betyr at SSB har revidert en publisert årgang stille.
    if frosne:
        siste = frosne[-1]
        try:
            from .pipeline import hent_og_frys  # lokal import, tung avhengighet

            gammelt = utdata.les_grunnlag(rot, siste, "kostnad")
            nytt, _ = hent_og_frys(klient, konfig, Path(args.midlertidig or rot), siste) if args.dyp else (None, None)
            if nytt is not None and gammelt is not None:
                linjer = utdata.diff_grunnlag(gammelt, nytt["kostnad"])
                if linjer and not linjer[0].startswith("Identisk"):
                    rapport["revisjon_oppdaget"].append({"aargang": siste, "diff": linjer})
        except Exception as feil:  # stikkprøven skal ikke velte detektoren
            rapport["stikkprove_feilet"] = str(feil)

    print(json.dumps(rapport, ensure_ascii=False, indent=1))
    return 0


def kommando_sensitivitet(args: argparse.Namespace) -> int:
    """Kjører med terskler ±50 % og rapporterer hvordan P10, median og P90 flytter seg."""
    rot = Path(args.rot)
    konfig = les_konfig(rot / "config.yaml")
    aargang = _frosne_aargang(rot)
    if not aargang:
        logg.error("Ingen frosne årganger. Kjør `hent` først.")
        return 2

    basis = beregn_alle(rot, konfig, aargang, skriv_revisjon=False)
    rapport: dict[str, Any] = {"basis": _uttrekk_punkter(basis), "varianter": {}}

    for faktor in konfig["sensitivitet"]["faktorer"]:
        terskler = copy.deepcopy(konfig["terskler"])
        for nokkel, verdi in terskler.items():
            if isinstance(verdi, (int, float)) and nokkel != "tukey_k":
                terskler[nokkel] = verdi * faktor
        variant = beregn_alle(rot, konfig, aargang, terskler=terskler, skriv_revisjon=False)
        rapport["varianter"][str(faktor)] = _uttrekk_punkter(variant)

    sti = rot / "data" / "publisert" / "sensitivitet.json"
    utdata.skriv_json(sti, rapport)
    logg.info("Skrev %s", sti)
    return 0


def _uttrekk_punkter(normtall: dict[str, Any]) -> dict[str, Any]:
    ut: dict[str, Any] = {}
    for funksjon, innhold in normtall["funksjoner"].items():
        dv = innhold["kostnad"]["normtall_forankret"].get("dv", {})
        ut[funksjon] = {
            "n_kjerne": innhold["kostnad"]["n_kjerne"],
            "lav": (dv.get("lav") or {}).get("verdi"),
            "sannsynlig": (dv.get("sannsynlig") or {}).get("verdi"),
            "hoy": (dv.get("hoy") or {}).get("verdi"),
        }
    return ut


def lag_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kostra-fdv", description=__doc__)
    parser.add_argument("--rot", default=str(rotkatalog()), help="Repoets rot")
    parser.add_argument("--logg", default="INFO", help="Loggnivå")
    under = parser.add_subparsers(dest="kommando", required=True)

    p_hent = under.add_parser("hent", help="Hent og frys KOSTRA-grunnlag")
    p_hent.add_argument("--aargang", default="alle", help="Årstall eller 'alle'")
    p_hent.add_argument("--tillat-forelopig", action="store_true")
    p_hent.set_defaults(funksjon=kommando_hent)

    p_beregn = under.add_parser("beregn", help="Beregn normtall fra frosset grunnlag")
    p_beregn.add_argument("--tillat-forelopig", action="store_true")
    p_beregn.set_defaults(funksjon=kommando_beregn)

    p_sjekk = under.add_parser("sjekk", help="Endringsdetektor: ny eller revidert årgang")
    p_sjekk.add_argument("--dyp", action="store_true", help="Hent stikkprøve på nytt fra SSB")
    p_sjekk.add_argument("--midlertidig", default=None, help="Katalog for stikkprøvehenting")
    p_sjekk.set_defaults(funksjon=kommando_sjekk)

    p_sens = under.add_parser("sensitivitet", help="Kjør med terskler ±50 %%")
    p_sens.set_defaults(funksjon=kommando_sensitivitet)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = lag_parser().parse_args(argv)
    _sett_opp_logg(args.logg)
    return int(args.funksjon(args))


if __name__ == "__main__":
    raise SystemExit(main())
