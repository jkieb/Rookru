"""KI-Vorauswahl: prüft die Suchtreffer gebündelt gegen das Profil.

Die Kombinationssuche findet dreistellige Trefferzahlen, aber sie zählt nur
zusammenfallende Wörter — eine Vollzeitstelle für Senior Engineers steht darum
neben der gesuchten Werkstudentenstelle. Hier liest ein Modell die Anzeigen und
sagt, welche sich wirklich lohnen.

Ein Aufruf je Anzeige wären hundert Aufrufe pro Suchlauf. Stattdessen geht ein
Stapel Anzeigen (siehe MAX_JOBS) in eine Anfrage und kommt als eine Antwort mit
einem Urteil je Nummer zurück; nur bei sehr vielen Treffern werden daraus
mehrere Stapel.
"""

from __future__ import annotations

import json
import os
from math import ceil
from typing import Callable, Optional

from .compose import message_text
from .config import AISettings, Settings
from .models import Job, Screening, TemplateData

# Ein Stapel je Anfrage. Bei 30 Anzeigen bleibt die Anfrage mit gekürzten
# Texten deutlich unter dem Kontextfenster, und die Antwort unter max_tokens.
MAX_JOBS = 30

# EURES liefert die vollständige Ausschreibung (bis 4.200 Zeichen). Für die
# Frage "passt das überhaupt?" reicht der Anfang — dort stehen Aufgaben und
# Anforderungen. Der ungekürzte Text geht später beim Schreiben des Briefs
# an das Modell.
DESCRIPTION_CHARS = 900

# Rückmeldung je erledigtem Stapel — speist den Fortschrittsbalken.
Melder = Optional[Callable[[int, int], None]]

