"""Stellensuche über die Jooble-API.

Jooble ist ein Aggregator und indiziert die großen österreichischen Börsen —
darunter karriere.at, das selbst keine Schnittstelle anbietet. Zugang über
JOOBLE_API_KEY (siehe .env.example); den Schlüssel gibt es kostenlos auf
Anfrage: https://jooble.org/api/about
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import SearchSettings
from ..models import Job
from .common import USER_AGENT, Melder, clean_text, excluded, zu_alt

DEFAULT_HOST = "jooble.org"
RETRY_CODES = (429, 500, 502, 503, 504)

# Jooble akzeptiert nur diese Umkreise (km); alles andere wird abgewiesen.
RADIUS_STUFEN = (0, 4, 8, 16, 26, 40, 80)


class JoobleError(RuntimeError):
    """Die Jooble-API war nicht erreichbar oder hat einen Fehler gemeldet."""


def api_key() -> str:
    key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not key:
        raise JoobleError(
            "JOOBLE_API_KEY ist nicht gesetzt. Schlüssel kostenlos anfordern unter "
            "https://jooble.org/api/about, in .env eintragen (Vorlage: .env.example) "
            "oder 'jooble' aus suche.quellen herausnehmen."
        )
    return key


def radius_stufe(distance_km: int) -> int:
    """Nächstgelegene erlaubte Umkreisstufe — 25 km werden zu 26."""
    if not distance_km:
        return 0
    return min(RADIUS_STUFEN, key=lambda stufe: abs(stufe - distance_km))


def build_body(settings: SearchSettings, query: str, page: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "keywords": query,
        "page": max(1, page),
        "ResultOnPage": max(1, min(settings.results, 100)),
    }
    if settings.where:
        body["location"] = settings.where
        if settings.distance_km:
            body["radius"] = str(radius_stufe(settings.distance_km))
    return body


def _fetch(body: dict, key: str, host: str, timeout: int = 30, versuche: int = 3) -> dict:
    daten = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"https://{host}/api/{urllib.parse.quote(key)}",
        data=daten,  # Jooble verlangt POST; GET beantwortet die API mit einem Fehler.
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    for versuch in range(1, versuche + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_CODES and versuch < versuche:
                time.sleep(versuch)
                continue
            if exc.code in (401, 403):
                # Genau hier verliert man sonst eine Stunde: Der Schlüssel gilt
                # nur für die Länderseite, auf der er beantragt wurde.
                raise JoobleError(
                    f"Jooble ({host}) weist den Schlüssel ab (HTTP {exc.code}). "
                    "Jooble-Schlüssel gelten nur für die Länderseite, auf der sie "
                    "beantragt wurden — steht der Schlüssel etwa auf de.jooble.org, "
                    "muss 'suche.jooble_host: de.jooble.org' in profil.yaml stehen."
                ) from exc
            rumpf = exc.read().decode("utf-8", "replace")[:200]
            raise JoobleError(f"Jooble antwortet mit HTTP {exc.code}: {rumpf}") from exc
        except urllib.error.URLError as exc:
            raise JoobleError(f"Keine Verbindung zu Jooble: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise JoobleError(f"Jooble hat kein gültiges JSON geliefert: {exc}") from exc
    raise JoobleError("Jooble nicht erreichbar")  # pragma: no cover


def _date(raw: str) -> str:
    """'2026-08-14T12:55:35.3870000' → '2026-08-14'.

    Die Bruchsekunden haben sieben Stellen und sind damit kein gültiges
    ISO-Format — der Datumsteil reicht ohnehin.
    """
    datum = str(raw or "")[:10]
    return datum if len(datum) == 10 and datum[4] == "-" and datum[7] == "-" else ""


def _to_job(raw: dict) -> Job:
    return Job(
        id=str(raw.get("id", "")),
        title=clean_text(raw.get("title")),
        company=clean_text(raw.get("company")),
        # 'snippet' ist nur ein Anriss — Jooble liefert keinen Volltext.
        description=clean_text(raw.get("snippet")),
        location=clean_text(raw.get("location")),
        url=str(raw.get("link", "")),
        created=_date(str(raw.get("updated", ""))),
        source="jooble",
    )


def search_jobs(
    settings: SearchSettings, page: int = 1, melden: Melder = None
) -> list[Job]:
    """Sucht über alle konfigurierten Suchbegriffe und entfernt Doppeltreffer."""
    key = api_key()
    host = settings.jooble_host or DEFAULT_HOST
    jobs: dict[str, Job] = {}
    for query in settings.queries:
        data = _fetch(build_body(settings, query, page), key, host)
        for raw in data.get("jobs", []):
            job = _to_job(raw)
            if excluded(job, settings) or zu_alt(job, settings.max_days_old):
                continue
            jobs.setdefault(job.id or f"{job.company}|{job.title}", job)
        if melden:
            melden(query)
    return list(jobs.values())
