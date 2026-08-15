"""Kommandozeile: rookru pruefen | suchen | bewerben"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

from tqdm import tqdm

from .compose import ComposerError, build_composer, detect_focus
from .config import ConfigError, Settings, load_settings
from .models import Job, Screening, TemplateData
from .pipeline import build_application, load_style_example, read_template, save_search_run
from .render.bundle import BundleError
from .render.convert import ConversionError, find_soffice
from .screening import ScreeningError, build_screener
from .screening import anfragen as vorauswahl_anfragen
from .sources import (
    QUELLEN,
    AdzunaError,
    CareerjetError,
    EuresError,
    JoobleError,
    SourceError,
    anfragen,
    load_jobs_file,
    rank_jobs,
    search_all,
)

DEFAULT_PROFILE = "profil.yaml"
BESCHRIFTUNG = 34  # Zeichen für "quelle: suchbegriff" im Fortschrittsbalken


def suchen_mit_balken(settings: Settings) -> tuple[list[Job], list[str]]:
    """Sucht über alle Quellen und zeigt dabei einen Fortschrittsbalken.

    Die Kombinationssuche stellt je Suchbegriff und Quelle eine Anfrage — das
    dauert über eine Minute und sähe sonst aus, als hänge das Programm. Der
    Balken läuft auf stderr, damit `rookru suchen > treffer.txt` sauber bleibt.
    """
    with tqdm(
        total=anfragen(settings.search),
        desc=f"{'Suche läuft':<{BESCHRIFTUNG}.{BESCHRIFTUNG}}",
        leave=False,
        file=sys.stderr,
        disable=not sys.stderr.isatty(),
        bar_format="  {desc} {bar} {n_fmt}/{total_fmt}",
    ) as balken:

        def melden(quelle: str, query: str) -> None:
            # Feste Breite, sonst springt der Balken bei jedem Suchbegriff.
            balken.set_description_str(
                f"{quelle}: {query}"[:BESCHRIFTUNG].ljust(BESCHRIFTUNG), refresh=False
            )
            balken.update(1)

        return search_all(settings.search, melden=melden)


def vorauswahl_mit_balken(
    settings: Settings,
    pairs: list[tuple[Job, int, int]],
    template: TemplateData,
    offline: bool = False,
) -> tuple[list[Screening] | None, str]:
    """Lässt die KI über die Treffer schauen; zeigt dabei einen Balken.

    Scheitert die Vorauswahl, ist das kein Grund, den ganzen Suchlauf
    wegzuwerfen: Es bleibt dann bei der Reihung der Suche, und der Grund steht
    als Warnung darüber.
    """
    try:
        screener = build_screener(offline=offline, ai=settings.ai)
    except ScreeningError as exc:
        print(f"⚠ KI-Vorauswahl übersprungen — {exc}\n")
        return None, ""

    with tqdm(
        total=vorauswahl_anfragen(len(pairs)),
        desc=f"{'KI-Vorauswahl läuft':<{BESCHRIFTUNG}.{BESCHRIFTUNG}}",
        leave=False,
        file=sys.stderr,
        disable=not sys.stderr.isatty(),
        bar_format="  {desc} {bar} {n_fmt}/{total_fmt}",
    ) as balken:

        def melden(nummer: int, gesamt: int) -> None:
            balken.set_description_str(
                f"KI prüft Stapel {nummer}/{gesamt}".ljust(BESCHRIFTUNG), refresh=False
            )
            balken.update(1)

        try:
            return screener.screen(settings, pairs, template, melden=melden), screener.model
        except ScreeningError as exc:
            print(f"⚠ KI-Vorauswahl fehlgeschlagen, es bleibt bei der Reihung der Suche: {exc}\n")
            return None, ""


def suchlauf(
    args: argparse.Namespace,
    settings: Settings,
    template: TemplateData | None = None,
    offline: bool = False,
) -> tuple[list[tuple[Job, int, int]], list[Screening] | None, Path | None]:
    """Suchen, reihen, von der KI prüfen lassen und beide Ergebnisse ablegen."""
    jobs, probleme = suchen_mit_balken(settings)
    for problem in probleme:
        print(f"⚠ {problem}\n")
    pairs = rank_jobs(
        jobs, settings.focus_rules, settings.search.min_score, settings.search.queries
    )
    if not pairs:
        return [], None, None

    urteile, modell = None, ""
    if settings.ai.screening and not args.ohne_vorauswahl:
        if template is None:
            try:
                template = read_template(settings.templates.cv)
            except Exception as exc:  # ohne Faktenblatt fehlt der Maßstab
                print(f"⚠ KI-Vorauswahl übersprungen — Lebenslauf-Vorlage nicht lesbar: {exc}\n")
        if template is not None:
            urteile, modell = vorauswahl_mit_balken(settings, pairs, template, offline)

    ordner = save_search_run(settings, pairs, urteile, probleme, model=modell)
    return pairs, urteile, ordner


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimaler .env-Leser — vorhandene Umgebungsvariablen haben Vorrang."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def cmd_pruefen(args: argparse.Namespace) -> int:
    """Konfiguration, Vorlagen, Anlagen und Werkzeuge prüfen."""
    ok = True
    try:
        settings = load_settings(args.profil)
    except ConfigError as exc:
        print(f"✗ Konfiguration: {exc}")
        return 1
    print(f"✓ Konfiguration: {args.profil}")
    print(f"  Bewerber: {settings.applicant.name}")

    missing = settings.missing_files()
    if missing:
        ok = False
        print("✗ Fehlende Dateien:")
        for entry in missing:
            print(f"    {entry}")
    else:
        print(f"✓ Vorlagen und {len(settings.attachments)} Anlagen vorhanden")

    try:
        data = read_template(settings.templates.cv)
        print(f"✓ Lebenslauf-Vorlage gelesen: {len(data.education)} Ausbildungseinträge, "
              f"{len(data.projects)} Projekte, {len(data.skills)} Kenntnis-Zeilen")
        print(f"  Anpassbar: {', '.join(data.projects) or '—'}")
        for eintrag in data.education:
            print(f"             {eintrag}")
    except Exception as exc:  # defekte oder fremd strukturierte Vorlage
        ok = False
        print(f"✗ Lebenslauf-Vorlage nicht lesbar: {exc}")

    print("✓ Stilbeispiel gefunden" if load_style_example(settings)
          else "· Kein Stilbeispiel (optional): privat/vorlagen/stilbeispiel.txt")

    try:
        print(f"✓ LibreOffice: {find_soffice()}")
    except ConversionError as exc:
        ok = False
        print(f"✗ {exc}")

    if os.environ.get("MISTRAL_API_KEY"):
        print(f"✓ Mistral-Zugang gesetzt (Modell: {settings.ai.model})")
    else:
        ok = False
        print("✗ MISTRAL_API_KEY fehlt (für --offline nicht nötig)")

    if settings.ai.screening:
        print(f"✓ KI-Vorauswahl aktiv (Modell: {settings.ai.model_for_screening()}, "
              f"ab {settings.ai.screening_min} Punkten passend)")
        print(f"  Suchläufe werden abgelegt unter: {settings.runs_dir}")
    else:
        print("· KI-Vorauswahl abgeschaltet (ki.vorauswahl: false)")

    # Geprüft wird nur, was in suche.quellen auch benutzt wird.
    schluessel = {
        "adzuna": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
        "careerjet": ("CAREERJET_API_KEY",),
        "jooble": ("JOOBLE_API_KEY",),
        "eures": (),  # öffentlich, kein Schlüssel nötig
    }
    for quelle in settings.search.sources:
        if quelle not in QUELLEN:
            ok = False
            print(f"✗ Unbekannte Quelle '{quelle}' — bekannt: {', '.join(QUELLEN)}")
            continue
        fehlend = [name for name in schluessel[quelle] if not os.environ.get(name)]
        if fehlend:
            ok = False
            print(f"✗ {quelle}: {' / '.join(fehlend)} fehlt")
        else:
            print(f"✓ {quelle}-Zugang gesetzt")

    print("\nAlles bereit." if ok else "\nEs fehlt noch etwas (siehe ✗ oben).")
    return 0 if ok else 1


def _kennzahlen(job: Job, settings: Settings, hits: int, score: int) -> str:
    focus = detect_focus(job, settings.focus_rules)
    return (f"    {job.company} · {job.location or 'Ort unbekannt'} · "
            f"{job.created or 'ohne Datum'} · {job.source} · "
            f"Titel {hits} · Schwerpunkt {score} {f'[{focus.key}]' if focus else '[—]'}")


def _print_jobs(pairs: list[tuple[Job, int, int]], settings: Settings) -> None:
    for i, (job, score, hits) in enumerate(pairs, 1):
        print(f"{i:2d}. {job.title}")
        print(_kennzahlen(job, settings, hits, score))
        if job.url:
            print(f"    {job.url}")


def _print_screenings(urteile: list[Screening], settings: Settings) -> None:
    for i, urteil in enumerate(urteile, 1):
        job = urteil.job
        print(f"{i:2d}. [{urteil.score:3d}] {job.title}")
        print(_kennzahlen(job, settings, urteil.title_hits, urteil.focus_score))
        if urteil.reason:
            print(textwrap.fill(
                urteil.reason, width=96, initial_indent="    KI: ", subsequent_indent="        "
            ))
        if job.url:
            print(f"    {job.url}")


def _print_vorauswahl_bilanz(urteile: list[Screening], gesamt: int, modell: str) -> None:
    passend = sum(1 for u in urteile if u.fits)
    ohne_urteil = sum(1 for u in urteile if not u.rated)
    print(f"\nKI-Vorauswahl ({modell}): {passend} von {gesamt} Treffern passen zum Profil, "
          f"{gesamt - passend} aussortiert — Begründungen in vorauswahl.json.")
    if ohne_urteil:
        print(f"⚠ {ohne_urteil} Stelle(n) ohne Urteil — sie stehen bei den aussortierten.")


def cmd_suchen(args: argparse.Namespace) -> int:
    settings = load_settings(args.profil)
    if args.query:
        settings.search.queries = [args.query]
    if args.ort:
        settings.search.where = args.ort
    if args.treffer:
        settings.search.results = args.treffer

    begriffe = " | ".join(settings.search.queries)
    print(f"Suche: '{begriffe}' in {settings.search.country.upper()}"
          f"{' / ' + settings.search.where if settings.search.where else ''}"
          f" über {', '.join(settings.search.sources)}\n")
    pairs, urteile, ordner = suchlauf(args, settings)
    if not pairs:
        print("Keine Treffer. Suchbegriff weiter fassen oder 'ausschliessen' in profil.yaml prüfen.")
        return 1

    if urteile is None:
        _print_jobs(pairs, settings)
        print(f"\n{len(pairs)} Treffer.")
    else:
        passend = [u for u in urteile if u.fits]
        if passend:
            _print_screenings(passend, settings)
        else:
            print("Die KI hält keinen der Treffer für passend — "
                  "aussortierte samt Begründung stehen in vorauswahl.json.")
        _print_vorauswahl_bilanz(urteile, len(pairs), settings.ai.model_for_screening())

    print(f"Suchlauf gespeichert: {ordner}")
    print("Bewerbungen erzeugen: rookru bewerben --anzahl N")
    return 0


def _collect_jobs(
    args: argparse.Namespace, settings: Settings, template: TemplateData | None = None
) -> list[Job]:
    if args.stellen:
        jobs = load_jobs_file(args.stellen)
        return jobs[: args.anzahl] if args.anzahl else jobs
    if args.query:
        settings.search.queries = [args.query]
    if args.ort:
        settings.search.where = args.ort

    pairs, urteile, ordner = suchlauf(args, settings, template, offline=args.offline)
    if not pairs:
        return []
    if urteile is not None:
        _print_vorauswahl_bilanz(urteile, len(pairs), settings.ai.model_for_screening())
    print(f"Suchlauf gespeichert: {ordner}\n")
    if urteile is None:
        return [job for job, _, _ in pairs][: args.anzahl]
    return [urteil.job for urteil in urteile if urteil.fits][: args.anzahl]


def cmd_bewerben(args: argparse.Namespace) -> int:
    settings = load_settings(args.profil)
    missing = settings.missing_files()
    if missing:
        print("Fehlende Dateien — zuerst 'rookru pruefen' ausführen:")
        for entry in missing:
            print(f"  {entry}")
        return 1

    template_data = read_template(settings.templates.cv)
    jobs = _collect_jobs(args, settings, template_data)
    if not jobs:
        hinweis = ""
        if not args.stellen:
            # Zeige den neuesten Suchlauf als Fallback-Option an
            runs_dir = settings.runs_dir
            if runs_dir.is_dir():
                neuester = next(
                    (p for p in sorted(runs_dir.iterdir(), reverse=True) if p.is_dir()), None
                )
                if neuester and (neuester / "vorauswahl.json").is_file():
                    hinweis = (
                        f"\n  Tipp: Nutze einen gespeicherten Suchlauf als Fallback:\n"
                        f"  rookru bewerben --anzahl N --stellen {neuester / 'vorauswahl.json'}"
                    )
                elif neuester and (neuester / "suche.json").is_file():
                    hinweis = (
                        f"\n  Tipp: Nutze einen gespeicherten Suchlauf als Fallback:\n"
                        f"  rookru bewerben --anzahl N --stellen {neuester / 'suche.json'}"
                    )
        print(
            "Keine passenden Stellen gefunden."
            + ("" if args.ohne_vorauswahl else " Mit --ohne-vorauswahl bewirbst du dich "
               "auf die bestplatzierten Treffer der Suche, ohne die KI zu fragen.")
            + hinweis
        )
        return 1

    try:
        composer = build_composer(offline=args.offline, ai=settings.ai)
    except ComposerError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    if args.offline:
        print("⚠ Testmodus: Brieftexte sind Platzhalter und nicht versandfertig.\n")

    style_example = load_style_example(settings)

    erfolge, fehler = 0, 0
    for i, job in enumerate(jobs, 1):
        print(f"[{i}/{len(jobs)}] {job.title} — {job.company}")
        try:
            app = build_application(
                settings, job, composer, template_data, style_example
            )
        except (ComposerError, BundleError, ConversionError) as exc:
            fehler += 1
            print(f"    ✗ {exc}\n")
            continue

        erfolge += 1
        print(f"    Schwerpunkt: {app.focus.label} — {app.focus.reason or '—'}")
        print(f"    Brief: {app.letter.word_count()} Wörter, {app.letter_pages} Seite(n)")
        print(f"    Bündel: {app.bundle_pdf.name} ({app.bundle_pages} Seiten)")
        print(f"    Ordner: {app.directory}")
        for warnung in app.warnings:
            print(f"    ⚠ {warnung}")
        print()

    print(f"Fertig: {erfolge} Bewerbung(en) erzeugt, {fehler} Fehler.")
    if erfolge:
        print("Vor dem Abschicken jede Bewerbung selbst gegenlesen — "
              "das Skript verschickt nichts.")
    return 0 if fehler == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rookru",
        description="Passende Stellen finden und daraus Bewerbungsunterlagen erzeugen.",
    )
    parser.add_argument("--profil", default=DEFAULT_PROFILE, help="Pfad zu profil.yaml")
    sub = parser.add_subparsers(dest="befehl", required=True)

    p_check = sub.add_parser("pruefen", help="Konfiguration und Werkzeuge prüfen")
    p_check.set_defaults(func=cmd_pruefen)

    p_search = sub.add_parser("suchen", help="Stellen bei den konfigurierten Börsen suchen und anzeigen")
    p_search.add_argument("--query", help="Suchbegriff (überschreibt profil.yaml)")
    p_search.add_argument("--ort", help="Ort (überschreibt profil.yaml)")
    p_search.add_argument("--treffer", type=int, help="Anzahl Treffer")
    p_search.add_argument(
        "--ohne-vorauswahl",
        action="store_true",
        help="Ohne KI-Vorauswahl: nur die Reihung der Suche, kein Mistral-Aufruf",
    )
    p_search.set_defaults(func=cmd_suchen)

    p_apply = sub.add_parser("bewerben", help="Unterlagen für gefundene Stellen erzeugen")
    p_apply.add_argument("--anzahl", type=int, default=3, help="Wie viele Stellen (Standard: 3)")
    p_apply.add_argument("--query", help="Suchbegriff (überschreibt profil.yaml)")
    p_apply.add_argument("--ort", help="Ort (überschreibt profil.yaml)")
    p_apply.add_argument("--stellen", help="YAML-Datei mit Stellen statt Online-Suche")
    p_apply.add_argument(
        "--ohne-vorauswahl",
        action="store_true",
        help="Ohne KI-Vorauswahl: die bestplatzierten Treffer der Suche nehmen",
    )
    p_apply.add_argument(
        "--offline",
        action="store_true",
        help="Ohne Mistral-API: Platzhaltertext, nur zum Prüfen des Layouts",
    )
    p_apply.set_defaults(func=cmd_bewerben)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        ConfigError,
        AdzunaError,
        CareerjetError,
        EuresError,
        JoobleError,
        SourceError,
        ScreeningError,
        ConversionError,
    ) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
