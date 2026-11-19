# Play-along

Übungs-Player für Klarinette (in B): Noel spielt seine Stimme vom Blatt, die App spielt die Klavierbegleitung, zeigt einen mitlaufenden Cursor und blättert automatisch um. Alles läuft **offline auf dem iPad**, ohne Server, ohne Cloud und ohne KI.

**Adresse der App:** <https://tihohub.github.io/playalong/>

| Ordner | Inhalt |
|---|---|
| `player/` | Die Web-App für das iPad (Version 1) |
| `pipeline/` | Werkzeuge für den Server (Version 2, folgt), dort liegt schon das Skript für die Demo-Stücke |
| `docs/` | Format der Liedpakete, Lizenzen |

---

## 1. Einmalig: Veröffentlichen auf GitHub Pages

Das musst du nur **einmal** einrichten. Danach wird jede Änderung automatisch veröffentlicht.

1. Auf GitHub das Repository öffnen: <https://github.com/tihohub/playalong>
2. Oben auf **Settings** → links **Pages**.
3. Bei **Build and deployment** → **Source** die Option **GitHub Actions** wählen.
4. Den Code in den Branch `main` übernehmen (den Pull Request zusammenführen, „Merge“).
5. Unter dem Reiter **Actions** siehst du den Lauf „Player auf GitHub Pages veröffentlichen“. Wenn er grün ist (nach ca. 1–2 Minuten), ist die App unter <https://tihohub.github.io/playalong/> erreichbar.

Falls du den Lauf von Hand starten willst: **Actions** → „Player auf GitHub Pages veröffentlichen“ → **Run workflow**.

## 2. Einmalig: App auf dem iPad einrichten

1. Auf dem iPad **Safari** öffnen (nicht Chrome) und <https://tihohub.github.io/playalong/> aufrufen.
2. Auf das **Teilen-Symbol** (Quadrat mit Pfeil) tippen → **Zum Home-Bildschirm** → **Hinzufügen**.
3. Die App ab jetzt immer über das neue Symbol **Play-along** auf dem Home-Bildschirm starten. Sie öffnet sich im Vollbild.
4. Einmal mit WLAN öffnen, kurz warten und einmal „▶“ drücken. Dann sind App und Klänge gespeichert. Unten in der Bibliothek steht dann **„Offline bereit ✓“**. Ab jetzt funktioniert alles auch ohne WLAN.

**Tipp zum Ton:** Ab iPadOS 17 spielt die App auch bei eingeschaltetem Stummschalter. Falls nichts zu hören ist: Stummschalter bzw. „Stumm“ im Kontrollzentrum ausschalten, Lautstärke hochdrehen und prüfen, ob ein Bluetooth-Lautsprecher verbunden ist.

## 3. Ein Lied hinzufügen

Die App braucht die Noten als **MusicXML** (`.musicxml`, `.xml` oder `.mxl`). PDF oder Fotos gehen nicht.

