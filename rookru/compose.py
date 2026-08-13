"""Texterzeugung über die Claude API.

Ein Aufruf je Stelle liefert alles, was sich zwischen zwei Bewerbungen ändert:
den Text des Motivationsschreibens und die Anpassung der beiden freigegebenen
Lebenslauf-Abschnitte.
"""

from __future__ import annotations

import json
from datetime import date

from .config import FocusRule, Settings
from .models import CVAdaptation, Focus, Job, LetterContent, SectionEdit

MODEL = "claude-opus-5"

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
- {paragraphs} Absätze, zusammen höchstens {max_words} Wörter. Der Brief muss \
auf eine Seite passen.
- Aufbau: (1) konkreter Bezug zu Stelle und Unternehmen, (2)–({last}) die \
Belege aus dem Faktenblatt, die zur Ausschreibung passen — der wichtigste \
zuerst, (letzter Absatz) Motivation für dieses Unternehmen.
- Tonfall: {tone}. Keine Superlative, keine Floskeln, kein "hiermit bewerbe ich \
mich", keine Aufzählung des Lebenslaufs.
- Fließtext ohne Zeilenumbrüche und ohne Aufzählungszeichen.
- Die Grußformel steht bereits in der Vorlage — schreibe sie nicht mit.

Lebenslauf:
- 'projekt_reihenfolge' enthält alle vorhandenen Projektkennungen, die \
relevanteste zuerst.
- 'projekt_bullets' ersetzt die Stichpunkte einzelner Projekte. Gib nur \
Projekte an, deren Formulierung du tatsächlich änderst; Länge und Detailgrad \
bleiben vergleichbar mit dem Original.
- 'kenntnis_zeilen' ersetzt die Zeilen unter BESONDERE KENNTNISSE UND \
FÄHIGKEITEN. Behalte Aufbau und Inhalt bei, sortiere nur nach Relevanz für die \
Stelle.
"""

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
            "description": "Text nach 'Bewerbung als' — Stellenbezeichnung, ggf. mit Referenz",
        },
        "anrede": {"type": "string", "description": "Anredezeile inklusive Komma"},
        "absaetze": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Absätze des Motivationsschreibens, Fließtext",
        },
        "projekt_reihenfolge": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Projektkennungen, relevanteste zuerst",
        },
        "projekt_bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "projekt": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["projekt", "bullets"],
                "additionalProperties": False,
            },
        },
        "kenntnis_zeilen": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "schwerpunkt",
        "schwerpunkt_begruendung",
        "betreff",
        "anrede",
        "absaetze",
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
    facts: str,
    projects: list[str],
    skills: list[str],
    style_example: str,
    hint: FocusRule | None,
) -> str:
    parts = [
        "# Faktenblatt des Bewerbers (bestehender Lebenslauf)",
        facts,
        "\n# Projektkennungen im Lebenslauf (genau diese Schreibweise verwenden)",
        "\n".join(f"- {p}" for p in projects) or "—",
        "\n# Aktuelle Zeilen unter BESONDERE KENNTNISSE UND FÄHIGKEITEN",
        "\n".join(f"- {s}" for s in skills) or "—",
        "\n# Stelle",
        job_briefing(job),
        "\n# Schwerpunkte",
        focus_briefing(settings.focus_rules, hint),
        "\n# Vorgaben für den Brief",
        f"Anrede (wörtlich übernehmen): {job.salutation_or_default()}",
        "Betreff beginnt in der Vorlage mit 'Bewerbung als ' — liefere nur die Fortsetzung.",
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


class ClaudeComposer:
    """Verfasst Brief und Lebenslauf-Anpassung mit Claude."""

    name = "claude"

    def __init__(self, model: str = MODEL, effort: str = "high") -> None:
        try:
            import anthropic  # noqa: PLC0415 — optionale Abhängigkeit
        except ImportError as exc:
            raise ComposerError(
                "Das Paket 'anthropic' fehlt. Installation: pip install anthropic"
            ) from exc
        self._anthropic = anthropic
        try:
            self._client = anthropic.Anthropic()
        except Exception as exc:  # fehlender Schlüssel u. Ä.
            raise ComposerError(f"Claude-Client nicht initialisierbar: {exc}") from exc
        self.model = model
        self.effort = effort

    def compose(
        self,
        settings: Settings,
        job: Job,
        facts: str,
        projects: list[str],
        skills: list[str],
        style_example: str = "",
    ) -> tuple[Focus, LetterContent, CVAdaptation]:
        hint = detect_focus(job, settings.focus_rules)
        system = SYSTEM_PROMPT.format(
            paragraphs=settings.letter.paragraphs,
            max_words=settings.letter.max_words,
            last=max(settings.letter.paragraphs - 1, 2),
            tone=settings.letter.tone,
        )
        user = build_prompt(settings, job, facts, projects, skills, style_example, hint)
        data = self._request(system, user)
        return self._to_models(settings, job, data, hint)

    def _request(self, system: str, user: str) -> dict:
        params = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        )

        try:
            # Claude Opus 5 kann eine Anfrage ablehnen; der serverseitige
            # Fallback beantwortet sie dann im selben Aufruf mit einem anderen
            # Modell, statt die Bewerbung ausfallen zu lassen.
            try:
                response = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    **params,
                )
            except self._anthropic.BadRequestError:
                response = self._client.messages.create(**params)
        except self._anthropic.APIStatusError as exc:
            raise ComposerError(f"Claude API: HTTP {exc.status_code} — {exc.message}") from exc
        except self._anthropic.APIConnectionError as exc:
            raise ComposerError(f"Keine Verbindung zur Claude API: {exc}") from exc

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", "") or ""
            raise ComposerError(f"Anfrage wurde abgelehnt. {detail}".strip())

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text.strip():
            raise ComposerError("Leere Antwort der Claude API.")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ComposerError(f"Antwort war kein gültiges JSON: {exc}") from exc

    def _to_models(
        self, settings: Settings, job: Job, data: dict, hint: FocusRule | None
    ) -> tuple[Focus, LetterContent, CVAdaptation]:
        key = str(data.get("schwerpunkt", "")).strip()
        rule = next((r for r in settings.focus_rules if r.key == key), hint)
        focus = Focus(
            key=rule.key if rule else "allgemein",
            label=rule.label if rule else "Allgemein",
            emphasise=list(rule.emphasise) if rule else [],
            reason=str(data.get("schwerpunkt_begruendung", "")).strip(),
        )

        paragraphs = [
            " ".join(str(p).split()) for p in data.get("absaetze", []) if str(p).strip()
        ]
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

        edits = [
            SectionEdit(
                anchor=str(item.get("projekt", "")).strip(),
                bullets=[str(b).strip() for b in item.get("bullets", []) if str(b).strip()],
            )
            for item in data.get("projekt_bullets", [])
            if str(item.get("projekt", "")).strip()
        ]
        adaptation = CVAdaptation(
            project_order=[str(p).strip() for p in data.get("projekt_reihenfolge", []) if str(p).strip()],
            project_edits=edits,
            skill_lines=[str(s).strip() for s in data.get("kenntnis_zeilen", []) if str(s).strip()],
            notes=focus.reason,
        )
        return focus, letter, adaptation


class StubComposer:
    """Ersatz ohne API-Zugriff — nur zum Testen der Dokumenterzeugung.

    Der Brieftext ist als Platzhalter erkennbar und niemals versandfertig.
    """

    name = "stub"

    def compose(
        self,
        settings: Settings,
        job: Job,
        facts: str,
        projects: list[str],
        skills: list[str],
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
        order = list(projects)
        if focus.emphasise:
            def rank(anchor: str) -> int:
                for i, needle in enumerate(focus.emphasise):
                    if needle.lower() in anchor.lower():
                        return i
                return len(focus.emphasise)

            order.sort(key=rank)
        return focus, letter, CVAdaptation(project_order=order, skill_lines=list(skills))


def build_composer(offline: bool = False):
    return StubComposer() if offline else ClaudeComposer()
