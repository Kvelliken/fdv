"""Bygger docs/dekning/index.html fra det frosne grunnlaget i dekning/grunnlag/.

Kjør: python dekning/bygg.py
Ingen nett. Les dekning/README.md for metode og kilder.
"""
import itertools
import json
import pathlib
import sys

HER = pathlib.Path(__file__).resolve().parent
GRUNNLAG = HER / "grunnlag"
UT = HER.parent / "docs" / "dekning" / "index.html"

FUNKSJONER = ["221", "222", "261", "130", "381", "386"]
ALTERNATIVER = ["Personer", "Personer1", "Personer2"]  # MMMM, LLML, HHMH
AAR = [str(a) for a in range(2026, 2051)]


def les(navn):
    """json-stat2 til {(kode, kode, ...): verdi}."""
    d = json.loads((GRUNNLAG / f"{navn}.json").read_text(encoding="utf-8"))
    koder = [
        [k for k, _ in sorted(d["dimension"][dim]["category"]["index"].items(), key=lambda x: x[1])]
        for dim in d["id"]
    ]
    verdier = dict(zip(itertools.product(*koder), d["value"]))
    etiketter = {dim: d["dimension"][dim]["category"]["label"] for dim in d["id"]}
    return verdier, etiketter


def siste(hent):
    """Siste årgang med verdi: 2025, ellers 2024."""
    for aar in ("2025", "2024"):
        v = hent(aar)
        if v is not None:
            return v, int(aar)
    return None, None


def bygg_data():
    A, AL = les("areal")
    B, _ = les("bhg")
    E, _ = les("elev")
    I, _ = les("inst")
    F, FL = les("fram")
    kobling = json.loads((GRUNNLAG / "klass.json").read_text(encoding="utf-8"))["correspondenceItems"]
    gruppe = {c["targetCode"]: int(c["sourceCode"][3:]) for c in kobling}
    navn = AL["KOKkommuneregion0000"]
    aldre = list(FL["Alder"])

    ut, mangler = [], []
    for k in sorted(gruppe):
        if (k, "F312", "Personer", "2026") not in F:
            mangler.append(k)
            continue
        r = {"k": k, "n": navn.get(k, k), "g": gruppe[k], "a": {}, "ay": {}, "le": {}}
        for f in FUNKSJONER:
            v, aar = siste(lambda a: A.get(("samlet", f, k, "KOSareal0000", a)))
            r["a"][f], r["ay"][f] = v, aar
            r["le"][f] = A.get(("leid", f, k, "KOSareal0000", str(aar))) if aar else None
        r["bk"], r["bky"] = siste(lambda a: B.get((k, "F000-006", "1", "0000", "KOSbhgbarn0000", a)))
        r["ba"], _ = siste(lambda a: B.get((k, "F000-006", "0", "0000", "KOSbhgbarn0000", a)))
        r["el"], r["ely"] = siste(lambda a: E.get((k, "KOSelevgrsk0000", a)))
        r["ip"], r["ipy"] = siste(lambda a: I.get((k, "KOSinstdispplass0000", a)))
        r["ik"], _ = siste(lambda a: I.get((k, "KOSinstkomplasse0000", a)))
        r["p"] = {}
        for i, alt in enumerate(ALTERNATIVER):
            def serie(grupper):
                return [sum(F[(k, g, alt, a)] for g in grupper) for a in AAR]
            r["p"][i] = {
                "b": serie(["F312"]),             # 1-5 år
                "s": serie(["F313", "F314"]),     # 6-15 år
                "e": serie(["F319", "F320"]),     # 80 år og eldre
                "t": serie(aldre),                # alle
            }
        ut.append(r)
    return ut, mangler, A


def kontroller(kommuner, A):
    """Summen av kommunene skal ligge nær SSBs landstall for areal."""
    for f in FUNKSJONER:
        land = A.get(("samlet", f, "EAK", "KOSareal0000", "2025"))
        sum_k = sum(r["a"][f] or 0 for r in kommuner)
        avvik = abs(sum_k - land) / land
        print(f"  {f}: kommuner {sum_k:>12,.0f}  landet {land:>12,.0f}  avvik {avvik:.2%}")
        if avvik > 0.02:
            sys.exit(f"Arealsummen for {f} avviker mer enn 2 % fra landstallet")


def main():
    kommuner, mangler, A = bygg_data()
    print(f"{len(kommuner)} kommuner, {len(mangler)} uten framskriving: {mangler}")
    kontroller(kommuner, A)
    data = json.dumps({"koms": kommuner}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    hentet_fil = GRUNNLAG / "HENTET"
    hentet = hentet_fil.read_text().strip() if hentet_fil.exists() else "ukjent dato"
    mal = (HER / "mal.html").read_text(encoding="utf-8")
    side = mal.replace("/*DATA*/", data).replace("/*HENTET*/", hentet)
    UT.parent.mkdir(parents=True, exist_ok=True)
    UT.write_text(side, encoding="utf-8")
    print(f"Skrev {UT.relative_to(HER.parent)} ({UT.stat().st_size:,} byte)")


if __name__ == "__main__":
    main()
