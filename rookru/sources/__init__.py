"""Stellenquellen: Adzuna, Careerjet und lokale YAML-Dateien."""

from __future__ import annotations

from ..config import FocusRule, SearchSettings
from ..models import Job
from .adzuna import AdzunaError
from .adzuna import search_jobs as search_adzuna
from .careerjet import CareerjetError
from .careerjet import search_jobs as search_careerjet
from .common import dedup_key, excluded
from .local import load_jobs_file

QUELLEN = {"adzuna": search_adzuna, "careerjet": search_careerjet}

__all__ = [
    "AdzunaError",
    "CareerjetError",
    "QUELLEN",
    "dedup_key",
    "excluded",
    "load_jobs_file",
    "rank_jobs",
    "search_all",
    "title_hits",
]


class SourceError(RuntimeError):
    """Keine einzige Quelle war erreichbar."""


def search_all(settings: SearchSettings) -> tuple[list[Job], list[str]]:
    """Sucht über alle konfigurierten Quellen und führt die Treffer zusammen.

    Zurück kommen die Stellen und die Fehlermeldungen einzelner Quellen: Fällt
    eine Börse aus, ist das kein Grund, die Treffer der anderen wegzuwerfen.
    Erst wenn keine Quelle liefert, fliegt ein Fehler.
    """
    jobs: dict[str, Job] = {}
    probleme: list[str] = []
    erreichbar = 0

    for name in settings.sources:
        suche = QUELLEN.get(name)
        if suche is None:
            probleme.append(f"Unbekannte Quelle '{name}' — bekannt: {', '.join(QUELLEN)}")
            continue
        try:
            treffer = suche(settings)
        except (AdzunaError, CareerjetError) as exc:
            probleme.append(str(exc))
            continue
        erreichbar += 1
        for job in treffer:
            jobs.setdefault(dedup_key(job), job)

    if not erreichbar:
        raise SourceError(
            "Keine Stellenquelle lieferte Ergebnisse:\n  " + "\n  ".join(probleme or ["—"])
        )
    return list(jobs.values()), probleme


def title_hits(job: Job, queries: list[str]) -> int:
    """Wie viele Wörter des besten Suchbegriffs im Stellentitel stehen.

    Die Schwerpunkt-Stichwörter sagen, welcher Teil des Profils passt — nicht,
    ob die Stelle überhaupt die gesuchte ist. Ohne dieses Maß landet eine
    Vollzeitstelle mit vielen Fachbegriffen vor der gesuchten Werkstudentenstelle.
    """
    title = job.title.lower()
    best = 0
    for query in queries:
        words = [w for w in query.lower().split() if len(w) > 2]
        if words:
            best = max(best, sum(1 for w in words if w in title))
    return best


def rank_jobs(
    jobs: list[Job],
    focus_rules: list[FocusRule],
    min_score: int = 0,
    queries: list[str] | None = None,
) -> list[tuple[Job, int, int]]:
    """Sortiert Treffer: erst Nähe zum Suchbegriff, dann passende Schwerpunkte.

    Gibt je Stelle (Stelle, Schwerpunkt-Treffer, Titel-Treffer) zurück;
    gefiltert wird weiterhin nur über die Schwerpunkt-Treffer (min_score).
    """
    queries = queries or []
    ranked = []
    for job in jobs:
        haystack = job.haystack()
        score = max((rule.score(haystack) for rule in focus_rules), default=0)
        if score >= min_score:
            ranked.append((job, score, title_hits(job, queries)))
    ranked.sort(key=lambda entry: (entry[2], entry[1]), reverse=True)
    return ranked
