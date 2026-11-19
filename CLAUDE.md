# Projekt: „Play-along“ – Klarinetten-Übungs-Player für Noel

- App-Name (Oberfläche, PWA-Manifest, Home-Bildschirm): **Play-along**
- Repository: https://github.com/tihohub/playalong
- Hosting: GitHub Pages unter **https://tihohub.github.io/playalong/**. Den Base-Path `/playalong/` in Build-Konfiguration, Manifest (`start_url`, `scope`) und Service Worker berücksichtigen.

## Ziel
Ein Übungs-Player ähnlich Tomplay für meinen Sohn Noel (B-Klarinette). Er spielt die Klarinettenstimme vom Blatt, der Player liefert die Begleitung. Er wird fast täglich genutzt. Der laufende Betrieb darf **keine KI/Credits** brauchen. Claude wird nur für Entwicklung und Wartung eingesetzt.

## Nutzer und Niveau
- Noel spielt seit ca. 5 Jahren auf sehr hohem Niveau: Weber Concertino op. 26 teilweise vom Blatt, 32tel-Passagen nach ca. 2 Unterrichtsstunden, Bordogni-Etüden vom Blatt.
- **Keine Vereinfachung** der Noten. Der volle Tonumfang inklusive Altissimo muss sauber dargestellt werden.
- Repertoire für die App: vor allem **moderne Film- und Orchestermusik**.
- Die Bedienoberfläche ist auf **Deutsch**.

## Geräte und Infrastruktur
- **iPad (Noel):** Hier läuft der Player als Web-App (PWA) in Safari, auf dem Home-Bildschirm abgelegt, im Vollbild und **offline-fähig**. Es gibt keine native App (kein Mac, kein Apple-Entwicklerkonto).
- **Verarbeitung („Server“):** Zum Testen ein Windows-Laptop (ThinkPad T14, 8 GB RAM, keine dedizierte GPU, nur zeitweise verfügbar). Später ein gebrauchter Mini-PC mit Linux (z. B. ThinkCentre M920q, i5-8500T, 16 GB). Alles muss **CPU-only** laufen.
- **NAS:** USB-Speicher an einer FRITZ!Box, erreichbar per SMB. Er dient nur als Ablage für fertige Liedpakete, kann keinen Code ausführen.
- **Hosting des Players:** Statisch über HTTPS (Voraussetzung für Service Worker/Offline auf iOS), z. B. GitHub Pages. Im Repo liegen **keine Musikdateien**, nur Code.

## Datenfluss
1. Ich lege auf dem Server MusicXML und/oder MP3 ab.
2. Die Verarbeitungs-Pipeline (Python, CLI) erzeugt pro Lied **ein Liedpaket** (z. B. `.playalong` = ZIP mit `manifest.json`, `score.musicxml`, optional `original.mp3`, optional `sync.json`) und schreibt es auf das NAS.
3. Auf dem iPad wählt Noel im Player „Lied importieren“ das Paket über die iOS-Dateien-App (SMB-Freigabe der FRITZ!Box) aus. Der Player speichert es in IndexedDB.
4. Danach läuft alles offline auf dem iPad, ohne Server, NAS oder WLAN.

## Funktionen Version 1: Noten-Player (iPad, rein clientseitig)
- MusicXML/MXL laden (Import aus Datei/Liedpaket) und anzeigen, z. B. mit OpenSheetMusicDisplay.
- Die Klarinettenstimme in **B (transponiert notiert)** anzeigen. Ist die Vorlage klingend notiert, automatisch transponieren (große Sekunde aufwärts).
- Eigene Stimme oben, Klavierstimme optional einblendbar.
- **Mitlaufender Cursor**, **automatisches Umblättern/Scrollen**, optimiert für iPad hoch und quer.
- Wiedergabe der **Klavierstimme** mit gutem Klavier-Sample (SoundFont/Samples, offline gecacht).
- Optional die **Klarinettenstimme zum Anhören** (umschaltbar, Lautstärke regelbar).
- Bedienung: **Play/Stop**, **Tempo-Regler in %** (gilt relativ für alle Tempoangaben im Stück), Einzähler, Sprung zu Takt/Abschnitt (Rehearsal Marks, Tempowechsel).
- **Übungsschleife:** Taktbereich wählen und in Schleife spielen, optional mit automatischer Tempo-Steigerung pro Durchgang (z. B. +5 % bis Ziel).
- **Metronom-Modus** für Stücke ohne Begleitung (Etüden).
- **Fermaten und Kadenzen („a piacere“):** optional anhalten und warten, bis Noel tippt, dann weiter.
- Mehrtaktpausen/Tutti: Die Begleitung spielt weiter, der Cursor bleibt sichtbar.
- Bibliothek: Liste der importierten Lieder, Löschen, zuletzt gespielte zuerst.

## Funktionen Version 2: Original-Audio + Verarbeitung (Server)
- Python-CLI, CPU-only, läuft unter Windows und Linux.
- **Audio-Score-Alignment:** Die MP3 (Original mit Melodie) wird mit der MusicXML synchronisiert (z. B. Chroma-Features + DTW, librosa/synctoolbox) und erzeugt eine Takt→Zeit-Zuordnung (`sync.json`).
- Im Player umschaltbar: **Klavier aus Noten** oder **Original-MP3**, mit Cursor-Synchronisation.
- Tempoänderung beim Original **ohne Tonhöhenänderung** (`preservesPitch`/Time-Stretching im Browser, ausreichend für 50–100 %).
- Paket-Builder: erzeugt `.playalong` und schreibt es in einen konfigurierbaren Zielordner (NAS-Pfad).
- Optional später: Fallback MP3→Noten (Demucs + Basic Pitch) als **Rohentwurf** zur Nachbearbeitung in MuseScore. Ausdrücklich niedrige Priorität, da bei Orchestermusik ungenau.

## Technische Leitplanken
- Player: möglichst einfacher Stack (Vanilla JS/TypeScript + Vite o. Ä.), keine Server-Abhängigkeit zur Laufzeit, Service Worker für Offline.
- Audio-Timing per Web Audio API (Scheduling mit Vorlauf), iOS-Eigenheiten beachten (Audio-Start nur nach Nutzerinteraktion, Stummschalter).
- Wenig Abhängigkeiten, alles quelloffen. Keine Tracking- oder Cloud-Dienste (Datenschutz ist mir wichtig).
- README mit klarer Schritt-für-Schritt-Anleitung auf Deutsch für mich als Nicht-Entwickler: Installation, Lied hinzufügen, Deployment.

## Vorgehen
1. Repo-Struktur anlegen (`player/`, `pipeline/`, `docs/`).
2. Version 1 bauen, mit einer kleinen selbst erstellten, gemeinfreien Test-MusicXML (Klarinette in B + Klavier, mit Tempowechsel, Fermate, Mehrtaktpause).
3. Deployment auf GitHub Pages einrichten, damit ich auf dem iPad testen kann.
4. Danach Version 2 (Pipeline + Original-Audio-Modus).

Nach jedem Schritt kurz zusammenfassen, was ich auf dem iPad testen soll.
