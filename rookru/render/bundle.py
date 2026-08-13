"""Zusammenführen der Bewerbungsunterlagen zu einem PDF."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


class BundleError(RuntimeError):
    """Eine Anlage fehlt oder ist kein lesbares PDF."""


def merge_pdfs(parts: list[tuple[str, Path]], output: Path, title: str = "") -> Path:
    """Führt `parts` in der übergebenen Reihenfolge zu einem PDF zusammen.

    `parts` ist eine Liste aus (Label, Pfad). Für jeden Teil wird ein Lesezeichen
    mit dem Label gesetzt, damit das Bündel navigierbar bleibt.
    """
    if not parts:
        raise BundleError("Keine Dokumente zum Zusammenführen übergeben")

    writer = PdfWriter()
    for label, path in parts:
        path = Path(path)
        if not path.is_file():
            raise BundleError(f"Anlage fehlt: {label} ({path})")
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                reader.decrypt("")
            start = len(writer.pages)
            for page in reader.pages:
                writer.add_page(page)
        except BundleError:
            raise
        except Exception as exc:  # pypdf wirft je nach Defekt sehr verschiedene Fehler
            raise BundleError(f"'{label}' ({path.name}) ist kein lesbares PDF: {exc}") from exc
        writer.add_outline_item(label, start)

    if title:
        writer.add_metadata({"/Title": title})

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    return output
