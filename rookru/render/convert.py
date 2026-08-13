"""docx → pdf über LibreOffice, Seitenzählung und Ein-Seiten-Anpassung."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from .docx_tools import scale_document

# Stufen, in denen bei Überlänge verkleinert wird: (Schriftfaktor, Abstandsfaktor).
# Zuerst nur die Abstände — das Schriftbild der Vorlage bleibt dabei erhalten.
SHRINK_STEPS: tuple[tuple[float, float], ...] = (
    (1.00, 1.00),
    (1.00, 0.70),
    (0.98, 0.60),
    (0.96, 0.50),
    (0.94, 0.45),
    (0.90, 0.40),
    (0.86, 0.35),
    (0.82, 0.30),
)


class ConversionError(RuntimeError):
    """LibreOffice fehlt oder konnte die Datei nicht konvertieren."""


def find_soffice() -> str:
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found
    raise ConversionError(
        "LibreOffice (soffice) wurde nicht gefunden. Ohne LibreOffice gibt es keine PDFs.\n"
        "  Debian/Ubuntu: sudo apt install libreoffice-writer\n"
        "  macOS:         brew install --cask libreoffice"
    )


def docx_to_pdf(docx_path: Path, output_dir: Path | None = None, timeout: int = 180) -> Path:
    """Konvertiert eine docx-Datei nach PDF und gibt den PDF-Pfad zurück."""
    soffice = find_soffice()
    docx_path = Path(docx_path).resolve()
    output_dir = Path(output_dir or docx_path.parent).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Eigenes Nutzerprofil je Aufruf, sonst blockieren sich mehrere
    # LibreOffice-Läufe gegenseitig.
    with tempfile.TemporaryDirectory(prefix="rookru-lo-") as profile_dir:
        result = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{profile_dir}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    pdf_path = output_dir / (docx_path.stem + ".pdf")
    if result.returncode != 0 or not pdf_path.is_file():
        detail = (result.stderr or result.stdout or "").strip()
        raise ConversionError(
            f"Konvertierung von {docx_path.name} fehlgeschlagen "
            f"(exit {result.returncode}): {detail}"
        )
    return pdf_path


def page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def fill_ratio(pdf_path: Path, docx_path: Path) -> float:
    """Anteil der Satzhöhe, den der Text auf der letzten Seite tatsächlich nutzt.

    Ein Motivationsschreiben, das nach zwei Dritteln der Seite endet, wirkt
    dünn — auffallen tut das aber erst im fertigen PDF. Gemessen wird gegen
    die Satzhöhe der Vorlage (Seitenhöhe minus Ränder), nicht gegen die
    Blatthöhe, sonst zählen die Ränder als ungenutzt.
    """
    reader = PdfReader(str(pdf_path))
    page = reader.pages[-1]
    section = Document(str(docx_path)).sections[0]
    top = section.top_margin.pt
    bottom = section.bottom_margin.pt
    satzhoehe = float(page.mediabox.height) - top - bottom
    if satzhoehe <= 0:
        return 1.0

    tiefste: list[float] = []
    page.extract_text(
        visitor_text=lambda text, cm, tm, font, size: (
            tiefste.append(tm[5]) if text.strip() else None
        )
    )
    if not tiefste:
        return 0.0
    genutzt = float(page.mediabox.height) - top - min(tiefste)
    return max(0.0, min(genutzt / satzhoehe, 1.0))


def fit_to_one_page(
    docx_path: Path,
    pdf_dir: Path | None = None,
    steps: tuple[tuple[float, float], ...] = SHRINK_STEPS,
) -> tuple[Path, int, tuple[float, float]]:
    """Konvertiert nach PDF und verkleinert notfalls, bis eine Seite reicht.

    Zurück kommen PDF-Pfad, Seitenzahl und die verwendete Stufe
    (Schriftfaktor, Abstandsfaktor). Bleibt das Dokument auch auf der engsten
    Stufe zweiseitig, wird diese Fassung zurückgegeben — die Seitenzahl > 1
    macht das für den Aufrufer sichtbar, statt still etwas abzuschneiden.
    """
    docx_path = Path(docx_path).resolve()
    original = docx_path.with_suffix(".orig.docx")
    shutil.copy2(docx_path, original)

    try:
        pdf_path = docx_to_pdf(docx_path, pdf_dir)
        pages = page_count(pdf_path)
        if pages <= 1:
            return pdf_path, pages, steps[0]

        for step in steps[1:]:
            document = Document(str(original))
            scale_document(document, step[0], step[1])
            document.save(str(docx_path))
            pdf_path = docx_to_pdf(docx_path, pdf_dir)
            pages = page_count(pdf_path)
            if pages <= 1:
                return pdf_path, pages, step

        return pdf_path, pages, steps[-1]
    finally:
        original.unlink(missing_ok=True)
