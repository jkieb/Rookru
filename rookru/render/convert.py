"""docx → pdf über LibreOffice, Seitenzählung und Ein-Seiten-Anpassung."""

from __future__ import annotations

import os
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


# Orte, an denen LibreOffice installiert wird, ohne im PATH zu landen —
# unter Windows und macOS ist das der Normalfall.
KNOWN_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/snap/bin/libreoffice",
)


def find_soffice() -> str:
    """Sucht das LibreOffice-Programm — PATH, Umgebungsvariable, übliche Orte."""
    override = os.environ.get("SOFFICE_PATH", "").strip().strip('"')
    if override:
        if Path(override).is_file():
            return override
        raise ConversionError(
            f"SOFFICE_PATH zeigt auf eine Datei, die es nicht gibt: {override}"
        )

    for candidate in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found

    for candidate in KNOWN_PATHS:
        if Path(candidate).is_file():
            return candidate

    raise ConversionError(
        "LibreOffice wurde nicht gefunden. Ohne LibreOffice gibt es keine PDFs.\n"
        "  Windows:       winget install TheDocumentFoundation.LibreOffice\n"
        "  macOS:         brew install --cask libreoffice\n"
        "  Debian/Ubuntu: sudo apt install libreoffice-writer\n"
        "Liegt es woanders, den vollen Pfad in .env eintragen, z. B.\n"
        r'  SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe'
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
