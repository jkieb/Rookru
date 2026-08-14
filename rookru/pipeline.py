"""Ablauf je Stelle: Text erzeugen, Dokumente bauen, Bündel zusammenstellen."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .config import Settings
from .models import Application, Job, TemplateData
from .render import bundle, convert, cv, letter
from .sources.common import UNBEKANNT

LETTER_LABEL = "Motivationsschreiben"
CV_LABEL = "Lebenslauf"


def compact_name(value: str, limit: int = 24) -> str:
    """'Knorr-Bremse GmbH' → 'KnorrBremse' — für Dateinamen."""
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"\b(GmbH|AG|KG|SE|mbH|Co|OG|e\.?U\.?|Ltd|Inc)\b\.?", " ", value, flags=re.I)
    words = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(w[:1].upper() + w[1:] for w in words)[:limit] or "Firma"


def describe_fit(label: str, step: tuple[float, float]) -> list[str]:
    """Meldet, wenn zum Einhalten der einen Seite verkleinert werden musste."""
    font, spacing = step
    if font >= 1.0 and spacing >= 1.0:
        return []
    if font >= 1.0:
        return [f"{label}: Absatzabstände auf {spacing:.0%} gestaucht, um auf eine Seite zu passen."]
    return [
        f"{label}: Schrift auf {font:.0%} und Abstände auf {spacing:.0%} verkleinert, "
        "um auf eine Seite zu passen."
    ]


MIN_FILL = 0.88  # darunter wirkt das Blatt halb leer


def describe_fill(ratio: float, words: int, max_words: int) -> list[str]:
    """Meldet ein Motivationsschreiben, das die Seite nicht ausfüllt."""
    if ratio >= MIN_FILL:
        return []
    return [
        f"Motivationsschreiben füllt nur {ratio:.0%} der Seite ({words} Wörter) — "
        f"brief.min_woerter anheben (max_woerter steht auf {max_words})."
    ]


def describe_address(job: Job) -> list[str]:
    """Meldet einen unvollständigen Empfängerblock.

    Adzuna liefert weder Straße noch Abteilung, und bei Personalberatungen
    steht dort ohnehin die Beratung statt des Unternehmens. Beides fällt im
    fertigen Brief kaum auf — deshalb hier ausdrücklich.
    """
    warnungen = []
    if job.company == UNBEKANNT:
        # EURES speist österreichische Anzeigen anonymisiert ein; der Name
        # steht dann nur im Fließtext der Ausschreibung.
        warnungen.append(
            "Arbeitgeber nicht genannt — im Brief steht deshalb "
            f"'{UNBEKANNT}'. Der Name steht meist im Ausschreibungstext."
        )
    fehlt = [name for name, wert in (("Straße", job.street), ("PLZ/Ort", job.postal_city))
             if not wert.strip()]
    if fehlt:
        warnungen.append(
            f"Empfängeradresse unvollständig ({', '.join(fehlt)} fehlt) — für den Postweg "
            "selbst ergänzen oder die Stelle über --stellen mit voller Adresse erfassen."
        )
    return warnungen


def read_template(cv_template: Path) -> TemplateData:
    """Liest Faktenblatt und Abschnittskennungen aus der Lebenslauf-Vorlage."""
    return TemplateData(
        facts=cv.template_facts(cv_template),
        projects=cv.project_anchors(cv_template),
        education=cv.education_anchors(cv_template),
        skills=cv.skill_lines(cv_template),
    )


def load_style_example(settings: Settings) -> str:
    candidate = settings.templates.letter.parent / "stilbeispiel.txt"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8").strip()
    return ""


def build_application(
    settings: Settings,
    job: Job,
    composer,
    template_data: TemplateData | None = None,
    style_example: str | None = None,
    output_root: Path | None = None,
) -> Application:
    """Erzeugt alle Dokumente für eine Stelle."""
    template_data = template_data or read_template(settings.templates.cv)
    style_example = load_style_example(settings) if style_example is None else style_example
    warnings: list[str] = []

    focus, content, adaptation = composer.compose(settings, job, template_data, style_example)

    today = date.today()
    firma = compact_name(job.company)
    root = output_root or settings.output_dir
    directory = root / f"{today:%Y_%m_%d}_{firma}_{compact_name(job.title, 28)}"
    directory.mkdir(parents=True, exist_ok=True)

    nachname = settings.applicant.name.split()[-1] if settings.applicant.name else "Bewerbung"

    # Motivationsschreiben
    letter_docx = directory / f"{LETTER_LABEL}_{nachname}_{firma}.docx"
    letter.render_letter(settings.templates.letter, content, letter_docx)
    offen = letter.check_placeholders(letter_docx)
    if offen:
        warnings.append(f"Nicht ersetzte Platzhalter im Brief: {', '.join(sorted(offen))}")
    warnings.extend(describe_address(job))
    letter_pdf, letter_pages, letter_step = convert.fit_to_one_page(letter_docx, directory)
    if letter_pages > 1:
        warnings.append(
            f"Motivationsschreiben hat {letter_pages} Seiten — Text kürzen "
            f"(brief.max_woerter senken, aktuell {content.word_count()} Wörter)."
        )
    else:
        warnings.extend(describe_fit("Motivationsschreiben", letter_step))
        # Nur ungestaucht ist ein niedriger Füllgrad ein Zeichen für zu wenig
        # Text — musste gestaucht werden, war der Brief im Gegenteil zu lang.
        if letter_step == (1.0, 1.0):
            warnings.extend(
                describe_fill(
                    convert.fill_ratio(letter_pdf, letter_docx),
                    content.word_count(),
                    settings.letter.max_words,
                )
            )

    # Lebenslauf
    cv_docx = directory / f"{CV_LABEL}_{nachname}_{firma}.docx"
    _, cv_warnings = cv.render_cv(settings.templates.cv, adaptation, cv_docx)
    warnings.extend(cv_warnings)
    cv_pdf, cv_pages, cv_step = convert.fit_to_one_page(cv_docx, directory)
    if cv_pages > 1:
        warnings.append(f"Lebenslauf hat {cv_pages} Seiten — Stichpunkte kürzen.")
    else:
        warnings.extend(describe_fit("Lebenslauf", cv_step))

    # Bündel in der festgelegten Reihenfolge
    parts = [(LETTER_LABEL, letter_pdf), (CV_LABEL, cv_pdf)]
    for attachment in settings.attachments:
        if attachment.path.is_file():
            parts.append((attachment.label, attachment.path))
        else:
            warnings.append(f"Anlage fehlt und wurde ausgelassen: {attachment.label}")

    bundle_pdf = directory / f"{today:%Y_%m_%d}_Bewerbungsunterlagen_{firma}.pdf"
    bundle.merge_pdfs(
        parts,
        bundle_pdf,
        title=f"Bewerbungsunterlagen {settings.applicant.name} — {job.company}",
    )
    bundle_pages = convert.page_count(bundle_pdf)

    application = Application(
        job=job,
        focus=focus,
        letter=content,
        adaptation=adaptation,
        directory=directory,
        letter_docx=letter_docx,
        letter_pdf=letter_pdf,
        cv_docx=cv_docx,
        cv_pdf=cv_pdf,
        bundle_pdf=bundle_pdf,
        letter_pages=letter_pages,
        cv_pages=cv_pages,
        bundle_pages=bundle_pages,
        warnings=warnings,
    )
    write_report(application)
    return application


def write_report(application: Application) -> Path:
    """Legt neben den Dokumenten eine bewerbung.json zum Nachlesen ab."""
    data = {
        "erstellt": date.today().isoformat(),
        "stelle": asdict(application.job),
        "schwerpunkt": asdict(application.focus),
        "brief": {
            "betreff": f"Bewerbung als {application.letter.subject}",
            "anrede": application.letter.salutation,
            "absaetze": application.letter.paragraphs,
            "woerter": application.letter.word_count(),
        },
        "lebenslauf_anpassung": asdict(application.adaptation),
        "seiten": {
            "motivationsschreiben": application.letter_pages,
            "lebenslauf": application.cv_pages,
            "buendel": application.bundle_pages,
        },
        "warnungen": application.warnings,
    }
    path = application.directory / "bewerbung.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
