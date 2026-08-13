"""Stellen aus einer lokalen YAML-Datei — für Tests und manuell erfasste Ausschreibungen."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..config import ConfigError, slugify
from ..models import Job


def load_jobs_file(path: str | Path) -> list[Job]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"Stellendatei nicht gefunden: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("stellen") or data.get("jobs") or []
    if not isinstance(data, list) or not data:
        raise ConfigError(f"{path} enthält keine Stellenliste")

    jobs: list[Job] = []
    for raw in data:
        title = str(raw.get("titel") or raw.get("title") or "").strip()
        company = str(raw.get("firma") or raw.get("company") or "").strip()
        if not title or not company:
            raise ConfigError(f"Jede Stelle in {path} braucht 'titel' und 'firma'")
        jobs.append(
            Job(
                id=str(raw.get("id") or f"{slugify(company)}-{slugify(title)}"),
                title=title,
                company=company,
                description=str(raw.get("beschreibung") or raw.get("description") or ""),
                location=str(raw.get("ort") or ""),
                url=str(raw.get("url") or ""),
                created=str(raw.get("datum") or ""),
                source="lokal",
                department=str(raw.get("abteilung") or ""),
                street=str(raw.get("strasse") or ""),
                postal_city=str(raw.get("plz_ort") or ""),
                salutation=str(raw.get("anrede") or ""),
                reference=str(raw.get("referenz") or ""),
            )
        )
    return jobs
