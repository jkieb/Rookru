"""Konfiguration aus profil.yaml laden und prüfen."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Fehlende oder widersprüchliche Konfiguration."""


@dataclass
class Applicant:
    name: str
    city: str = ""
    email: str = ""
    phone: str = ""


@dataclass
class Templates:
    letter: Path
    cv: Path


@dataclass
class Attachment:
    label: str
    path: Path


@dataclass
class FocusRule:
    """Regel, welcher Schwerpunkt bei welchen Stichwörtern gilt."""

    key: str
    label: str
    keywords: list[str] = field(default_factory=list)
    emphasise: list[str] = field(default_factory=list)

    def score(self, text: str) -> int:
        return sum(1 for kw in self.keywords if kw.lower() in text)


@dataclass
class SearchSettings:
    country: str = "at"
    queries: list[str] = field(default_factory=lambda: ["Werkstudent Maschinenbau"])
    where: str = ""
    distance_km: int = 0
    results: int = 20
    max_days_old: int = 30
    contract_time: str = ""
    exclude: list[str] = field(default_factory=list)
    min_score: int = 0


@dataclass
class LetterSettings:
    max_words: int = 300
    paragraphs: int = 4
    tone: str = "sachlich, konkret, ohne Werbefloskeln"
    closing_fixed: bool = True


@dataclass
class Settings:
    applicant: Applicant
    templates: Templates
    attachments: list[Attachment]
    focus_rules: list[FocusRule]
    search: SearchSettings
    letter: LetterSettings
    output_dir: Path
    base_dir: Path

    def attachment_labels(self) -> list[str]:
        return [a.label for a in self.attachments]

    def missing_files(self) -> list[str]:
        missing = []
        for label, path in (
            ("Motivationsschreiben-Vorlage", self.templates.letter),
            ("Lebenslauf-Vorlage", self.templates.cv),
        ):
            if not path.is_file():
                missing.append(f"{label}: {path}")
        for att in self.attachments:
            if not att.path.is_file():
                missing.append(f"{att.label}: {att.path}")
        return missing


def slugify(value: str) -> str:
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(src, dst).replace(src.upper(), dst.capitalize())
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "stelle"


def _resolve(base: Path, value: str) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _require(data: dict, key: str, where: str) -> Any:
    if not isinstance(data, dict) or key not in data or data[key] in (None, ""):
        raise ConfigError(f"Pflichtfeld '{key}' fehlt in {where}")
    return data[key]


DEFAULT_FOCUS = [
    FocusRule(
        key="allgemein",
        label="Allgemein",
        keywords=[],
        emphasise=[],
    )
]


def load_settings(path: str | Path) -> Settings:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(
            f"Konfiguration nicht gefunden: {path}\n"
            "Kopiere profil.example.yaml nach profil.yaml und trage deine Daten ein."
        )
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} muss ein YAML-Mapping enthalten")
    base = path.parent

    bewerber = _require(data, "bewerber", str(path))
    applicant = Applicant(
        name=str(_require(bewerber, "name", "bewerber")),
        city=str(bewerber.get("ort", "")),
        email=str(bewerber.get("email", "")),
        phone=str(bewerber.get("telefon", "")),
    )

    vorlagen = _require(data, "vorlagen", str(path))
    templates = Templates(
        letter=_resolve(base, _require(vorlagen, "motivationsschreiben", "vorlagen")),
        cv=_resolve(base, _require(vorlagen, "lebenslauf", "vorlagen")),
    )

    attachments = [
        Attachment(
            label=str(_require(raw, "label", "unterlagen")),
            path=_resolve(base, _require(raw, "pfad", "unterlagen")),
        )
        for raw in (data.get("unterlagen") or [])
    ]

    focus_rules = [
        FocusRule(
            key=str(_require(raw, "key", "schwerpunkte")),
            label=str(raw.get("label", raw.get("key", ""))),
            keywords=[str(k).lower() for k in (raw.get("keywords") or [])],
            emphasise=[str(e) for e in (raw.get("hervorheben") or [])],
        )
        for raw in (data.get("schwerpunkte") or [])
    ] or list(DEFAULT_FOCUS)

    suche = data.get("suche") or {}
    raw_query = suche.get("query", "Werkstudent Maschinenbau")
    queries = [str(raw_query)] if isinstance(raw_query, str) else [str(q) for q in raw_query]
    search = SearchSettings(
        country=str(suche.get("land", "at")).lower(),
        queries=[q for q in queries if q.strip()],
        where=str(suche.get("ort", "")),
        distance_km=int(suche.get("umkreis_km", 0) or 0),
        results=int(suche.get("treffer", 20)),
        max_days_old=int(suche.get("max_tage", 30)),
        contract_time=str(suche.get("anstellung", "")),
        exclude=[str(x).lower() for x in (suche.get("ausschliessen") or [])],
        min_score=int(suche.get("min_score", 0)),
    )

    brief = data.get("brief") or {}
    letter = LetterSettings(
        max_words=int(brief.get("max_woerter", 300)),
        paragraphs=int(brief.get("absaetze", 4)),
        tone=str(brief.get("tonfall", "sachlich, konkret, ohne Werbefloskeln")),
        closing_fixed=bool(brief.get("grussformel_fix", True)),
    )

    output_dir = _resolve(base, str(data.get("ausgabe", "out")))

    return Settings(
        applicant=applicant,
        templates=templates,
        attachments=attachments,
        focus_rules=focus_rules,
        search=search,
        letter=letter,
        output_dir=output_dir,
        base_dir=base,
    )
