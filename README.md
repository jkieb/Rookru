# Rookru

Findet passende Stellen bei Adzuna und Careerjet und erzeugt daraus vollständige
Bewerbungsunterlagen: ein je Stelle neu geschriebenes Motivationsschreiben, einen
auf die Stelle zugeschnittenen Lebenslauf und ein fertiges PDF-Bündel mit allen
Anlagen.

**Das Skript verschickt nichts.** Es legt die Unterlagen in einen Ordner; das
Abschicken machst du selbst.

## Was pro Stelle passiert

1. **Suchen** — alle unter `suche.quellen` eingetragenen Börsen werden mit
   deinen Suchbegriffen abgefragt und die Treffer zusammengeführt; dieselbe
   Stelle bei zwei Börsen erscheint einmal. Treffer mit Ausschlusswörtern
   fliegen raus. Sortiert wird zuerst danach, wie viele Wörter des Suchbegriffs
   im Stellentitel stehen, dann nach passenden Schwerpunkt-Stichwörtern — so
   steht die gesuchte Werkstudentenstelle vor der Vollzeitstelle, die zufällig
   mehr Fachbegriffe enthält.
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
     Lebenslauf und danach deine Anlagen in der Reihenfolge aus `profil.yaml`,
     mit Lesezeichen je Teil
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
ADZUNA_APP_ID=…       # kostenlos: https://developer.adzuna.com/
ADZUNA_APP_KEY=…
CAREERJET_API_KEY=…   # kostenlos: https://www.careerjet.com/partners/api/
JOOBLE_API_KEY=…      # kostenlos auf Anfrage: https://jooble.org/api/about
MISTRAL_API_KEY=…     # https://console.mistral.ai/
```

Gebraucht wird nur, was in `suche.quellen` steht — wer bloß Adzuna nutzt,
braucht keinen Careerjet-Schlüssel. `rookru pruefen` meldet genau die, die
fehlen.

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
privat/unterlagen/sammelzeugnis.pdf     # Namen frei wählbar — maßgeblich ist,
privat/unterlagen/maturazeugnis.pdf     # was unter 'unterlagen' in profil.yaml
privat/unterlagen/praktikumszeugnisse.pdf   # steht, in genau dieser Reihenfolge
```

Ein Bewerbungsfoto gehört in die Lebenslauf-Vorlage selbst (frei positioniert,
rechts oben) — Rookru übernimmt es von dort in jeden erzeugten Lebenslauf.

Dann prüfen, ob alles zusammenpasst:

```bash
.venv/bin/python -m rookru pruefen
```

### Suchbegriffe: nach Können suchen, nicht nur nach dem Fach

Werkstudentenstellen nennen das Studienfach oft überhaupt nicht. Eine Anzeige
„Werkstudent\*in Sales & CRM Support" verlangt nur „Bachelorstudium" plus VBA,
SQL und Access — über `Werkstudent Maschinenbau` ist sie unauffindbar, über
`Werkstudent VBA` steht sie an erster Stelle. Alle drei Börsen durchsuchen den
**Volltext** der Anzeige, auch wenn sie nur einen Anriss zurückliefern; die
Suche nach den eigenen Fähigkeiten erreicht deshalb Stellen, die die Suche nach
dem Fach nie findet.

Dafür gibt es die Kombinationssuche: jede Rolle wird mit jedem Thema verbunden.

```yaml
suche:
  rollen: [Werkstudent, Praktikum, studentische Aushilfe]
  themen: [Maschinenbau, Konstruktion, CAD, 3D-Druck, Python, VBA, SQL, Datenauswertung]
  query:                 # zusätzliche Begriffe, unabhängig von den Kombinationen
    - Werkstudent Maschinenbauingenieur
```

Daraus werden `Werkstudent Maschinenbau`, `Werkstudent Konstruktion`, …,
`studentische Aushilfe Datenauswertung` — 3 × 8 = 24 Begriffe. Unter `themen`
gehört das, was du kannst, nicht das, was du studierst.

**Jede Kombination ist eine Anfrage je Quelle.** 24 Begriffe × 3 Börsen sind 72
Anfragen und rund anderthalb Minuten; ein Fortschrittsbalken zeigt, wo die Suche
gerade steht. Wird es zu langsam, kürze die Themenliste — sie ist der Hebel.

Der Balken läuft auf stderr, `rookru suchen > treffer.txt` bleibt also sauber.

### Stellenquellen

Welche Börsen abgefragt werden, steht unter `suche.quellen`:

```yaml
suche:
  quellen: [adzuna, careerjet]
  land: at                 # at, de, ch …
  ort: Wien
  umkreis_km: 25
  # locale: de_AT          # optional, nur Careerjet; sonst aus 'land' abgeleitet
```

