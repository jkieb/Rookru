"""Stellensuche über die Careerjet-Such-API.

Zweite Quelle neben Adzuna: Careerjet bündelt österreichische Jobbörsen, die
Adzuna nicht abdeckt. Zugang über CAREERJET_API_KEY (siehe .env.example),
kostenlose Registrierung: careerjet.com/partners/api/
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from typing import Any

from ..config import SearchSettings
from ..models import Job
from .common import USER_AGENT, Melder, clean_text, excluded, zu_alt

API_URL = "https://search.api.careerjet.net/v4/query"
# Careerjet weist Anfragen ohne Referer ab (HTTP 403, "Undeclared referrer").
REFERER = "https://github.com/jkieb/Rookru"
RETRY_CODES = (429, 502, 503, 504)

# Ländercode aus profil.yaml → Careerjet-Locale.
LOCALES = {"at": "de_AT", "de": "de_DE", "ch": "de_CH"}
DEFAULT_LOCALE = "en_GB"


class CareerjetError(RuntimeError):
    """Die Careerjet-API war nicht erreichbar oder hat einen Fehler gemeldet."""


def api_key() -> str:
    key = os.environ.get("CAREERJET_API_KEY", "").strip()
    if not key:
        raise CareerjetError(
            "CAREERJET_API_KEY ist nicht gesetzt. Trage ihn in .env ein "
            "(Vorlage: .env.example) oder nimm 'careerjet' aus suche.quellen heraus."
        )
    return key


def locale_for(settings: SearchSettings) -> str:
    return settings.locale or LOCALES.get(settings.country, DEFAULT_LOCALE)


def build_url(settings: SearchSettings, query: str, page: int) -> str:
    params: dict[str, Any] = {
        "keywords": query,
        "locale_code": locale_for(settings),
        "page": max(1, min(page, 10)),
        "page_size": max(1, min(settings.results, 100)),
        "sort": "date",
        # Beide Felder verlangt die API; hier läuft kein Endnutzer-Browser.
        "user_ip": "127.0.0.1",
        "user_agent": USER_AGENT,
    }
    if settings.where:
        params["location"] = settings.where
        if settings.distance_km:
            params["radius"] = settings.distance_km
    if settings.contract_time == "full_time":
        params["work_hours"] = "f"
    elif settings.contract_time == "part_time":
        params["work_hours"] = "p"
    return f"{API_URL}?" + urllib.parse.urlencode(params)


def _fetch(url: str, key: str, timeout: int = 30, versuche: int = 3) -> dict:
    token = base64.b64encode(f"{key}:".encode()).decode()
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {token}",
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        },
    )
    for versuch in range(1, versuche + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_CODES and versuch < versuche:
                time.sleep(versuch)
                continue
            body = exc.read().decode("utf-8", "replace")[:300]
            hint = " — API-Key prüfen." if exc.code in (401, 403) else ""
            raise CareerjetError(
                f"Careerjet antwortet mit HTTP {exc.code}{hint} {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise CareerjetError(f"Keine Verbindung zu Careerjet: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise CareerjetError(f"Careerjet hat kein gültiges JSON geliefert: {exc}") from exc

        if data.get("type") == "ERROR":
            raise CareerjetError(f"Careerjet meldet: {data.get('error', 'unbekannter Fehler')}")
        return data
    raise CareerjetError("Careerjet nicht erreichbar")  # pragma: no cover


def _date(raw: str) -> str:
    """'Wed, 05 Aug 2026 07:25:37 GMT' → '2026-08-05'."""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _to_job(raw: dict) -> Job:
    url = str(raw.get("url", ""))
    return Job(
        # Careerjet vergibt keine ID; die Weiterleitungs-URL ist je Anzeige eindeutig.
        id=url[-32:],
        title=clean_text(raw.get("title", "")),
        company=clean_text(raw.get("company", "")),
        description=clean_text(raw.get("description", "")),
        location=clean_text(raw.get("locations", "")),
        url=url,
        created=_date(str(raw.get("date", ""))),
        source="careerjet",
    )


def search_jobs(
    settings: SearchSettings, page: int = 1, melden: Melder = None
) -> list[Job]:
    """Sucht über alle konfigurierten Suchbegriffe und entfernt Doppeltreffer."""
    key = api_key()
    jobs: dict[str, Job] = {}
    for query in settings.queries:
        data = _fetch(build_url(settings, query, page), key)
        for raw in data.get("jobs", []):
            job = _to_job(raw)
            if excluded(job, settings) or zu_alt(job, settings.max_days_old):
                continue
            jobs.setdefault(job.id or f"{job.company}|{job.title}", job)
        if melden:
            melden(query)
    return list(jobs.values())
