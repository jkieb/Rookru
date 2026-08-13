"""Kommandozeile: rookru pruefen | suchen | bewerben"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .compose import ComposerError, build_composer, detect_focus
from .config import ConfigError, Settings, load_settings
from .models import Job
from .pipeline import build_application, load_style_example, read_template
from .render.bundle import BundleError
from .render.convert import ConversionError, find_soffice
from .sources.adzuna import AdzunaError, rank_jobs, search_jobs
from .sources.local import load_jobs_file

DEFAULT_PROFILE = "profil.yaml"


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

    if os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"):
        print("✓ Adzuna-Zugang gesetzt")
    else:
        ok = False
        print("✗ ADZUNA_APP_ID / ADZUNA_APP_KEY fehlen")

    print("\nAlles bereit." if ok else "\nEs fehlt noch etwas (siehe ✗ oben).")
    return 0 if ok else 1


def _print_jobs(pairs: list[tuple[Job, int, int]], settings: Settings) -> None:
    for i, (job, score, hits) in enumerate(pairs, 1):
        focus = detect_focus(job, settings.focus_rules)
        marker = f"[{focus.key}]" if focus else "[—]"
        print(f"{i:2d}. {job.title}")
        print(f"    {job.company} · {job.location or 'Ort unbekannt'} · "
              f"{job.created or 'ohne Datum'} · Titel {hits} · Schwerpunkt {score} {marker}")
        if job.url:
            print(f"    {job.url}")


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
          f"{' / ' + settings.search.where if settings.search.where else ''}\n")
    jobs = search_jobs(settings.search)
    pairs = rank_jobs(
        jobs, settings.focus_rules, settings.search.min_score, settings.search.queries
    )
    if not pairs:
        print("Keine Treffer. Suchbegriff weiter fassen oder 'ausschliessen' in profil.yaml prüfen.")
        return 1
    _print_jobs(pairs, settings)
    print(f"\n{len(pairs)} Treffer. Bewerbungen erzeugen: rookru bewerben --anzahl N")
    return 0


def _collect_jobs(args: argparse.Namespace, settings: Settings) -> list[Job]:
    if args.stellen:
        jobs = load_jobs_file(args.stellen)
        return jobs[: args.anzahl] if args.anzahl else jobs
    if args.query:
        settings.search.queries = [args.query]
    if args.ort:
        settings.search.where = args.ort
    jobs = search_jobs(settings.search)
    pairs = rank_jobs(
        jobs, settings.focus_rules, settings.search.min_score, settings.search.queries
    )
    return [job for job, _, _ in pairs][: args.anzahl]


def cmd_bewerben(args: argparse.Namespace) -> int:
    settings = load_settings(args.profil)
    missing = settings.missing_files()
    if missing:
        print("Fehlende Dateien — zuerst 'rookru pruefen' ausführen:")
        for entry in missing:
            print(f"  {entry}")
        return 1

    jobs = _collect_jobs(args, settings)
    if not jobs:
        print("Keine passenden Stellen gefunden.")
        return 1

    try:
        composer = build_composer(offline=args.offline, ai=settings.ai)
    except ComposerError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    if args.offline:
        print("⚠ Testmodus: Brieftexte sind Platzhalter und nicht versandfertig.\n")

    template_data = read_template(settings.templates.cv)
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

    p_search = sub.add_parser("suchen", help="Stellen bei Adzuna suchen und anzeigen")
    p_search.add_argument("--query", help="Suchbegriff (überschreibt profil.yaml)")
    p_search.add_argument("--ort", help="Ort (überschreibt profil.yaml)")
    p_search.add_argument("--treffer", type=int, help="Anzahl Treffer")
    p_search.set_defaults(func=cmd_suchen)

    p_apply = sub.add_parser("bewerben", help="Unterlagen für gefundene Stellen erzeugen")
    p_apply.add_argument("--anzahl", type=int, default=3, help="Wie viele Stellen (Standard: 3)")
    p_apply.add_argument("--query", help="Suchbegriff (überschreibt profil.yaml)")
    p_apply.add_argument("--ort", help="Ort (überschreibt profil.yaml)")
    p_apply.add_argument("--stellen", help="YAML-Datei mit Stellen statt Adzuna-Suche")
    p_apply.add_argument(
        "--offline",
        action="store_true",
        help="Ohne Claude-API: Platzhaltertext, nur zum Prüfen des Layouts",
    )
    p_apply.set_defaults(func=cmd_bewerben)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, AdzunaError, ConversionError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
