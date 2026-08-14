"""Stellensuche über EURES, das Jobportal der Europäischen Kommission.

Der Grund für diese Quelle ist nicht die Menge, sondern der Text: Adzuna,
Careerjet und Jooble liefern nur Anrisse von 270 bis 500 Zeichen, EURES die
vollständige Ausschreibung (im Test 2.700 bis 4.200 Zeichen). Das Modell kann
damit auf konkrete Anforderungen eingehen, statt aus Bruchstücken zu raten.

Der Endpunkt ist öffentlich und braucht keinen Schlüssel. Er ist allerdings
nicht förmlich dokumentiert; die Feldnamen stammen aus einer
community-gepflegten Spezifikation und aus eigenen Abfragen.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..config import SearchSettings
from ..models import Job
from .common import UNBEKANNT, USER_AGENT, Melder, clean_text, excluded, zu_alt

API_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
RETRY_CODES = (429, 500, 502, 503, 504)
MAX_PRO_SEITE = 50  # Obergrenze der API

# EURES filtert über NUTS-Regionen, nicht über Orte mit Umkreis. 'umkreis_km'
# bleibt hier deshalb wirkungslos; ohne Zuordnung wird landesweit gesucht.
NUTS = {
    "wien": "AT13",
    "eisenstadt": "AT11",
    "st. pölten": "AT12",
    "sankt pölten": "AT12",
    "klagenfurt": "AT21",
    "graz": "AT22",
    "linz": "AT31",
    "salzburg": "AT32",
    "innsbruck": "AT33",
    "bregenz": "AT34",
    "berlin": "DE3",
    "hamburg": "DE6",
    "münchen": "DE21",
    "zürich": "CH04",
}

# max_tage aus profil.yaml → grober Vorfilter der API. Genau nachgefiltert
# wird anschließend über das Anzeigendatum.
ZEITRAEUME = ((1, "LAST_DAY"), (3, "LAST_THREE_DAYS"), (7, "LAST_WEEK"), (31, "LAST_MONTH"))

# Kommt statt eines Firmennamens im Feld, wenn der Arbeitgeber nicht gepflegt ist.
PLATZHALTER = ("siehe beschreibung", "see description", "n/a", "-", "keine angabe")


class EuresError(RuntimeError):
    """EURES war nicht erreichbar oder hat einen Fehler gemeldet."""


def location_codes(settings: SearchSettings) -> list[str]:
    """Ortsangabe auf einen NUTS-Code abbilden, sonst das ganze Land."""
    code = NUTS.get(settings.where.strip().lower())
    return [code] if code else [settings.country.lower()]


def publication_period(max_days_old: int) -> str | None:
    if not max_days_old:
        return None
    for grenze, code in ZEITRAEUME:
        if max_days_old <= grenze:
            return code
    return None


def build_body(settings: SearchSettings, query: str, page: int) -> dict[str, Any]:
    """Baut die Abfrage — ein Stichwort-Eintrag je Wort.

    Ein Eintrag mit mehreren Wörtern verknüpft EURES mit ODER: 'Werkstudent
    Maschinenbau' ergab in Wien 168 Treffer, nämlich die Summe beider
    Einzelsuchen. Ein Eintrag je Wort verknüpft dagegen mit UND — dasselbe
    Verhalten wie bei den übrigen Quellen.
    """
    woerter = query.split()
    body: dict[str, Any] = {
        # Das erste Wort ist die Rolle ('Werkstudent', 'Praktikum') und muss im
        # Titel stehen. Sonst matchen kurze Themen wie 'CAD' oder 'VBA' quer
        # durch den Bestand: 'Praktikum CAD' lieferte so 58 Treffer, darunter
        # Zahnärztliche Assistenz und Reinigungstechnik. Mit Titelbindung
        # bleibt genau ein passender übrig.
        "keywords": [{"keyword": woerter[0], "specificSearchCode": "TITLE"}]
        + [{"keyword": wort, "specificSearchCode": "EVERYWHERE"} for wort in woerter[1:]],
        "locationCodes": location_codes(settings),
        "resultsPerPage": max(1, min(settings.results, MAX_PRO_SEITE)),
        "page": max(1, page),
        "sortSearch": "MOST_RECENT",
    }
    zeitraum = publication_period(settings.max_days_old)
    if zeitraum:
        body["publicationPeriod"] = zeitraum
    if settings.contract_time == "full_time":
        body["positionScheduleCodes"] = ["fulltime"]
    elif settings.contract_time == "part_time":
        body["positionScheduleCodes"] = ["parttime"]
    return body


def _fetch(body: dict, timeout: int = 60, versuche: int = 3) -> dict:
    # Volltext-Antworten sind groß (im Test bis 45 KB je Abfrage) und
    # gelegentlich langsam — daher mehr Zeit als bei den Anriss-Quellen.
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    for versuch in range(1, versuche + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_CODES and versuch < versuche:
                time.sleep(versuch)
                continue
            rumpf = exc.read().decode("utf-8", "replace")[:200]
            raise EuresError(f"EURES antwortet mit HTTP {exc.code}: {rumpf}") from exc
        except TimeoutError as exc:
            # urlopen wirft die Zeitüberschreitung direkt, nicht als URLError —
            # ohne eigenen Zweig gäbe es dafür keinen zweiten Versuch.
            if versuch < versuche:
                time.sleep(versuch)
                continue
            raise EuresError(f"EURES antwortet nicht innerhalb von {timeout} s") from exc
        except urllib.error.URLError as exc:
            raise EuresError(f"Keine Verbindung zu EURES: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise EuresError(f"EURES hat kein gültiges JSON geliefert: {exc}") from exc

        if "jvs" not in data:
            raise EuresError(f"EURES meldet: {data.get('message', 'unerwartete Antwort')}")
        return data
    raise EuresError("EURES nicht erreichbar")  # pragma: no cover


def _date(millis: object) -> str:
    """Zeitstempel in Millisekunden → '2026-08-14'."""
    try:
        return datetime.fromtimestamp(int(millis) / 1000, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _company(raw: dict) -> str:
    name = clean_text((raw.get("employer") or {}).get("name"))
    if not name or name.lower() in PLATZHALTER:
        # Sichtbar lassen statt die Stelle wegzuwerfen — beim Gegenlesen fällt
        # es auf, und der Adressblock wird ohnehin als unvollständig gemeldet.
        return UNBEKANNT
    return name


def _location(raw: dict) -> str:
    orte = raw.get("locationMap") or {}
    return ", ".join(f"{land} {'/'.join(codes)}" for land, codes in sorted(orte.items()))


def _to_job(raw: dict) -> Job:
    kennung = str(raw.get("id", ""))
    return Job(
        id=kennung,
        title=clean_text(raw.get("title")),
        company=_company(raw),
        # Der eigentliche Gewinn dieser Quelle: die vollständige Ausschreibung.
        description=clean_text(raw.get("description")),
        location=_location(raw),
        url=f"https://europa.eu/eures/portal/jv-se/jv-details/{kennung}",
        created=_date(raw.get("creationDate")),
        contract_time=" ".join(raw.get("positionScheduleCodes") or []),
        source="eures",
    )


def search_jobs(
    settings: SearchSettings, page: int = 1, melden: Melder = None
) -> list[Job]:
    """Sucht über alle konfigurierten Suchbegriffe und entfernt Doppeltreffer."""
    jobs: dict[str, Job] = {}
    for query in settings.queries:
        data = _fetch(build_body(settings, query, page))
        for raw in data.get("jvs", []):
            job = _to_job(raw)
            if excluded(job, settings) or zu_alt(job, settings.max_days_old):
                continue
            jobs.setdefault(job.id or f"{job.company}|{job.title}", job)
        if melden:
            melden(query)
    return list(jobs.values())
