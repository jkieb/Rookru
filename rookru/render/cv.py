"""Lebenslauf: Vorlage übernehmen und nur die freigegebenen Abschnitte anpassen.

Angepasst werden AUSBILDUNG (nur Stichpunkte), PROJEKTE (Reihenfolge und
Stichpunkte) und BESONDERE KENNTNISSE UND FÄHIGKEITEN. Persönliche Daten,
Berufserfahrungen und Sprachkenntnisse bleiben Zeichen für Zeichen so, wie sie
in der Vorlage stehen.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table

from ..models import CVAdaptation
from . import docx_tools as dt

HEADINGS = [
    "PERSÖNLICHE DATEN",
    "AUSBILDUNG",
    "BERUFSERFAHRUNGEN",
    "PROJEKTE",
    "SPRACHKENNTNISSE",
    "BESONDERE KENNTNISSE UND FÄHIGKEITEN",
]
EDUCATION = "AUSBILDUNG"
PROJECTS = "PROJEKTE"
SKILLS = "BESONDERE KENNTNISSE UND FÄHIGKEITEN"

EDITABLE_SECTIONS = (EDUCATION, PROJECTS, SKILLS)


def _needles(anchor: str) -> list[str]:
    """Kennungen, unter denen eine Vorlagenzeile gesucht wird.

    education_anchors() reicht der KI 'Kennung | Titelzeile' — genau so kommt
    die Kennung auch zurück. Diese Form steht in keiner Zelle, also werden
    zusätzlich beide Teile für sich geprüft.
    """
    parts = [anchor] + (anchor.split("|", 1) if "|" in anchor else [])
    return [p.strip().lower() for p in parts if p.strip()]


def _match_table(tables: list[Table], anchor: str) -> Table | None:
    needles = _needles(anchor)
    for needle in needles:
        for table in tables:
            if dt.table_anchor(table).lower() == needle:
                return table
    for needle in needles:
        for table in tables:
            row = table.rows[0]
            haystack = f"{row.cells[0].text} {row.cells[1].text}".lower()
            if needle in haystack:
                return table
    return None


def _section_tables(document: DocumentType, section: str) -> list[Table]:
    return dt.section_tables(document, section, [h for h in HEADINGS if h != section])


def apply_education(document: DocumentType, adaptation: CVAdaptation) -> list[str]:
    """Stichpunkte der Ausbildungseinträge umformulieren.

    Reihenfolge und Bestand bleiben unangetastet: Ein Lebenslauf ohne
    chronologische Ausbildung oder mit fehlendem Abschluss fällt auf.
    """
    if not adaptation.education_edits:
        return []

    warnings: list[str] = []
    tables = _section_tables(document, EDUCATION)
    if not tables:
        return ["Abschnitt AUSBILDUNG in der Vorlage nicht gefunden — unverändert übernommen."]

    for edit in adaptation.education_edits:
        table = _match_table(tables, edit.anchor)
        if table is None:
            warnings.append(
                f"Ausbildungseintrag '{edit.anchor}' nicht in der Vorlage gefunden — übersprungen."
            )
            continue
        if edit.drop:
            warnings.append(
                f"Ausbildungseintrag '{edit.anchor}' sollte entfernt werden — abgelehnt, "
                "Ausbildungseinträge bleiben vollständig."
            )
            continue
        if edit.bullets:
            dt.set_bullets(table.rows[0].cells[1], edit.bullets)
    return warnings


def apply_projects(document: DocumentType, adaptation: CVAdaptation) -> list[str]:
    """Projekte umsortieren und Stichpunkte ersetzen. Gibt Warnungen zurück."""
    warnings: list[str] = []
    tables = _section_tables(document, PROJECTS)
    if not tables:
        return ["Abschnitt PROJEKTE in der Vorlage nicht gefunden — unverändert übernommen."]

    for edit in adaptation.project_edits:
        table = _match_table(tables, edit.anchor)
        if table is None:
            warnings.append(f"Projekt '{edit.anchor}' nicht in der Vorlage gefunden — übersprungen.")
            continue
        if edit.drop:
            dt.delete_table(table)
            tables = [t for t in tables if t is not table]
            continue
        if edit.bullets:
            dt.set_bullets(table.rows[0].cells[1], edit.bullets)

    if adaptation.project_order:
        ordered: list[Table] = []
        for anchor in adaptation.project_order:
            table = _match_table(tables, anchor)
            if table is not None and table not in ordered:
                ordered.append(table)
        ordered += [t for t in tables if t not in ordered]
        if len(ordered) == len(tables):
            dt.reorder_tables(tables, ordered)
        else:
            warnings.append("Projektreihenfolge konnte nicht angewendet werden.")

    return warnings


def apply_skills(document: DocumentType, adaptation: CVAdaptation) -> list[str]:
    """Zeilen unter BESONDERE KENNTNISSE ersetzen."""
    if not adaptation.skill_lines:
        return []

    blocks = dt.section_blocks(document, SKILLS, [])
    paragraphs = [b for b in blocks if hasattr(b, "runs") and b.text.strip()]
    if not paragraphs:
        return ["Abschnitt BESONDERE KENNTNISSE nicht gefunden — unverändert übernommen."]

    lines = adaptation.skill_lines
    for paragraph, text in zip(paragraphs, lines):
        dt.set_text_preserving(paragraph, text)

    if len(lines) > len(paragraphs):
        anchor = paragraphs[-1]
        for text in lines[len(paragraphs) :]:
            anchor = dt.clone_paragraph_after(anchor, text)

    for paragraph in paragraphs[len(lines) :]:
        dt.delete_paragraph(paragraph)

    return []


def render_cv(template: Path, adaptation: CVAdaptation, output: Path) -> tuple[Path, list[str]]:
    """Erzeugt den angepassten Lebenslauf; gibt Pfad und Warnungen zurück."""
    document = Document(str(template))
    warnings = apply_education(document, adaptation)
    warnings += apply_projects(document, adaptation)
    warnings += apply_skills(document, adaptation)
    dt.sync_table_grids(document)

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return output, warnings


def template_facts(template: Path) -> str:
    """Liest die Vorlage als Faktenblatt für die KI aus.

    Damit gibt es nur eine Quelle der Wahrheit: den Lebenslauf selbst.
    """
    document = Document(str(template))
    lines: list[str] = []
    for block in dt.iter_block_items(document):
        if isinstance(block, Table):
            row = block.rows[0]
            left = row.cells[0].text.strip()
            cell = row.cells[1]
            paragraphs = [p.text.strip() for p in cell.paragraphs if p.text.strip()]
            if paragraphs:
                head = paragraphs[0]
                lines.append(f"- [{left}] {head}")
                lines.extend(f"    {p}" for p in paragraphs[1:])
        else:
            text = block.text.strip()
            if not text:
                continue
            if text.upper() in HEADINGS:
                lines.append(f"\n## {text.upper()}")
            else:
                lines.append(text)
    return "\n".join(lines).strip()


def project_anchors(template: Path) -> list[str]:
    """Kennungen der Projekt-Zeilen (linke Tabellenspalte) in Vorlagenreihenfolge."""
    document = Document(str(template))
    return [dt.table_anchor(t) for t in _section_tables(document, PROJECTS)]


def education_anchors(template: Path) -> list[str]:
    """Kennungen der Ausbildungseinträge, jeweils mit Titelzeile zur Orientierung."""
    document = Document(str(template))
    anchors = []
    for table in _section_tables(document, EDUCATION):
        row = table.rows[0]
        head = next((p.text.strip() for p in row.cells[1].paragraphs if p.text.strip()), "")
        anchors.append(f"{row.cells[0].text.strip()} | {head}")
    return anchors


def skill_lines(template: Path) -> list[str]:
    document = Document(str(template))
    blocks = dt.section_blocks(document, SKILLS, [])
    return [b.text.strip() for b in blocks if hasattr(b, "runs") and b.text.strip()]
