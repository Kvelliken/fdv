"""Uttrekk fra SSBs statistikkbank-API (PxWebApi v1, json-stat2).

Modulen gjør tre ting og ikke mer: henter metadata, poster spørringer med
ratebegrensning og retry, og pakker json-stat2 ut til flate rader. All
fagkunnskap om KOSTRA ligger i kodevalg.py og beregning.py.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

logg = logging.getLogger(__name__)


class SSBFeil(RuntimeError):
    """API-et svarte ikke som forventet. Jobben skal feile, ikke fortsette."""


@dataclass(frozen=True)
class Rad:
    """En celle i et json-stat2-datasett, med alle dimensjoner som koder."""

    koder: dict[str, str]
    etiketter: dict[str, str]
    verdi: float | None
    status: str | None = None


class Ratebegrenser:
    """Enkel token bucket. SSB tåler 30 kall per minutt per klient."""

    def __init__(self, maks_per_minutt: int) -> None:
        self.maks = maks_per_minutt
        self._tidspunkt: list[float] = []

    def vent(self) -> None:
        naa = time.monotonic()
        self._tidspunkt = [t for t in self._tidspunkt if naa - t < 60.0]
        if len(self._tidspunkt) >= self.maks:
            sov = 60.0 - (naa - self._tidspunkt[0]) + 0.1
            if sov > 0:
                logg.info("Ratebegrensning: venter %.1f s", sov)
                time.sleep(sov)
        self._tidspunkt.append(time.monotonic())


class SSBKlient:
    """Henter metadata og data fra ett statistikkbank-endepunkt."""

    def __init__(self, konfig: dict[str, Any], sesjon: Any | None = None) -> None:
        api = konfig["api"]
        self.base_url = api["base_url"].rstrip("/")
        self.timeout = api["timeout_sekunder"]
        self.retry = api["retry"]
        self.begrenser = Ratebegrenser(api["maks_kall_per_minutt"])
        if sesjon is None:
            import requests  # importeres sent, så enhetstester slipper nettpakker

            sesjon = requests.Session()
            sesjon.headers.update({"User-Agent": "kostra-fdv (github.com/kostra-fdv)"})
        self.sesjon = sesjon

    # -- HTTP ---------------------------------------------------------------

    def _kall(self, metode: str, url: str, **kwargs: Any) -> Any:
        forsok = int(self.retry["forsok"])
        grunn = float(self.retry["grunn_ventetid_sekunder"])
        tak = float(self.retry["maks_ventetid_sekunder"])
        gir_retry = set(self.retry["status_som_gir_retry"])

        siste: Exception | None = None
        for n in range(forsok):
            self.begrenser.vent()
            try:
                svar = self.sesjon.request(metode, url, timeout=self.timeout, **kwargs)
            except Exception as feil:  # nettverksfeil, timeout
                siste = feil
                svar = None
            if svar is not None:
                if svar.status_code == 200:
                    try:
                        return svar.json()
                    except json.JSONDecodeError as feil:
                        raise SSBFeil(f"{url}: svarte 200 men ikke gyldig JSON") from feil
                if svar.status_code not in gir_retry:
                    raise SSBFeil(
                        f"{url}: HTTP {svar.status_code}. "
                        f"Svar: {svar.text[:400]}"
                    )
                siste = SSBFeil(f"{url}: HTTP {svar.status_code}")
            if n < forsok - 1:
                ventetid = min(tak, grunn * (2**n)) * (0.5 + random.random())
                logg.warning("Forsøk %d/%d feilet mot %s, venter %.1f s", n + 1, forsok, url, ventetid)
                time.sleep(ventetid)
        raise SSBFeil(f"{url}: ga opp etter {forsok} forsøk") from siste

    def hent_metadata(self, tabell: str) -> dict[str, Any]:
        """GET mot tabell-URL-en gir tabellens variabler med koder og tekster."""
        return self._kall("GET", f"{self.base_url}/{tabell}")

    def hent_data(self, tabell: str, sporring: dict[str, Any]) -> dict[str, Any]:
        """POST av en PxWebApi-spørring. Returnerer json-stat2-datasettet."""
        return self._kall("POST", f"{self.base_url}/{tabell}", json=sporring)


# -- Spørringsbygging -------------------------------------------------------


def lag_sporring(utvalg: dict[str, Sequence[str]]) -> dict[str, Any]:
    """Bygger en PxWebApi-spørring av {dimensjonskode: [verdikoder]}.

    Tom liste betyr «alle verdier» og oversettes til filteret `all` med `*`.
    """
    query = []
    for dimensjon, verdier in utvalg.items():
        if not verdier:
            filt = {"filter": "all", "values": ["*"]}
        else:
            filt = {"filter": "item", "values": list(verdier)}
        query.append({"code": dimensjon, "selection": filt})
    return {"query": query, "response": {"format": "json-stat2"}}


# -- json-stat2 -------------------------------------------------------------


def parse_jsonstat2(datasett: dict[str, Any]) -> list[Rad]:
    """Pakker ut et json-stat2-datasett til flate rader.

    json-stat2 lagrer verdiene i en flat liste i radmajor rekkefølge over
    dimensjonene i `id`. Verdien kan også være et sparse-objekt med
    strengnøkler. Begge former håndteres. `status` bærer SSBs kodede
    fravær («:», «..») og følger med ut.
    """
    if datasett.get("class") not in (None, "dataset"):
        raise SSBFeil(f"Uventet json-stat-klasse: {datasett.get('class')!r}")
    for felt in ("id", "size", "dimension", "value"):
        if felt not in datasett:
            raise SSBFeil(f"json-stat2 mangler feltet {felt!r}")

    dimensjoner: list[str] = list(datasett["id"])
    storrelser: list[int] = list(datasett["size"])
    if len(dimensjoner) != len(storrelser):
        raise SSBFeil("json-stat2: id og size har ulik lengde")

    # For hver dimensjon: posisjon -> (kode, etikett)
    oppslag: list[list[tuple[str, str]]] = []
    for dim in dimensjoner:
        kategori = datasett["dimension"][dim]["category"]
        indeks = kategori["index"]
        etiketter = kategori.get("label", {})
        if isinstance(indeks, dict):
            par = sorted(indeks.items(), key=lambda kv: kv[1])
            koder = [k for k, _ in par]
        else:  # listeform
            koder = list(indeks)
        oppslag.append([(k, etiketter.get(k, k)) for k in koder])

    antall = 1
    for s in storrelser:
        antall *= s
    verdier = datasett["value"]
    statuser = datasett.get("status") or {}

    def hent(i: int) -> tuple[float | None, str | None]:
        if isinstance(verdier, dict):
            raa = verdier.get(str(i))
        else:
            raa = verdier[i] if i < len(verdier) else None
        if isinstance(statuser, dict):
            st = statuser.get(str(i))
        elif isinstance(statuser, list) and i < len(statuser):
            st = statuser[i]
        else:
            st = None
        return (None if raa is None else float(raa)), st

    rader: list[Rad] = []
    for i in range(antall):
        koder: dict[str, str] = {}
        etiketter: dict[str, str] = {}
        rest = i
        for d in range(len(dimensjoner) - 1, -1, -1):
            posisjon = rest % storrelser[d]
            rest //= storrelser[d]
            kode, etikett = oppslag[d][posisjon]
            koder[dimensjoner[d]] = kode
            etiketter[dimensjoner[d]] = etikett
        verdi, status = hent(i)
        rader.append(Rad(koder=koder, etiketter=etiketter, verdi=verdi, status=status))
    return rader


def dimensjonsverdier(metadata: dict[str, Any]) -> Iterator[tuple[str, str, list[tuple[str, str]]]]:
    """Gir (dimensjonskode, dimensjonstekst, [(verdikode, verditekst)]) per variabel."""
    for variabel in metadata.get("variables", []):
        kode = variabel.get("code", "")
        tekst = variabel.get("text", "")
        verdier = list(zip(variabel.get("values", []), variabel.get("valueTexts", [])))
        yield kode, tekst, verdier


def tilgjengelige_aargang(metadata: dict[str, Any]) -> list[str]:
    """Årgangene tabellen faktisk har, hentet fra tidsdimensjonen."""
    for kode, tekst, verdier in dimensjonsverdier(metadata):
        if kode.lower() in ("tid", "time") or "år" in tekst.lower():
            return [v for v, _ in verdier]
    raise SSBFeil("Fant ingen tidsdimensjon i metadata")