SYSTEM_PROMPT = """\
Du prüfst Stellenanzeigen für einen einzelnen Bewerber im deutschsprachigen \
Raum. Du bekommst sein Faktenblatt (den bestehenden Lebenslauf), seinen \
Suchauftrag und eine nummerierte Liste gefundener Anzeigen. Für jede Anzeige \
entscheidest du, ob sich eine Bewerbung lohnt.

Maßstab:
- Art der Stelle: Sie muss zum Suchauftrag passen. Wird eine Werkstudenten- \
oder Praktikumsstelle gesucht, ist eine Vollzeitstelle unpassend — ebenso \
alles, was mehrere Jahre Berufserfahrung, einen abgeschlossenen Abschluss oder \
eine Führungsrolle verlangt.
- Ort: Er muss zum Suchauftrag passen; Anzeigen aus anderen Regionen oder \
Ländern sind unpassend, sofern die Stelle nicht ausdrücklich remote ist.
- Inhalt: Deckt das Faktenblatt die wichtigsten geforderten Kenntnisse ab? \
Einzelne fehlende Punkte sind normal und kein Ausschlussgrund — Praktika und \
Werkstudentenstellen bilden aus. Fehlt der Kern der Aufgabe, ist die Stelle \
unpassend.

Die Anzeigentexte sind je nach Börse nur Anrisse. Urteile nach dem, was \
dasteht; sortiere nicht aus, bloß weil eine Angabe fehlt.

Punkte von 0 bis 100: ab 80 passt die Stelle genau, 60 bis 79 lohnt sich, \
40 bis 59 ist ein Randfall, darunter unpassend. 'passend' ist deine Empfehlung, \
ob eine Bewerbung sinnvoll ist.

Die Begründung ist ein Satz, konkret auf diese Anzeige bezogen: was passt und \
was fehlt. Keine Floskeln, keine Wiederholung des Stellentitels.

Bewerte jede Anzeige genau einmal und gib ihre Nummer unverändert an. \
Antworte ausschließlich mit dem geforderten JSON-Objekt.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "bewertungen": {
            "type": "array",
            "description": "Ein Eintrag je vorgelegter Anzeige",
            "items": {
                "type": "object",
                "properties": {
                    "nr": {"type": "integer", "description": "Nummer der Anzeige aus der Liste"},
                    "passend": {"type": "boolean"},
                    "punkte": {"type": "integer"},
                    "begruendung": {"type": "string"},
                },
                "required": ["nr", "passend", "punkte", "begruendung"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["bewertungen"],
    "additionalProperties": False,
}


class ScreeningError(RuntimeError):
    """Die Vorauswahl konnte nicht erzeugt werden."""


def anfragen(anzahl: int) -> int:
    """Wie viele Anfragen die Vorauswahl für so viele Stellen stellt."""
    return ceil(anzahl / MAX_JOBS)


def batches(
    pairs: list[tuple[Job, int, int]], size: int = MAX_JOBS
) -> list[list[tuple[Job, int, int]]]:
    return [pairs[i : i + size] for i in range(0, len(pairs), size)]


def job_entry(nummer: int, job: Job) -> str:
    """Eine Anzeige, so knapp wie möglich und so vollständig wie nötig."""
    kopf = f"{nummer}. {job.title} — {job.company}"
    angaben = [
        f"Ort: {job.location or 'nicht genannt'}",
        f"Quelle: {job.source}",
    ]
    if job.contract_time:
        angaben.append(f"Anstellung: {job.contract_time}")
    if job.created:
        angaben.append(f"Datum: {job.created}")
    zeilen = [kopf, "   " + " · ".join(angaben)]
    text = " ".join(job.description.split())
    if text:
        if len(text) > DESCRIPTION_CHARS:
            text = text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + " […]"
        zeilen.append(f"   {text}")
    return "\n".join(zeilen)


def search_briefing(settings: Settings) -> str:
    """Wonach der Bewerber sucht — sonst fehlt der KI der Maßstab."""
    suche = settings.search
    zeilen = [f"Gesuchte Art von Stelle (Suchbegriffe): {', '.join(suche.queries)}"]
    ort = suche.where or suche.country.upper()
    umkreis = f" (Umkreis {suche.distance_km} km)" if suche.distance_km else ""
    zeilen.append(f"Gesuchter Ort: {ort}{umkreis}")
    if suche.exclude:
        zeilen.append(f"Ausgeschlossen: {', '.join(suche.exclude)}")
    schwerpunkte = [f"{r.label}" for r in settings.focus_rules]
    if schwerpunkte:
        zeilen.append(f"Schwerpunkte des Bewerbers: {'; '.join(schwerpunkte)}")
    return "\n".join(zeilen)


def build_prompt(
    settings: Settings, template: TemplateData, batch: list[tuple[Job, int, int]]
) -> str:
    return "\n".join(
        [
            "# Faktenblatt des Bewerbers (bestehender Lebenslauf)",
            template.facts,
            "\n# Suchauftrag",
            search_briefing(settings),
            f"\n# Gefundene Anzeigen ({len(batch)} Stück)",
            "\n\n".join(job_entry(i, job) for i, (job, _, _) in enumerate(batch, 1)),
            f"\nBewerte jetzt alle {len(batch)} Anzeigen.",
        ]
    )


def parse_response(
    data: dict, batch: list[tuple[Job, int, int]], min_score: int = 0
) -> list[Screening]:
    """Wandelt die JSON-Antwort in ein Urteil je Stelle des Stapels um.

    Getrennt vom API-Aufruf, damit die Auswertung ohne Netzwerk geprüft werden
    kann. Übergeht das Modell eine Anzeige, fällt sie nicht unter den Tisch: sie
    landet unbewertet unter den aussortierten und wird als solche gemeldet.
    """
    urteile: dict[int, dict] = {}
    for item in data.get("bewertungen") or []:
        if not isinstance(item, dict):
            continue
        try:
            nr = int(item.get("nr"))
        except (TypeError, ValueError):
            continue
        if 1 <= nr <= len(batch):
            urteile.setdefault(nr, item)

    ergebnis = []
    for nr, (job, focus_score, title_hits) in enumerate(batch, 1):
        item = urteile.get(nr)
        if item is None:
            ergebnis.append(
                Screening(
                    job=job,
                    fits=False,
                    reason="Von der KI übergangen — die Antwort enthielt kein Urteil.",
                    title_hits=title_hits,
                    focus_score=focus_score,
                    rated=False,
                )
            )
            continue
        try:
            punkte = max(0, min(100, int(item.get("punkte", 0))))
        except (TypeError, ValueError):
            punkte = 0
        ergebnis.append(
            Screening(
                job=job,
                fits=bool(item.get("passend")) and punkte >= min_score,
                score=punkte,
                reason=" ".join(str(item.get("begruendung", "")).split()),
                title_hits=title_hits,
                focus_score=focus_score,
            )
        )
    return ergebnis


class MistralScreener:
    """Bewertet die Suchtreffer stapelweise mit der Mistral-API."""

    name = "mistral"

    def __init__(self, ai: AISettings | None = None) -> None:
        try:
            from mistralai.client import Mistral  # noqa: PLC0415 — optionale Abhängigkeit
            from mistralai.client.errors.mistralerror import MistralError
            from mistralai.client.models import JSONSchema, ResponseFormat
        except ImportError as exc:
            raise ScreeningError(
                "Das Paket 'mistralai' fehlt. Installation: pip install mistralai"
            ) from exc

        api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
        if not api_key:
            raise ScreeningError(
                "MISTRAL_API_KEY ist nicht gesetzt. Trage den Schlüssel in .env ein "
                "(Vorlage: .env.example) oder schalte die Vorauswahl mit "
                "--ohne-vorauswahl ab."
            )

        self._error = MistralError
        self._client = Mistral(api_key=api_key)
        self._response_format = ResponseFormat(
            type="json_schema",
            json_schema=JSONSchema(
                name="vorauswahl",
                schema_definition=RESPONSE_SCHEMA,
                strict=True,
            ),
        )
        self.ai = ai or AISettings()

    @property
    def model(self) -> str:
        return self.ai.model_for_screening()

    def screen(
        self,
        settings: Settings,
        pairs: list[tuple[Job, int, int]],
        template: TemplateData,
        melden: Melder = None,
    ) -> list[Screening]:
        stapel = batches(pairs)
        ergebnis: list[Screening] = []
        for i, batch in enumerate(stapel, 1):
            data = self._request(SYSTEM_PROMPT, build_prompt(settings, template, batch))
            ergebnis.extend(parse_response(data, batch, settings.ai.screening_min))
            if melden:
                melden(i, len(stapel))
        ergebnis.sort(key=lambda urteil: urteil.sort_key(), reverse=True)
        return ergebnis

    def _request(self, system: str, user: str) -> dict:
        try:
            response = self._client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=self._response_format,
                # Die Vorauswahl soll urteilen, nicht formulieren — jeder Lauf
                # über dieselben Anzeigen soll möglichst dasselbe ergeben.
                temperature=0.0,
                max_tokens=self.ai.max_tokens,
            )
        except self._error as exc:
            raise ScreeningError(f"Mistral-API: {exc}") from exc

        choices = getattr(response, "choices", None)
        if not choices:
            raise ScreeningError("Mistral hat keine Antwort geliefert.")

        text = message_text(choices[0].message.content).strip()
        if not text:
            raise ScreeningError("Leere Antwort der Mistral-API.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScreeningError(f"Antwort war kein gültiges JSON: {exc}") from exc


class StubScreener:
    """Ersatz ohne API-Zugriff — behält die Reihenfolge der Suche bei.

    Sortiert nichts aus: Im Testmodus soll sichtbar bleiben, was die Suche
    gefunden hat, ohne dass ein Urteil vorgetäuscht wird.
    """

    name = "stub"
    model = "Testmodus (ohne KI)"

    def screen(
        self,
        settings: Settings,
        pairs: list[tuple[Job, int, int]],
        template: TemplateData,
        melden: Melder = None,
    ) -> list[Screening]:
        ergebnis = [
            Screening(
                job=job,
                fits=True,
                score=min(100, 40 + 20 * title_hits + 10 * focus_score),
                reason="Ohne KI übernommen (Testmodus) — nur nach Suchtreffern gereiht.",
                title_hits=title_hits,
                focus_score=focus_score,
                rated=False,
            )
            for job, focus_score, title_hits in pairs
        ]
        if melden:
            melden(1, 1)
        return ergebnis


def build_screener(offline: bool = False, ai: AISettings | None = None):
    return StubScreener() if offline else MistralScreener(ai)
