"""Stellen aus einer lokalen YAML- oder JSON-Datei.

Unterstützte Formate:
- Eigene YAML-Stellenliste (titel/firma oder title/company je Eintrag)
- suche.json eines Rookru-Suchlaufs (stellen[].stelle-Struktur)
- vorauswahl.json eines Rookru-Suchlaufs (passend[].stelle-Struktur)
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..config import ConfigError, slugify
from ..models import Job


def _raw_list_from_data(data: object, path: Path) -> list[dict]:
    """Extrahiert die flache Stellenliste aus allen unterstützten Formaten."""
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        raise ConfigError(f"{path} enthält keine Stellenliste")

    # suche.json: {"stellen": [{"stelle": {...}}, ...]}
    suche_stellen = data.get("stellen")
    if isinstance(suche_stellen, list) and suche_stellen:
        first = suche_stellen[0]
        if isinstance(first, dict) and "stelle" in first:
            return [entry["stelle"] for entry in suche_stellen if isinstance(entry.get("stelle"), dict)]

    # vorauswahl.json: {"passend": [{"stelle": {...}}, ...]}
    passend = data.get("passend")
    if isinstance(passend, list) and passend:
        first = passend[0]
        if isinstance(first, dict) and "stelle" in first:
            return [entry["stelle"] for entry in passend if isinstance(entry.get("stelle"), dict)]

    # Eigene Stellenliste: {"stellen": [...]} oder {"jobs": [...]}
    flat = data.get("stellen") or data.get("jobs")
    if isinstance(flat, list):
        return flat

    raise ConfigError(f"{path} enthält keine erkannte Stellenliste")


def load_jobs_file(path: str | Path) -> list[Job]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"Stellendatei nicht gefunden: {path}")

    text = path.read_text(encoding="utf-8")
    # JSON direkt parsen, YAML als Fallback (YAML ist ein Superset von JSON,
    # aber json.loads ist strenger und meldet Fehler klarer bei JSON-Dateien)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} ist kein gültiges JSON: {exc}") from exc
    else:
        data = yaml.safe_load(text) or []

    raw_list = _raw_list_from_data(data, path)
    if not raw_list:
        raise ConfigError(f"{path} enthält keine Stellenliste")

    jobs: list[Job] = []
    for raw in raw_list:
        title = str(raw.get("titel") or raw.get("title") or "").strip()
        company = str(raw.get("firma") or raw.get("company") or "").strip()
        if not title or not company:
            raise ConfigError(
                f"Jede Stelle in {path} braucht 'titel'/'title' und 'firma'/'company'.\n"
                "  Tipp: suche.json und vorauswahl.json aus suchlaeufe/ werden direkt unterstützt."
            )
        jobs.append(
            Job(
                id=str(raw.get("id") or f"{slugify(company)}-{slugify(title)}"),
                title=title,
                company=company,
                description=str(raw.get("beschreibung") or raw.get("description") or ""),
                location=str(raw.get("ort") or raw.get("location") or ""),
                url=str(raw.get("url") or ""),
                created=str(raw.get("datum") or raw.get("created") or ""),
                source=str(raw.get("source") or "lokal"),
                department=str(raw.get("abteilung") or raw.get("department") or ""),
                street=str(raw.get("strasse") or raw.get("street") or ""),
                postal_city=str(raw.get("plz_ort") or raw.get("postal_city") or ""),
                salutation=str(raw.get("anrede") or raw.get("salutation") or ""),
                reference=str(raw.get("referenz") or raw.get("reference") or ""),
            )
        )
    return jobs