| Quelle | Abdeckung | Besonderheiten |
| --- | --- | --- |
| `adzuna` | breit, viele Länder | mehrwortige Begriffe werden als „alle Wörter" gesucht; kennt einen Altersfilter |
| `careerjet` | bündelt zusätzliche Börsen | Altersfilter rechnet Rookru selbst; kürzere Ausschreibungstexte |
| `jooble` | Aggregator, deckt u. a. karriere.at mit ab | Umkreis nur in festen Stufen (0/4/8/16/26/40/80 km) — Rookru rundet; Altersfilter rechnet Rookru selbst |

karriere.at, StepStone und Indeed lassen sich nicht direkt anbinden: Indeed hat
seine Publisher-API 2024 abgeschaltet, die StepStone-Schnittstelle dient
Arbeitgebern zum Inserieren, und karriere.at bietet weder API noch RSS. Über
`jooble` kommen deren Inhalte trotzdem teilweise herein.

Eine Stelle, die bei beiden steht, erscheint einmal — zusammengeführt über Firma
und Titel, auch bei unterschiedlicher Schreibweise.

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

Es gibt drei Befehle: `pruefen`, `suchen`, `bewerben`.

### Der übliche Ablauf

**1. Einmal prüfen, ob alles steht.** Meldet fehlende Vorlagen, Anlagen,
API-Schlüssel und LibreOffice, und zeigt, welche Abschnitte des Lebenslaufs
angepasst werden können:

```bash
.venv/bin/python -m rookru pruefen
```

**2. Stellen ansehen, ohne etwas zu erzeugen.** Kostet keinen Mistral-Aufruf:

```bash
.venv/bin/python -m rookru suchen
```

Jeder Treffer zeigt Firma, Ort, Datum, Quelle und zwei Zahlen: `Titel` sind die
Wörter des Suchbegriffs im Stellentitel, `Schwerpunkt` die passenden
Stichwörter aus `profil.yaml`. Danach ist auch sortiert.

```
 1. Werkstudent Maschinenbauingenieur Teil- oder Vollzeit (all genders)
    Angst+Pfister Austria · Wien · 2026-07-19 · adzuna · Titel 2 · Schwerpunkt 0 [—]
```

**3. Unterlagen wirklich erzeugen** — für die N bestplatzierten Treffer, ein
Mistral-Aufruf je Stelle. Das ist der eigentliche Zweck des Werkzeugs:

```bash
.venv/bin/python -m rookru bewerben --anzahl 3
```

Fang beim ersten Mal mit `--anzahl 1` an, sieh dir das Ergebnis an, und dreh
erst dann hoch.

Der Lauf meldet je Stelle, was er tut:

```
[1/2] Werkstudent Maschinenbauingenieur — Angst+Pfister Austria
    Schwerpunkt: Konstruktion / additive Fertigung — Die Ausschreibung betont …
    Brief: 287 Wörter, 1 Seite(n)
    Bündel: 2026_08_14_Bewerbungsunterlagen_AngstPfisterAustria.pdf (11 Seiten)
    Ordner: /…/out/2026_08_14_AngstPfisterAustria_WerkstudentMaschinenbauingen
    ⚠ Empfängeradresse unvollständig (Straße, PLZ/Ort fehlt) — …
```

**4. Ergebnis ansehen.** Je Stelle entsteht ein Ordner
`out/<Datum>_<Firma>_<Stelle>/`:

| Datei | Wozu |
| --- | --- |
| `<Datum>_Bewerbungsunterlagen_<Firma>.pdf` | **das fertige Bündel** — Brief, Lebenslauf und alle Anlagen mit Lesezeichen; das ist die Datei, die du verschickst |
| `Motivationsschreiben_<Name>_<Firma>.pdf` / `.docx` | einzeln, falls ein Portal die Teile getrennt will. Das `.docx` ist zum Nachbessern da |
| `Lebenslauf_<Name>_<Firma>.pdf` / `.docx` | dito |
| `bewerbung.json` | Brieftext, gewählter Schwerpunkt samt Begründung, alle Warnungen — zum Nachlesen, was das Modell warum entschieden hat |

**5. Gegenlesen — das bleibt deine Aufgabe.** Sinnvolle Reihenfolge: Brief
ganz lesen; im Lebenslauf die drei änderbaren Abschnitte (AUSBILDUNG, PROJEKTE,
BESONDERE KENNTNISSE) mit deiner Vorlage vergleichen; Empfängeradresse prüfen,
wenn du per Post schickst. Nachbessern kannst du im `.docx` — dann aber neu nach
PDF exportieren, denn das Bündel wird dabei nicht automatisch neu gebaut.

Die Warnungen am Ende sind ernst gemeint. Die häufigsten:

