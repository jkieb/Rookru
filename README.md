# Rookru

Findet passende Stellen bei Adzuna und erzeugt daraus vollständige
Bewerbungsunterlagen: ein je Stelle neu geschriebenes Motivationsschreiben, einen
auf die Stelle zugeschnittenen Lebenslauf und ein fertiges PDF-Bündel mit allen
Anlagen.

**Das Skript verschickt nichts.** Es legt die Unterlagen in einen Ordner; das
Abschicken machst du selbst.

## Was pro Stelle passiert

1. **Suchen** — Adzuna liefert Treffer zu deinen Suchbegriffen. Treffer mit
   Ausschlusswörtern fliegen raus, der Rest wird nach passenden
   Schwerpunkt-Stichwörtern sortiert.
2. **Schwerpunkt bestimmen** — anhand der Ausschreibung: eine Software-Stelle
   rückt GitHub und CS50 nach vorne, eine Konstruktionsstelle den privaten
   3D-Drucker und die Bachelorarbeit. Regeln stehen in `profil.yaml`.
3. **Texten** — ein Aufruf an die Mistral-API (`mistral-large-latest`, in
   `profil.yaml` umstellbar) schreibt den Brieftext und die
   Lebenslauf-Anpassung. Die Antwort ist per JSON-Schema festgelegt. Grundlage
   ist ausschließlich dein bestehender Lebenslauf; das Modell darf nichts
   hinzuerfinden.
4. **Dokumente bauen** —
   - `Motivationsschreiben_<Name>_<Firma>.docx` + `.pdf` (einseitig)
   - `Lebenslauf_<Name>_<Firma>.docx` + `.pdf` (einseitig)
   - `<Datum>_Bewerbungsunterlagen_<Firma>.pdf` — Motivationsschreiben,
     Lebenslauf, Sammelzeugnis, Maturazeugnis, Praktikumszeugnis, mit
     Lesezeichen je Teil
   - `bewerbung.json` — Brieftext, Schwerpunkt, Warnungen zum Nachlesen

Der Lebenslauf wird **nicht neu gebaut**, sondern deine Word-Vorlage wird
übernommen. Geändert werden nur drei Abschnitte:

| Abschnitt | Was die KI darf |
| --- | --- |
| AUSBILDUNG | nur Stichpunkte umformulieren (z. B. die Bachelorarbeit auf die Stelle ausrichten). Reihenfolge, Zeiträume, Institutionen und Abschlüsse bleiben; kein Eintrag wird entfernt |
| PROJEKTE | umsortieren, Stichpunkte umformulieren |
| BESONDERE KENNTNISSE UND FÄHIGKEITEN | Zeilen nach Relevanz sortieren und umformulieren |

Persönliche Daten, Berufserfahrungen und Sprachkenntnisse bleiben Zeichen für
Zeichen wie in der Vorlage.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

LibreOffice wird für die PDF-Erzeugung gebraucht (inklusive Writer-Modul):

```bash
sudo apt install libreoffice-writer     # Debian/Ubuntu
brew install --cask libreoffice         # macOS
```

Zugangsdaten in `.env` eintragen (Vorlage: `.env.example`):

```
ADZUNA_APP_ID=…     # kostenlos: https://developer.adzuna.com/
ADZUNA_APP_KEY=…
MISTRAL_API_KEY=…   # https://console.mistral.ai/
```

## Einrichten

```bash
cp profil.example.yaml profil.yaml
```

In `profil.yaml` eintragen: Name, Pfade zu deinen beiden Word-Vorlagen, deine
Anlagen in der gewünschten Reihenfolge, Schwerpunktregeln und Suchbegriffe.

Ablage für alles Persönliche (per `.gitignore` ausgeschlossen):

```
privat/vorlagen/motivationsschreiben_vorlage.docx
privat/vorlagen/lebenslauf_vorlage.docx
privat/vorlagen/stilbeispiel.txt        # optional
privat/unterlagen/sammelzeugnis.pdf
privat/unterlagen/maturazeugnis.pdf
privat/unterlagen/praktikumszeugnis.pdf
```

