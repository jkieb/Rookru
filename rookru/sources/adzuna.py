"""Stellensuche über die Adzuna Job-Search-API.

Zugangsdaten kommen aus den Umgebungsvariablen ADZUNA_APP_ID und
ADZUNA_APP_KEY (siehe .env.example). Registrierung: developer.adzuna.com
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import SearchSettings
from ..models import Job

API_BASE = "https://api.adzuna.com/v1/api/jobs"
USER_AGENT = "rookru/0.1 (persönliche Bewerbungsautomatisierung)"


class AdzunaError(RuntimeError):
    """Die Adzuna-API war nicht erreichbar oder hat einen Fehler gemeldet."""


def credentials() -> tuple[str, str]:
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise AdzunaError(
            "ADZUNA_APP_ID und ADZUNA_APP_KEY sind nicht gesetzt. "
            "Trage sie in .env ein (Vorlage: .env.example) oder exportiere sie in der Shell."
        )
    return app_id, app_key


def build_url(
    settings: SearchSettings, query: str, page: int, app_id: str, app_key: str
) -> str:
    params: dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": max(1, min(settings.results, 50)),
        "what": query,
        "content-type": "application/json",
    }
    if settings.where:
        params["where"] = settings.where
        if settings.distance_km:
            params["distance"] = settings.distance_km
    if settings.max_days_old:
        params["max_days_old"] = settings.max_days_old
    if settings.contract_time in ("full_time", "part_time"):
        params[settings.contract_time] = 1

    country = urllib.parse.quote(settings.country)
    return f"{API_BASE}/{country}/search/{page}?" + urllib.parse.urlencode(params)


def _fetch(url: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        hint = ""
        if exc.code in (401, 403):
            hint = " — App-ID/App-Key prüfen."
        elif exc.code == 429:
            hint = " — Kontingent der Adzuna-API erschöpft, später erneut versuchen."
        raise AdzunaError(f"Adzuna antwortet mit HTTP {exc.code}{hint} {body}") from exc
    except urllib.error.URLError as exc:
        raise AdzunaError(f"Keine Verbindung zu Adzuna: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise AdzunaError(f"Adzuna hat kein gültiges JSON geliefert: {exc}") from exc


def _to_job(raw: dict) -> Job:
    company = (raw.get("company") or {}).get("display_name", "") or "Unbekanntes Unternehmen"
    location = (raw.get("location") or {}).get("display_name", "")
    return Job(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")).replace("<strong>", "").replace("</strong>", "").strip(),
        company=str(company).strip(),
        description=str(raw.get("description", "")).strip(),
        location=str(location).strip(),
        url=str(raw.get("redirect_url", "")),
        created=str(raw.get("created", ""))[:10],
        contract_time=str(raw.get("contract_time", "")),
        source="adzuna",
    )


def search_jobs(settings: SearchSettings, page: int = 1) -> list[Job]:
    """Sucht über alle konfigurierten Suchbegriffe und entfernt Doppeltreffer."""
    app_id, app_key = credentials()
    jobs: dict[str, Job] = {}
    for query in settings.queries:
        data = _fetch(build_url(settings, query, page, app_id, app_key))
        for raw in data.get("results", []):
            job = _to_job(raw)
            if _excluded(job, settings):
                continue
            key = job.id or f"{job.company}|{job.title}"
            jobs.setdefault(key, job)
    return list(jobs.values())


def _excluded(job: Job, settings: SearchSettings) -> bool:
    if not job.title or not job.company:
        return True
    haystack = job.haystack()
    return any(word in haystack for word in settings.exclude)


def rank_jobs(jobs: list[Job], focus_rules, min_score: int = 0) -> list[tuple[Job, int]]:
    """Sortiert Treffer nach Anzahl passender Schwerpunkt-Stichwörter."""
    ranked = []
    for job in jobs:
        haystack = job.haystack()
        score = max((rule.score(haystack) for rule in focus_rules), default=0)
        if score >= min_score:
            ranked.append((job, score))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked
