"""Texterzeugung über die Mistral-API.

Ein Aufruf je Stelle liefert alles, was sich zwischen zwei Bewerbungen ändert:
den Text des Motivationsschreibens und die Anpassung der freigegebenen
Lebenslauf-Abschnitte.
"""

from __future__ import annotations

import json
import os
from datetime import date

from .config import AISettings, FocusRule, Settings
from .models import CVAdaptation, Focus, Job, LetterContent, SectionEdit, TemplateData

SYSTEM_PROMPT = """\
Du schreibst Bewerbungsunterlagen für einen einzelnen Bewerber im \
deutschsprachigen Raum. Du bekommst sein vollständiges Faktenblatt (den \
bestehenden Lebenslauf) und eine Stellenausschreibung.

Absolute Regel — keine Erfindungen:
- Jede Aussage muss sich auf das Faktenblatt zurückführen lassen. Erfinde \
keine Arbeitgeber, Zeiträume, Zahlen, Tools, Zertifikate, Noten oder Projekte.
- Fordert die Stelle etwas, das im Faktenblatt fehlt, lässt du es weg. Schreibe \
niemals "Grundkenntnisse in X", wenn X nicht belegt ist.
- Beim Lebenslauf darfst du ausschließlich umformulieren, gewichten und \
umsortieren. Der Sachgehalt jedes Stichpunkts bleibt erhalten.

Motivationsschreiben:
- {paragraphs} Absätze, zusammen {min_words} bis {max_words} Wörter. Der Brief \
füllt genau eine Seite: Er soll sie ausschöpfen, aber nicht auf eine zweite \
rutschen. Bleib nicht unter der Untergrenze — ein halb leeres Blatt wirkt \
lustlos. Fehlt dir Stoff, geh bei den Belegen mehr ins Detail (was genau \
gemacht, womit, mit welchem Ergebnis), statt Floskeln einzufügen.
- Aufbau: (1) konkreter Bezug zu Stelle und Unternehmen, (2)–({last}) die \
Belege aus dem Faktenblatt, die zur Ausschreibung passen — der wichtigste \
zuerst, (letzter Absatz) Motivation für dieses Unternehmen.
- Tonfall: {tone}. Keine Superlative, keine Floskeln, kein "hiermit bewerbe ich \
mich", keine Aufzählung des Lebenslaufs.
- Fließtext ohne Zeilenumbrüche und ohne Aufzählungszeichen.
- Die Grußformel steht bereits in der Vorlage — schreibe sie nicht mit.

Lebenslauf — nur diese drei Felder, alles andere bleibt unangetastet:
- 'ausbildung_bullets' formuliert Stichpunkte einzelner Ausbildungseinträge um,
etwa um die Bachelorarbeit auf die Stelle auszurichten. Reihenfolge und Bestand \
der Einträge bleiben unverändert; Thema, Zeitraum, Institution und Abschluss \
dürfen sich nie ändern. Gib nur Einträge an, die du tatsächlich änderst.
- 'projekt_reihenfolge' enthält alle vorhandenen Projektkennungen, die \
relevanteste zuerst.
- 'projekt_bullets' ersetzt die Stichpunkte einzelner Projekte. Gib nur \
Projekte an, deren Formulierung du tatsächlich änderst; Länge und Detailgrad \
bleiben vergleichbar mit dem Original.
- 'kenntnis_zeilen' ersetzt die Zeilen unter BESONDERE KENNTNISSE UND \
FÄHIGKEITEN. Behalte Aufbau und Inhalt bei, sortiere nur nach Relevanz für die \
Stelle.

Antworte ausschließlich mit dem geforderten JSON-Objekt.
"""


def _bullet_edit_schema(key: str) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                key: {"type": "string"},
                "bullets": {"type": "array", "items": {"type": "string"}},
            },
            "required": [key, "bullets"],
            "additionalProperties": False,
        },
    }


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "schwerpunkt": {
            "type": "string",
            "description": "Schlüssel des passenden Schwerpunkts aus der Vorgabe",
        },
        "schwerpunkt_begruendung": {"type": "string"},
        "betreff": {
            "type": "string",
            "description": (
                "Text nach 'Bewerbung als' — die Stellenbezeichnung. Eine Referenz nur "
                "dann anhängen, wenn sie unter 'Stelle' ausdrücklich genannt ist."
            ),
        },
        "anrede": {"type": "string", "description": "Anredezeile inklusive Komma"},
        "absaetze": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Absätze des Motivationsschreibens, Fließtext",
        },
        "ausbildung_bullets": _bullet_edit_schema("eintrag"),
        "projekt_reihenfolge": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Projektkennungen, relevanteste zuerst",
        },
        "projekt_bullets": _bullet_edit_schema("projekt"),
        "kenntnis_zeilen": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "schwerpunkt",
        "schwerpunkt_begruendung",
        "betreff",
        "anrede",
        "absaetze",
        "ausbildung_bullets",
        "projekt_reihenfolge",
        "projekt_bullets",
        "kenntnis_zeilen",
    ],
    "additionalProperties": False,
}


class ComposerError(RuntimeError):
    """Der Bewerbungstext konnte nicht erzeugt werden."""


def detect_focus(job: Job, rules: list[FocusRule]) -> FocusRule | None:
    """Heuristische Vorauswahl des Schwerpunkts anhand der Stichwörter."""
    if not rules:
        return None
    haystack = job.haystack()
    best = max(rules, key=lambda rule: rule.score(haystack))
    return best if best.score(haystack) > 0 else None


def job_briefing(job: Job) -> str:
    lines = [f"Unternehmen: {job.company}", f"Position: {job.title}"]
    if job.location:
        lines.append(f"Ort: {job.location}")
    if job.contract_time:
        lines.append(f"Anstellung: {job.contract_time}")
    if job.reference:
        lines.append(f"Referenz: {job.reference}")
    if job.url:
        lines.append(f"Quelle: {job.url}")
    if job.description:
        lines.append(f"\nAusschreibungstext:\n{job.description.strip()}")
    return "\n".join(lines)


def focus_briefing(rules: list[FocusRule], hint: FocusRule | None) -> str:
    lines = ["Mögliche Schwerpunkte (Schlüssel: Bedeutung → was nach vorne gehört):"]
    for rule in rules:
        emphasise = ", ".join(rule.emphasise) or "—"
        lines.append(f"- {rule.key}: {rule.label} → hervorheben: {emphasise}")
    if hint:
        lines.append(
            f"\nStichwortabgleich schlägt '{hint.key}' vor. "
            "Prüfe das anhand der Ausschreibung und entscheide selbst."
        )
    return "\n".join(lines)


def build_prompt(
    settings: Settings,
    job: Job,
    template: TemplateData,
    style_example: str,
    hint: FocusRule | None,
) -> str:
    parts = [
        "# Faktenblatt des Bewerbers (bestehender Lebenslauf)",
        template.facts,
        "\n# Ausbildungseinträge (Kennung links vom | für 'eintrag' verwenden)",
        "\n".join(f"- {e}" for e in template.education) or "—",
        "\n# Projektkennungen im Lebenslauf (genau diese Schreibweise verwenden)",
        "\n".join(f"- {p}" for p in template.projects) or "—",
        "\n# Aktuelle Zeilen unter BESONDERE KENNTNISSE UND FÄHIGKEITEN",
        "\n".join(f"- {line}" for line in template.skills) or "—",
        "\n# Stelle",
        job_briefing(job),
        "\n# Schwerpunkte",
        focus_briefing(settings.focus_rules, hint),
        "\n# Vorgaben für den Brief",
        f"Anrede (wörtlich übernehmen): {job.salutation_or_default()}",
        "Betreff beginnt in der Vorlage mit 'Bewerbung als ' — liefere nur die Fortsetzung.",
        "Keine Referenz- oder Kennnummer erfinden: nur übernehmen, was oben unter "
        "'Stelle' steht. Ohne Angabe endet der Betreff mit der Stellenbezeichnung.",
    ]
    if style_example:
        parts += [
            "\n# Stilbeispiel eines früheren Briefs desselben Bewerbers",
            "Übernimm Tonfall, Satzbau und Absatzlänge. Übernimm keine Inhalte, "
            "die nicht zu dieser Stelle passen.",
            style_example,
        ]
    parts.append("\nErzeuge jetzt Brieftext und Lebenslauf-Anpassung.")
    return "\n".join(parts)


