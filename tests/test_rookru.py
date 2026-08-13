"""Tests, die ohne Netzwerk, API-Schlüssel und private Dateien laufen.

Die docx-Vorlagen werden im Test selbst erzeugt, damit nichts aus privat/
gebraucht wird.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from rookru.compose import StubComposer, detect_focus
from rookru.config import ConfigError, FocusRule, load_settings, slugify
from rookru.models import CVAdaptation, Job, LetterContent, SectionEdit, TemplateData
from rookru.pipeline import compact_name, describe_fit
from rookru.render import cv as cv_render
from rookru.render import docx_tools as dt
from rookru.render import letter as letter_render
from rookru.render.bundle import BundleError, merge_pdfs
from rookru.sources.local import load_jobs_file

# ---------------------------------------------------------------- Hilfsvorlagen


def make_letter_template(path: Path) -> Path:
    document = Document()
    for text in (
        "Max Muster",
        "Wien, {{DATUM}}",
        "{{FIRMA_NAME}}",
        "{{FIRMA_ABTEILUNG}}",
        "{{FIRMA_STRASSE}}",
        "{{FIRMA_PLZ_ORT}}",
        "Bewerbung als {{STELLE}}",
        "Sehr geehrte Damen und Herren,",
        "{{ABSATZ_1}}",
        "{{ABSATZ_2}}",
        "Mit freundlichen Grüßen,",
    ):
        document.add_paragraph(text)
    document.save(str(path))
    return path


def make_cv_template(path: Path) -> Path:
    document = Document()
    document.add_paragraph("Max Muster")
    document.add_paragraph("AUSBILDUNG")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "2023 – dato"
    cell = table.rows[0].cells[1]
    cell.text = "Bachelorstudium Maschinenbau, TU Wien"
    cell.add_paragraph("●  Bachelorarbeit zu additiver Fertigung")
    document.add_paragraph("")
    document.add_paragraph("PROJEKTE")
    for anchor, head, bullets in (
        ("Drucker", "FDM-3D-Druck, privat", ["●  Halterungen konstruiert", "●  PETG und TPU"]),
        ("GitHub", "github.com/muster", ["●  Python-Projekte"]),
    ):
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = anchor
        cell = table.rows[0].cells[1]
        cell.text = head
        for bullet in bullets:
            cell.add_paragraph(bullet)
        document.add_paragraph("")
    document.add_paragraph("SPRACHKENNTNISSE")
    document.add_paragraph("Deutsch: Muttersprache")
    document.add_paragraph("BESONDERE KENNTNISSE UND FÄHIGKEITEN")
    document.add_paragraph("CAD-Kenntnisse: Creo")
    document.add_paragraph("Programmierkenntnisse: Python")
    document.save(str(path))
    return path


@pytest.fixture
def cv_template(tmp_path: Path) -> Path:
    return make_cv_template(tmp_path / "lebenslauf.docx")


@pytest.fixture
def letter_template(tmp_path: Path) -> Path:
    return make_letter_template(tmp_path / "brief.docx")


# ------------------------------------------------------------------ docx_tools


def test_platzhalter_ueber_mehrere_runs(tmp_path: Path) -> None:
    """Word zerlegt Platzhalter oft in mehrere Runs — das muss trotzdem greifen."""
    document = Document()
    paragraph = document.add_paragraph()
    for teil in ("{{FIR", "MA_", "NAME}}"):
        paragraph.add_run(teil)
    dt.replace_in_paragraph(paragraph, {"{{FIRMA_NAME}}": "ACME GmbH"})
    assert paragraph.text == "ACME GmbH"


def test_platzhalter_behaelt_formatierung(tmp_path: Path) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("{{STELLE}}")
    run.bold = True
    dt.replace_in_paragraph(paragraph, {"{{STELLE}}": "Werkstudent"})
    assert paragraph.runs[0].bold is True
    assert paragraph.text == "Werkstudent"


def test_umgebender_text_bleibt_erhalten() -> None:
    document = Document()
    paragraph = document.add_paragraph("Bewerbung als {{STELLE}} (m/w/d)")
    dt.replace_in_paragraph(paragraph, {"{{STELLE}}": "Werkstudent"})
    assert paragraph.text == "Bewerbung als Werkstudent (m/w/d)"


def test_bullets_ersetzen_und_ergaenzen(cv_template: Path) -> None:
    document = Document(str(cv_template))
    tables = dt.section_tables(document, "PROJEKTE", ["SPRACHKENNTNISSE"])
    cell = tables[0].rows[0].cells[1]
    dt.set_bullets(cell, ["Erster Punkt", "Zweiter Punkt", "Dritter Punkt"])
    bullets = [p.text for p in dt.cell_bullets(cell)]
    assert bullets == ["●  Erster Punkt", "●  Zweiter Punkt", "●  Dritter Punkt"]


def test_bullets_kuerzen(cv_template: Path) -> None:
    document = Document(str(cv_template))
    tables = dt.section_tables(document, "PROJEKTE", ["SPRACHKENNTNISSE"])
    cell = tables[0].rows[0].cells[1]
    dt.set_bullets(cell, ["Nur einer"])
    assert len(dt.cell_bullets(cell)) == 1


# ------------------------------------------------------------------- Lebenslauf


def test_projekte_umsortieren(cv_template: Path, tmp_path: Path) -> None:
    adaptation = CVAdaptation(project_order=["GitHub", "Drucker"])
    output, warnings = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    assert warnings == []
    assert cv_render.project_anchors(output) == ["GitHub", "Drucker"]


def test_unbekanntes_projekt_warnt_statt_zu_scheitern(
    cv_template: Path, tmp_path: Path
) -> None:
    adaptation = CVAdaptation(project_edits=[SectionEdit(anchor="Gibt es nicht", bullets=["x"])])
    _, warnings = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    assert any("nicht in der Vorlage" in w for w in warnings)


def test_unveraenderte_abschnitte_bleiben_gleich(cv_template: Path, tmp_path: Path) -> None:
    """Sprachkenntnisse dürfen sich nie ändern — sie sind nicht freigegeben."""
    adaptation = CVAdaptation(project_order=["GitHub", "Drucker"], skill_lines=["CAD: Creo"])
    output, _ = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    texte = [p.text for p in Document(str(output)).paragraphs]
    assert "Deutsch: Muttersprache" in texte


def test_kenntnis_zeilen_ersetzen(cv_template: Path, tmp_path: Path) -> None:
    adaptation = CVAdaptation(skill_lines=["3D-Druck: Prusa", "CAD: Fusion 360", "Extra: Zeile"])
    output, _ = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    assert cv_render.skill_lines(output) == [
        "3D-Druck: Prusa",
        "CAD: Fusion 360",
        "Extra: Zeile",
    ]


def test_faktenblatt_enthaelt_alle_abschnitte(cv_template: Path) -> None:
    facts = cv_render.template_facts(cv_template)
    assert "## PROJEKTE" in facts
    assert "Halterungen konstruiert" in facts


# -------------------------------------------------------- Motivationsschreiben


def test_brief_fuellt_alle_platzhalter(letter_template: Path, tmp_path: Path) -> None:
    content = LetterContent(
        subject="Werkstudent Maschinenbau",
        salutation="Sehr geehrte Frau Muster,",
        paragraphs=["Erster Absatz.", "Zweiter Absatz."],
        company_name="ACME GmbH",
        company_department="Personal",
        company_street="Teststraße 1",
        company_postal_city="1010 Wien",
    )
    output = letter_render.render_letter(letter_template, content, tmp_path / "brief_out.docx")
    assert letter_render.check_placeholders(output) == set()
    text = "\n".join(p.text for p in Document(str(output)).paragraphs)
    assert "Bewerbung als Werkstudent Maschinenbau" in text
    assert "ACME GmbH" in text


def test_mehr_absaetze_als_platzhalter(letter_template: Path, tmp_path: Path) -> None:
    """Die Vorlage hat zwei Absatz-Slots; drei Absätze müssen trotzdem passen."""
    content = LetterContent(
        subject="Stelle",
        salutation="Sehr geehrte Damen und Herren,",
        paragraphs=["Eins.", "Zwei.", "Drei."],
        company_name="ACME GmbH",
    )
    output = letter_render.render_letter(letter_template, content, tmp_path / "brief3.docx")
    text = "\n".join(p.text for p in Document(str(output)).paragraphs)
    assert letter_render.check_placeholders(output) == set()
    for absatz in ("Eins.", "Zwei.", "Drei."):
        assert absatz in text


def test_leere_adresszeile_wird_entfernt(letter_template: Path, tmp_path: Path) -> None:
    content = LetterContent(
        subject="Stelle",
        salutation="Sehr geehrte Damen und Herren,",
        paragraphs=["Text."],
        company_name="ACME GmbH",
    )
    output = letter_render.render_letter(letter_template, content, tmp_path / "brief_kurz.docx")
    texte = [p.text for p in Document(str(output)).paragraphs]
    assert "" not in [t for t in texte if "{{" in t]
    assert letter_render.check_placeholders(output) == set()


def test_datum_deutsch_formatiert() -> None:
    from datetime import date

    assert letter_render.format_date(date(2026, 8, 13)) == "13. August 2026"


# ------------------------------------------------------------------ Schwerpunkt


def _rules() -> list[FocusRule]:
    return [
        FocusRule("it", "IT", ["python", "sql"], ["GitHub"]),
        FocusRule("konstruktion", "Konstruktion", ["cad", "3d-druck"], ["Prusa MK3S+"]),
    ]


def test_schwerpunkt_it() -> None:
    job = Job(id="1", title="Werkstudent Datenauswertung", company="X",
              description="Python und SQL für Messdaten")
    assert detect_focus(job, _rules()).key == "it"


def test_schwerpunkt_konstruktion() -> None:
    job = Job(id="2", title="Aushilfe 3D-Druck", company="Y",
              description="CAD-Konstruktion von Bauteilen")
    assert detect_focus(job, _rules()).key == "konstruktion"


def test_ohne_treffer_kein_schwerpunkt() -> None:
    job = Job(id="3", title="Bürokraft", company="Z", description="Ablage und Telefon")
    assert detect_focus(job, _rules()) is None


# ----------------------------------------------------------------- Bündel & Co.


def test_buendel_meldet_fehlende_anlage(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="Anlage fehlt"):
        merge_pdfs([("Zeugnis", tmp_path / "gibtsnicht.pdf")], tmp_path / "b.pdf")


def test_buendel_ohne_teile() -> None:
    with pytest.raises(BundleError):
        merge_pdfs([], Path("/tmp/leer.pdf"))


def test_dateinamen_kompakt() -> None:
    assert compact_name("Knorr-Bremse GmbH") == "KnorrBremse"
    assert compact_name("Beispiel Automation GmbH") == "BeispielAutomation"


def test_slugify() -> None:
    assert slugify("Werkstudent Maschinenbau (m/w/d)") == "werkstudent-maschinenbau-m-w-d"


def test_fit_meldung() -> None:
    assert describe_fit("Lebenslauf", (1.0, 1.0)) == []
    nur_abstaende = describe_fit("Lebenslauf", (1.0, 0.6))[0]
    assert "60%" in nur_abstaende and "Schrift" not in nur_abstaende
    auch_schrift = describe_fit("Lebenslauf", (0.9, 0.5))[0]
    assert "Schrift" in auch_schrift and "90%" in auch_schrift


def test_stellen_datei_braucht_pflichtfelder(tmp_path: Path) -> None:
    path = tmp_path / "stellen.yaml"
    path.write_text("- firma: ACME\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="titel"):
        load_jobs_file(path)


def test_fehlende_konfiguration_meldet_pfad(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="profil.example.yaml"):
        load_settings(tmp_path / "fehlt.yaml")


def test_stub_composer_liefert_vollstaendiges_ergebnis(
    tmp_path: Path, cv_template: Path, letter_template: Path
) -> None:
    profil = tmp_path / "profil.yaml"
    profil.write_text(
        f"""
