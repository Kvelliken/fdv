"""Nettstedet under docs/: samme meny overalt, og ingen døde interne lenker.

Sidene lages på tre måter: docs/index.html og docs/drift/ er håndskrevne,
docs/dekning/ bygges fra dekning/mal.html, og docs/byggekost/ bygges av
byggekost/modell.py. Menyen står derfor fire steder, og denne testen passer
på at de ikke glir fra hverandre.
"""
import pathlib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

ROT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROT / "docs"

KILDER = {
    "oversikt": ROT / "docs" / "index.html",
    "drift": ROT / "docs" / "drift" / "index.html",
    "dekning": ROT / "dekning" / "mal.html",
    "byggekost": ROT / "byggekost" / "modell.py",
}

SIDER = [
    DOCS / "index.html",
    DOCS / "drift" / "index.html",
    DOCS / "dekning" / "index.html",
    DOCS / "byggekost" / "index.html",
]


def meny(tekst: str) -> list[tuple[str, str]]:
    """Menypunktene som (mål, etikett), med mål gjort uavhengig av mappenivå."""
    blokk = re.search(r'<ul class="vv-meny">(.*?)</ul>', tekst, re.S)
    assert blokk, "fant ikke hovedmenyen"
    punkter = []
    for href, innhold in re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', blokk.group(1), re.S):
        maal = href.removeprefix("../").removeprefix("./") or "./"
        etikett = re.sub(r"<[^>]+>", "", innhold).strip()
        punkter.append((maal, etikett))
    return punkter


def test_menyen_er_lik_paa_alle_sidene():
    menyer = {navn: meny(sti.read_text(encoding="utf-8")) for navn, sti in KILDER.items()}
    forventet = menyer["oversikt"]
    assert [m for m, _ in forventet] == ["./", "dekning/", "byggekost/", "drift/"]
    for navn, punkter in menyer.items():
        assert punkter == forventet, f"menyen i {navn} avviker fra oversiktssiden"


@pytest.mark.parametrize("navn,sti", KILDER.items())
def test_riktig_menypunkt_er_markert(navn, sti):
    tekst = sti.read_text(encoding="utf-8")
    blokk = re.search(r'<ul class="vv-meny">(.*?)</ul>', tekst, re.S).group(1)
    markert = re.findall(r'<a href="([^"]*)" aria-current="page"', blokk)
    forventet = {"oversikt": "./", "drift": "../drift/", "dekning": "../dekning/", "byggekost": "../byggekost/"}
    assert markert == [forventet[navn]]


class Lenker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lenker = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for attr in ("href", "src"):
            if a.get(attr) and tag in ("a", "link", "script", "img"):
                self.lenker.append(a[attr])


@pytest.mark.parametrize("side", SIDER, ids=lambda s: str(s.relative_to(DOCS)))
def test_interne_lenker_finnes(side):
    if not side.exists():
        pytest.skip("siden er ikke bygget")
    p = Lenker()
    p.feed(side.read_text(encoding="utf-8"))
    mangler = []
    for lenke in p.lenker:
        deler = urlsplit(lenke)
        if deler.scheme or lenke.startswith(("#", "mailto:")) or not deler.path:
            continue
        maal = (side.parent / deler.path).resolve()
        if maal.is_dir():
            maal = maal / "index.html"
        if not maal.exists():
            mangler.append(lenke)
    assert not mangler, f"døde lenker i {side.relative_to(DOCS)}: {mangler}"


def test_ingen_skrift_fra_tredjepart():
    """Skriftene ligger i docs/felles/fonter, så sidene skal ikke hente fra Google."""
    for side in SIDER:
        if side.exists():
            assert "fonts.googleapis.com" not in side.read_text(encoding="utf-8"), side