**MusicXML bekommen:**
- **MuseScore** (kostenlos, <https://musescore.org>): Stück öffnen → **Datei → Exportieren → MusicXML** (`.mxl` oder `.musicxml`).
- Viele Noten-Shops und Notensatzprogramme (Sibelius, Finale, Dorico) können ebenfalls MusicXML exportieren.
- Die Partitur sollte die **Klarinettenstimme** und die **Klavierstimme** enthalten. Die Klarinettenstimme wird automatisch erkannt (Name „Klarinette“ oder „Clarinet“).

**Auf das iPad bringen:**
1. Die Datei auf den NAS-Speicher an der FRITZ!Box kopieren (oder per AirDrop, iCloud Drive, E-Mail …).
2. In Play-along auf **„＋ Lied importieren“** tippen.
3. In der Dateien-App die FRITZ!Box-Freigabe öffnen und die Datei antippen. Mehrere Dateien auf einmal gehen auch.
4. Das Lied steht jetzt in der Bibliothek und ist dauerhaft auf dem iPad gespeichert.

> **FRITZ!Box in der Dateien-App einrichten (einmalig):** Dateien-App → oben rechts „…“ → **Mit Server verbinden** → `smb://fritz.box` → mit dem FRITZ!Box-Benutzer anmelden.

**Klingend oder in B?** Ist die Klarinettenstimme in der Vorlage *klingend* notiert (ohne Transpositionsangabe), wird sie automatisch eine große Sekunde höher in B gesetzt. Wenn die Erkennung einmal falsch liegt: im Player auf ⚙︎ → **Stimmen** → „Notiert“ umstellen.

## 4. Bedienung (für Noel)

| Element | Funktion |
|---|---|
| ▶ / ■ | Start / Stopp. Nach Stopp geht es am Anfang des aktuellen Takts weiter. Es wird vorher eingezählt. |
| ⏮ | Zurück zum Anfang (oder zum Anfang der Schleife) |
| Tempo-Regler | 25–150 %, gilt für alle Tempoangaben im Stück. Daneben steht das aktuelle Metronom-Tempo. |
| Springen zu … | Studierbuchstaben, Tempowechsel oder eine Taktnummer |
| Auf einen Takt tippen | Setzt die Startposition dorthin |
| ⟲ Schleife | Taktbereich wiederholen. Bereich eingeben oder „Im Notenbild antippen“ (Start- und Endtakt antippen). Optional **Tempo steigern** pro Durchgang (z. B. +5 % bis 100 %). |
| ♩ Metronom | Klick dazuschalten, z. B. für Etüden ohne Begleitung |
| ⚙︎ Einstellungen | Klavierstimme anzeigen, Lautstärken, Klarinettenstimme zum Anhören, Einzähler, Notengröße, Verhalten bei Fermaten |
| Fermate / Kadenz | Der Player hält an und wartet. Weiter mit **„Weiter“**, Tippen auf die Noten, Leertaste oder Bluetooth-Pedal. (Abschaltbar: dann wird die Fermate automatisch ausgehalten.) |

Mehrtaktpausen: Die Begleitung spielt weiter, der Cursor wandert durch die Pause, oben steht die aktuelle Taktnummer.

## 5. Updates

Neue Versionen werden automatisch veröffentlicht. Das iPad holt sie beim nächsten Öffnen mit WLAN und meldet „Neue Version installiert“. Nach dem nächsten Schließen und Öffnen ist sie aktiv. Die Bibliothek bleibt dabei erhalten.

## 6. Datenschutz

- Keine Anmeldung, kein Tracking, keine Cloud-Dienste.
- Die Lieder werden nur auf dem iPad gespeichert (im Browser-Speicher der App).
- Im Repository liegen **keine Musikdateien**, nur Code, die Instrumentenklänge und zwei selbst geschriebene Demo-Stücke.

> Achtung: Wird die App vom Home-Bildschirm gelöscht, sind auch die importierten Lieder auf dem iPad weg. Die Originale liegen ja auf dem NAS.

---

## Für Entwickler

```bash
cd player
npm install
npm run dev      # Entwicklungsserver: http://localhost:5173/playalong/
npm run check    # Typprüfung
npm run build    # fertige App in player/dist
npm run preview  # gebaute App testen (inkl. Offline-Modus)
```

- Stack: TypeScript + Vite, [OpenSheetMusicDisplay](https://opensheetmusicdisplay.org/) für den Notensatz, Web Audio API für die Wiedergabe, IndexedDB für die Bibliothek, eigener Service Worker (`player/sw-template.js`) für den Offline-Betrieb.
- Wichtige Dateien: `src/musicxml/prepare.ts` (Stimmen, Transposition), `src/musicxml/timeline.ts` (Wiederholungen, Tempi, Fermaten), `src/audio/engine.ts` (Wiedergabe), `src/score/view.ts` (Notenbild + Cursor).
- Demo-Stücke neu erzeugen: `python3 pipeline/testdata/make_demo_scores.py player/public/demo`
- Format der Liedpakete: [`docs/liedpaket-format.md`](docs/liedpaket-format.md)
- Lizenzen der Klänge und Bibliotheken: [`docs/LIZENZEN.md`](docs/LIZENZEN.md)
