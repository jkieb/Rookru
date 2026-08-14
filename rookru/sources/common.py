"""Was sich alle Stellenquellen teilen."""

from __future__ import annotations

from ..config import SearchSettings
from ..models import Job


def excluded(job: Job, settings: SearchSettings) -> bool:
    """Unvollständige Treffer und Ausschlusswörter aus profil.yaml aussortieren."""
    if not job.title or not job.company:
        return True
    haystack = job.haystack()
    return any(word in haystack for word in settings.exclude)


def dedup_key(job: Job) -> str:
    """Kennung für Doppeltreffer — auch über Quellgrenzen hinweg.

    Dieselbe Stelle steht oft bei mehreren Börsen, mit unterschiedlichen IDs.
    Firma und Titel sind das, was dann noch übereinstimmt.
    """
    from ..config import slugify

    return f"{slugify(job.company)}|{slugify(job.title)}"
