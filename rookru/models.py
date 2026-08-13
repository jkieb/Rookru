"""Datenmodelle für Stellen, Profil und generierte Unterlagen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Job:
    """Eine Stellenausschreibung — aus Adzuna oder aus jobs.yaml."""

    id: str
    title: str
    company: str
    description: str = ""
    location: str = ""
    url: str = ""
    created: str = ""
    contract_time: str = ""
    source: str = "adzuna"
    # Felder, die Adzuna nicht liefert und die man je Stelle nachtragen kann
    department: str = ""
    street: str = ""
    postal_city: str = ""
    salutation: str = ""
    reference: str = ""

    @property
    def slug(self) -> str:
        from .config import slugify

        return f"{slugify(self.company)}-{slugify(self.title)}"[:70]

    def salutation_or_default(self) -> str:
        return self.salutation or "Sehr geehrte Damen und Herren,"

    def haystack(self) -> str:
        """Gesamter Text der Ausschreibung in Kleinschreibung — für Keyword-Prüfungen."""
        return " ".join([self.title, self.company, self.description]).lower()


@dataclass
class TemplateData:
    """Was einmalig aus der Lebenslauf-Vorlage gelesen wird.

    Die Vorlage ist die einzige Quelle der Wahrheit über den Bewerber; das
    Faktenblatt und die Kennungen unten gehen so an das Modell.
    """

    facts: str = ""
    projects: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class Focus:
    """Welcher Schwerpunkt für diese Stelle vorne stehen soll."""

    key: str  # z. B. "it" oder "konstruktion"
    label: str
    emphasise: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class LetterContent:
    """Der Text, der in die Motivationsschreiben-Vorlage eingesetzt wird."""

    subject: str
    salutation: str
    paragraphs: list[str]
    company_name: str = ""
    company_department: str = ""
    company_street: str = ""
    company_postal_city: str = ""
    letter_date: date = field(default_factory=date.today)

    def word_count(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


@dataclass
class SectionEdit:
    """Eine überarbeitete Lebenslauf-Zeile.

    `anchor` identifiziert die Vorlagenzeile (linke Tabellenspalte bzw.
    Zeilenanfang), `bullets` ersetzt deren Stichpunkte.
    """

    anchor: str
    bullets: list[str] = field(default_factory=list)
    drop: bool = False


@dataclass
class CVAdaptation:
    """Anpassungen am Lebenslauf für genau eine Stelle.

    Betrifft ausschließlich die freigegebenen Abschnitte AUSBILDUNG, PROJEKTE
    und BESONDERE KENNTNISSE UND FÄHIGKEITEN. Berufserfahrungen, persönliche
    Daten und Sprachkenntnisse bleiben unverändert.

    Bei AUSBILDUNG werden nur die Stichpunkte umformuliert — die Einträge
    behalten ihre chronologische Reihenfolge und keiner wird entfernt, damit
    im Lebenslauf keine Lücke entsteht.
    """

    project_order: list[str] = field(default_factory=list)
    project_edits: list[SectionEdit] = field(default_factory=list)
    education_edits: list[SectionEdit] = field(default_factory=list)
    skill_lines: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Application:
    """Ergebnis einer erzeugten Bewerbung."""

    job: Job
    focus: Focus
    letter: LetterContent
    adaptation: CVAdaptation
    directory: Path
    letter_docx: Path
    letter_pdf: Path
    cv_docx: Path
    cv_pdf: Path
    bundle_pdf: Path
    letter_pages: int
    cv_pages: int
    bundle_pages: int
    warnings: list[str] = field(default_factory=list)

    def files(self) -> list[Path]:
        return [self.letter_docx, self.letter_pdf, self.cv_docx, self.cv_pdf, self.bundle_pdf]
