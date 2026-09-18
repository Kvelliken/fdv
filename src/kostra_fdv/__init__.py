"""KOSTRA FDV-normtall: reproduserbare nøkkeltall for kommunale formålsbygg."""

from __future__ import annotations

from pathlib import Path
from typing import Any

__version__ = "0.1.0"


def les_konfig(sti: Path | str | None = None) -> dict[str, Any]:
    """Leser config.yaml. Ingen terskler eller koder finnes utenfor denne filen."""
    import yaml

    if sti is None:
        sti = rotkatalog() / "config.yaml"
    sti = Path(sti)
    konfig = yaml.safe_load(sti.read_text(encoding="utf-8"))
    if not isinstance(konfig, dict):
        raise ValueError(f"{sti} inneholder ikke et konfigurasjonsobjekt")
    return konfig


def rotkatalog() -> Path:
    """Repoets rot, uavhengig av hvor jobben kjøres fra."""
    return Path(__file__).resolve().parents[2]