| Warnung | Was zu tun ist |
| --- | --- |
| `Empfängeradresse unvollständig` | Adresse im `.docx` ergänzen oder die Stelle per `--stellen` mit voller Anschrift erfassen |
| `Motivationsschreiben füllt nur X %` | `brief.min_woerter` anheben |
| `Absatzabstände auf X % gestaucht` | Brief war zu lang — `brief.max_woerter` senken |
| `Projekt '…' nicht in der Vorlage gefunden` | das Modell wollte etwas außerhalb der freigegebenen Abschnitte ändern; die Schutzlogik hat es abgelehnt, meist unkritisch |

### Eine bestimmte Stelle statt der Suche

Für Ausschreibungen, die dir wichtig sind oder die keine Börse liefert:
Ausschreibung in eine YAML-Datei schreiben (`stellenanzeigen/stellen.beispiel.yaml` als
Muster) — dort kannst du auch Abteilung, Anschrift, Anrede und Referenz für den
Briefkopf angeben, die keine API liefert:

```bash
.venv/bin/python -m rookru bewerben --stellen meine_stellen.yaml
```

### Suche für einen Lauf überschreiben

`--query` und `--ort` gelten nur für diesen Aufruf, `profil.yaml` bleibt
unangetastet:

```bash
.venv/bin/python -m rookru suchen --query "Praktikum Konstruktion" --ort Graz
.venv/bin/python -m rookru bewerben --query "Werkstudent CAD" --anzahl 1
```

### Layout testen, ohne die API zu bezahlen

`--offline` erzeugt Platzhaltertext statt echter Briefe — gut, um nach einer
Änderung an den Vorlagen Seitenumbruch und Bündel zu prüfen:

```bash
.venv/bin/python -m rookru bewerben --stellen stellenanzeigen/stellen.beispiel.yaml --offline
```

### Alle Optionen

| Befehl | Option | Bedeutung |
| --- | --- | --- |
| *(alle)* | `--profil PFAD` | andere Konfiguration statt `profil.yaml` |
| `suchen` | `--query TEXT` | Suchbegriff für diesen Lauf |
| | `--ort ORT` | Ort für diesen Lauf |
| | `--treffer N` | Treffer je Quelle und Suchbegriff (Standard 20) |
| `bewerben` | `--anzahl N` | wie viele Stellen (Standard 3) |
| | `--query` / `--ort` | wie bei `suchen` |
| | `--stellen DATEI` | Stellen aus YAML statt aus der Online-Suche |
| | `--offline` | Platzhaltertext statt Mistral-Aufruf |

Fällt eine Börse aus, läuft die Suche mit den übrigen weiter und meldet das
Problem als Warnung; erst wenn keine einzige antwortet, bricht sie ab.

## Grenzen, die du kennen solltest

- **Beide Börsen kürzen Ausschreibungstexte.** Adzuna liefert rund 500 Zeichen,
  Careerjet nur rund 270 — und lässt sich auch per `fragment_size` nicht zu mehr
  überreden. Der Brief wird dadurch allgemeiner. Für Bewerbungen, die dir
  wichtig sind: Ausschreibung in eine eigene YAML-Datei kopieren
  (`stellenanzeigen/stellen.beispiel.yaml` als Muster) und `--stellen` benutzen — dort
  kannst du auch Abteilung und Anschrift für den Briefkopf angeben, die keine
  API liefert.
- **Nach dem Studienfach allein findest du wenig.** Gemessen im August 2026:
  `Werkstudent Maschinenbau` in Wien ergab über Adzuna und Careerjet zusammen
  zwei Treffer. Mit Jooble und der Kombinationssuche über Fähigkeiten wurden
  daraus 141 — siehe „Suchbegriffe" oben. karriere.at und der AMS eJob-Room
  haben keine offene Such-API; ihre Inhalte kommen teilweise über `jooble`
  herein, ansonsten lohnt die Suche von Hand, gefolgt von `--stellen`.
- **LibreOffice bricht Seiten leicht anders um als Word.** Passt ein Dokument
  nicht auf eine Seite, verkleinert Rookru stufenweise erst die Abstände, dann
  die Schrift, und schreibt eine Warnung dazu. Ist auf deinem Rechner die echte
  Arial installiert, passt der Lebenslauf meist ohne jede Verkleinerung.
- **Die Briefspanne gehört zu deiner Vorlage.** `brief.min_woerter` und
  `max_woerter` bestimmen, wie voll die Seite wird; wie viele Wörter darauf
  passen, hängt an Schrift, Rändern und Absatzzahl deiner Vorlage. Wird der
  Brief zweiseitig, ist `max_woerter` zu hoch; meldet Rookru einen niedrigen
  Füllgrad, ist `min_woerter` zu niedrig. **Das Modell überschießt die
  Obergrenze regelmäßig um 10–15 %** — setze `max_woerter` entsprechend
  niedriger als das, was gerade noch auf die Seite passt.
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
