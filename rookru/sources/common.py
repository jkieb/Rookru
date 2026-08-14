"""Was sich alle Stellenquellen teilen."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..config import SearchSettings
from ..models import Job

# HTTP-Kopfzeilen muessen ASCII sein (RFC 7230). Ein Umlaut hier laesst
# Jooble die Anfrage mit HTTP 400 abweisen — daher bewusst ohne.
USER_AGENT = "rookru/0.1 (persoenliche Bewerbungsautomatisierung)"

TAGS = re.compile(r"<[^>]+>")
ENTITIES = {"&amp;": "&", "&nbsp;": " ", "&quot;": '"', "&#39;": "'", "&lt;": "<", "&gt;": ">"}


def clean_text(value: object) -> str:
    """Markup aus Anzeigentexten entfernen.

    Börsen heben die Suchwörter im Anriss mit <b> hervor und liefern
    HTML-Entities — im Motivationsschreiben hat beides nichts verloren.
    """
    text = TAGS.sub("", str(value or ""))
    for entity, zeichen in ENTITIES.items():
        text = text.replace(entity, zeichen)
    return " ".join(text.split())


def zu_alt(job: Job, max_days_old: int) -> bool:
    """Prüft das Anzeigendatum — für Quellen ohne eigenen Altersfilter.

    Ohne Datum wird nichts aussortiert: lieber ein Treffer zu viel als eine
    Stelle, die nur an einer fehlenden Angabe scheitert.
    """
    if not max_days_old or not job.created:
        return False
    try:
        erschienen = datetime.fromisoformat(job.created).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return erschienen < datetime.now(timezone.utc) - timedelta(days=max_days_old)


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