def _edits(items, key: str) -> list[SectionEdit]:
    return [
        SectionEdit(
            anchor=str(item.get(key, "")).strip(),
            bullets=[str(b).strip() for b in item.get("bullets", []) if str(b).strip()],
        )
        for item in items or []
        if isinstance(item, dict) and str(item.get(key, "")).strip()
    ]


def parse_response(
    settings: Settings, job: Job, data: dict, hint: FocusRule | None = None
) -> tuple[Focus, LetterContent, CVAdaptation]:
    """Wandelt die JSON-Antwort in die Datenmodelle um.

    Bewusst getrennt vom API-Aufruf, damit die Auswertung ohne Netzwerk
    geprüft werden kann.
    """
    key = str(data.get("schwerpunkt", "")).strip()
    rule = next((r for r in settings.focus_rules if r.key == key), hint)
    focus = Focus(
        key=rule.key if rule else "allgemein",
        label=rule.label if rule else "Allgemein",
        emphasise=list(rule.emphasise) if rule else [],
        reason=str(data.get("schwerpunkt_begruendung", "")).strip(),
    )

    paragraphs = [" ".join(str(p).split()) for p in data.get("absaetze", []) if str(p).strip()]
    if not paragraphs:
        raise ComposerError("Das Modell hat keinen Brieftext geliefert.")

    letter = LetterContent(
        subject=str(data.get("betreff", "")).strip() or job.title,
        salutation=str(data.get("anrede", "")).strip() or job.salutation_or_default(),
        paragraphs=paragraphs,
        company_name=job.company,
        company_department=job.department,
        company_street=job.street,
        company_postal_city=job.postal_city or job.location,
        letter_date=date.today(),
    )

    adaptation = CVAdaptation(
        project_order=[
            str(p).strip() for p in data.get("projekt_reihenfolge", []) if str(p).strip()
        ],
        project_edits=_edits(data.get("projekt_bullets"), "projekt"),
        education_edits=_edits(data.get("ausbildung_bullets"), "eintrag"),
        skill_lines=[str(s).strip() for s in data.get("kenntnis_zeilen", []) if str(s).strip()],
        notes=focus.reason,
    )
    return focus, letter, adaptation