bewerber:
  name: Max Muster
vorlagen:
  motivationsschreiben: {letter_template}
  lebenslauf: {cv_template}
schwerpunkte:
  - key: konstruktion
    label: Konstruktion
    keywords: [3d-druck]
    hervorheben: [GitHub]
""",
        encoding="utf-8",
    )
    settings = load_settings(profil)
    job = Job(id="1", title="Aushilfe 3D-Druck", company="ACME GmbH", description="3d-druck")
    template = TemplateData(
        facts="fakten", projects=["Drucker", "GitHub"], skills=["CAD: Creo"]
    )
    focus, letter, adaptation = StubComposer().compose(settings, job, template)
    assert focus.key == "konstruktion"
    assert letter.paragraphs and "TESTMODUS" in letter.paragraphs[0]
    assert adaptation.project_order[0] == "GitHub"  # 'hervorheben' zieht nach vorne


# ------------------------------------------------------------------ Ausbildung


def test_ausbildung_bullets_werden_umformuliert(cv_template: Path, tmp_path: Path) -> None:
    adaptation = CVAdaptation(
        education_edits=[
            SectionEdit(
                anchor="2023 – dato",
                bullets=["Bachelorarbeit: Schutzeinhausung, konstruiert in Fusion 360"],
            )
        ]
    )
    output, warnings = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    assert warnings == []
    text = "\n".join(p.text for p in Document(str(output)).tables[0].rows[0].cells[1].paragraphs)
    assert "Schutzeinhausung" in text
    assert "Bachelorstudium Maschinenbau, TU Wien" in text  # Titelzeile bleibt


def test_ausbildungseintrag_wird_nie_entfernt(cv_template: Path, tmp_path: Path) -> None:
    """Ein gelöschter Ausbildungseintrag wäre eine Lücke im Lebenslauf."""
    adaptation = CVAdaptation(
        education_edits=[SectionEdit(anchor="2023 – dato", bullets=[], drop=True)]
    )
    output, warnings = cv_render.render_cv(cv_template, adaptation, tmp_path / "out.docx")
    assert any("abgelehnt" in w for w in warnings)
    assert len(cv_render.education_anchors(output)) == 1


def test_ausbildungskennungen_mit_titelzeile(cv_template: Path) -> None:
    anchors = cv_render.education_anchors(cv_template)
    assert anchors == ["2023 – dato | Bachelorstudium Maschinenbau, TU Wien"]


def test_ausbildung_ohne_anpassung_bleibt_unveraendert(
    cv_template: Path, tmp_path: Path
) -> None:
    output, warnings = cv_render.render_cv(cv_template, CVAdaptation(), tmp_path / "out.docx")
    assert warnings == []
    text = "\n".join(p.text for p in Document(str(output)).tables[0].rows[0].cells[1].paragraphs)
    assert "Bachelorarbeit zu additiver Fertigung" in text