Dann prüfen, ob alles zusammenpasst:

```bash
.venv/bin/python -m rookru pruefen
```

### Platzhalter in der Motivationsschreiben-Vorlage

| Platzhalter | Inhalt |
| --- | --- |
| `{{DATUM}}` | Datum, z. B. `13. August 2026` |
| `{{FIRMA_NAME}}` | Unternehmen |
| `{{FIRMA_ABTEILUNG}}` | Abteilung — Zeile entfällt, wenn unbekannt |
| `{{FIRMA_STRASSE}}` | Straße — Zeile entfällt, wenn unbekannt |
| `{{FIRMA_PLZ_ORT}}` | PLZ und Ort |
| `{{STELLE}}` | Fortsetzung nach „Bewerbung als “ |
| `{{ABSATZ_1}}` … `{{ABSATZ_4}}` | Brieftext; weitere Absätze werden automatisch ergänzt |

`stilbeispiel.txt` ist optional: Steht dort ein früherer Brief von dir, übernimmt
das Modell Tonfall und Satzbau daraus — aber keine Inhalte.

### Lebenslauf-Vorlage

Erwartet wird der Aufbau deiner bestehenden Vorlage: Abschnittsüberschriften in
Großbuchstaben, darunter je Eintrag eine zweispaltige Tabelle (links die
Kennung, rechts Text und `●`-Stichpunkte). Die Kennungen der linken Spalte
(z. B. `Prusa MK3S+`, `GitHub`) sind gleichzeitig die Namen, mit denen das
Modell die Reihenfolge angibt.

## Benutzung

```bash
# Stellen ansehen, ohne etwas zu erzeugen
.venv/bin/python -m rookru suchen
.venv/bin/python -m rookru suchen --query "Praktikum Konstruktion" --ort Graz

# Unterlagen für die 3 bestpassenden Treffer erzeugen
.venv/bin/python -m rookru bewerben --anzahl 3

# Einzelne, von Hand erfasste Stellen (mit Firmenadresse für den Briefkopf)
.venv/bin/python -m rookru bewerben --stellen examples/stellen.beispiel.yaml

# Layout prüfen, ohne die Mistral-API zu benutzen (Platzhaltertext)
.venv/bin/python -m rookru bewerben --stellen examples/stellen.beispiel.yaml --offline
```

Ergebnis liegt unter `out/<Datum>_<Firma>_<Stelle>/`.

## Grenzen, die du kennen solltest

- **Adzuna kürzt Ausschreibungstexte.** Die API liefert oft nur einen Anriss der
  Stellenbeschreibung. Der Brief wird dadurch allgemeiner. Für Bewerbungen, die
  dir wichtig sind: Ausschreibung in eine eigene YAML-Datei kopieren
  (`examples/stellen.beispiel.yaml` als Muster) und `--stellen` benutzen — dort
  kannst du auch Abteilung und Anschrift für den Briefkopf angeben, die Adzuna
  nicht liefert.
- **LibreOffice bricht Seiten leicht anders um als Word.** Passt ein Dokument
  nicht auf eine Seite, verkleinert Rookru stufenweise erst die Abstände, dann
  die Schrift, und schreibt eine Warnung dazu. Ist auf deinem Rechner die echte
  Arial installiert, passt der Lebenslauf meist ohne jede Verkleinerung.
- **Deine Daten gehen an die Mistral-API.** Für jede Bewerbung werden dein
  Lebenslauf-Inhalt und die Stellenausschreibung übertragen. Ohne API-Zugriff
  läuft nur `--offline`, und der erzeugt reinen Platzhaltertext.
- **Gegenlesen bleibt Pflicht.** Das Modell soll nichts erfinden und wird
  entsprechend angewiesen — garantieren lässt sich das nicht. Lies den Brief und
  die geänderten Lebenslauf-Zeilen, bevor du etwas abschickst.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
```

Die Tests erzeugen ihre Vorlagen selbst und brauchen weder Netzwerk noch
API-Schlüssel noch die Dateien aus `privat/`.