def message_text(content) -> str:
    """Holt den Text aus der Antwort — Mistral liefert String oder Chunk-Liste."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            text = getattr(chunk, "text", None)
            if text is None and isinstance(chunk, dict):
                text = chunk.get("text")
            if text:
                parts.append(text)
        return "".join(parts)
    return ""


class MistralComposer:
    """Verfasst Brief und Lebenslauf-Anpassung mit der Mistral-API."""

    name = "mistral"

    def __init__(self, ai: AISettings | None = None) -> None:
        try:
            from mistralai.client import Mistral  # noqa: PLC0415 — optionale Abhängigkeit
            from mistralai.client.errors.mistralerror import MistralError
            from mistralai.client.models import JSONSchema, ResponseFormat
        except ImportError as exc:
            raise ComposerError(
                "Das Paket 'mistralai' fehlt. Installation: pip install mistralai"
            ) from exc

        api_key = os.environ.get("MISTRAL_API_KEY", "").strip()
        if not api_key:
            raise ComposerError(
                "MISTRAL_API_KEY ist nicht gesetzt. Trage den Schlüssel in .env ein "
                "(Vorlage: .env.example) oder nutze --offline."
            )

        self._error = MistralError
        self._client = Mistral(api_key=api_key)
        self._response_format = ResponseFormat(
            type="json_schema",
            json_schema=JSONSchema(
                name="bewerbung",
                schema_definition=RESPONSE_SCHEMA,
                strict=True,
            ),
        )
        self.ai = ai or AISettings()

    def compose(
        self,
        settings: Settings,
        job: Job,
        template: TemplateData,
        style_example: str = "",
    ) -> tuple[Focus, LetterContent, CVAdaptation]:
        hint = detect_focus(job, settings.focus_rules)
        min_words, max_words = settings.letter.target_words()
        system = SYSTEM_PROMPT.format(
            paragraphs=settings.letter.paragraphs,
            min_words=min_words,
            max_words=max_words,
            last=max(settings.letter.paragraphs - 1, 2),
            tone=settings.letter.tone,
        )
        user = build_prompt(settings, job, template, style_example, hint)
        data = self._request(system, user)
        return parse_response(settings, job, data, hint)

    def _request(self, system: str, user: str) -> dict:
        try:
            response = self._client.chat.complete(
                model=self.ai.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=self._response_format,
                temperature=self.ai.temperature,
                max_tokens=self.ai.max_tokens,
            )
        except self._error as exc:
            raise ComposerError(f"Mistral-API: {exc}") from exc
        except Exception as exc:
            # Netzwerkfehler (z. B. httpx.ProxyError bei gesperrtem Proxy) sauber abfangen
            raise ComposerError(f"Mistral-API Netzwerkfehler: {type(exc).__name__}: {exc}") from exc

        choices = getattr(response, "choices", None)
        if not choices:
            raise ComposerError("Mistral hat keine Antwort geliefert.")

        text = message_text(choices[0].message.content).strip()
        if not text:
            raise ComposerError("Leere Antwort der Mistral-API.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ComposerError(f"Antwort war kein gültiges JSON: {exc}") from exc


class StubComposer:
    """Ersatz ohne API-Zugriff — nur zum Testen der Dokumenterzeugung.

    Der Brieftext ist als Platzhalter erkennbar und niemals versandfertig.
    """

    name = "stub"

    def compose(
        self,
        settings: Settings,
        job: Job,
        template: TemplateData,
        style_example: str = "",
    ) -> tuple[Focus, LetterContent, CVAdaptation]:
        hint = detect_focus(job, settings.focus_rules)
        focus = Focus(
            key=hint.key if hint else "allgemein",
            label=hint.label if hint else "Allgemein",
            emphasise=list(hint.emphasise) if hint else [],
            reason="Stichwortabgleich ohne KI (Testmodus).",
        )
        paragraphs = [
            f"[TESTMODUS — kein KI-Text] Absatz {i + 1} zur Bewerbung als {job.title} "
            f"bei {job.company}. Dieser Text dient nur der Layoutprüfung und darf so "
            "nicht verschickt werden."
            for i in range(settings.letter.paragraphs)
        ]
        letter = LetterContent(
            subject=job.title,
            salutation=job.salutation_or_default(),
            paragraphs=paragraphs,
            company_name=job.company,
            company_department=job.department,
            company_street=job.street,
            company_postal_city=job.postal_city or job.location,
        )
        order = list(template.projects)
        if focus.emphasise:

            def rank(anchor: str) -> int:
                for i, needle in enumerate(focus.emphasise):
                    if needle.lower() in anchor.lower():
                        return i
                return len(focus.emphasise)

            order.sort(key=rank)
        return focus, letter, CVAdaptation(
            project_order=order, skill_lines=list(template.skills)
        )


def build_composer(offline: bool = False, ai: AISettings | None = None):
    return StubComposer() if offline else MistralComposer(ai)
