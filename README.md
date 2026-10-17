# Polizeimeldungen München & Umland

Automatisch gepflegte Datenbank aller Pressemeldungen der Polizeipräsidien München, Oberbayern Nord, Oberbayern Süd und (erweitert) Schwaben Nord. Dazu gehört ein Dashboard unter <https://secmuc.github.io/Polizeiberichte/>.

## Grundsätze

- **Nur echte Meldungen.** Erfasst wird ausschließlich, was die Polizei veröffentlicht hat. Jeder Datensatz verweist auf das Original auf polizei.bayern.de und enthält den Text wörtlich. Eine automatische Prüfung (`tools/validate.py`) bricht den Lauf ab, wenn ein Text nicht exakt im Original vorkommt.
- **Nichts wird geraten.** Tatdatum, Uhrzeit und Ort werden nur eingetragen, wenn sie eindeutig im Text stehen. Andernfalls bleibt das Feld leer.
- **Abgeleitet ist gekennzeichnet.** Das Delikt (Feld `kategorie`) stammt aus einer regelbasierten Zuordnung ohne Gewichtung (`collector/classify.py`) und steht nicht in der Polizeimeldung selbst.

## Quellen

| Quelle | Zweck |
|---|---|
| polizei.bayern.de – „Neueste Pressemeldungen“ | Neue Meldungen der letzten ca. 14 Tage |
| polizei.bayern.de – Pressearchiv-Suche | Vollständigkeit je Präsidium, Nachladen älterer Zeiträume |
| Telegram @PressePolizeiMuenchen | Zusätzlicher Abgleich für PP München |
| X (optional) | Posts offizieller Accounts, aktiv nur mit Secret `X_BEARER_TOKEN` |

## Datenbank (Ordner `data/`)

| Datei | Inhalt |
|---|---|
| `pressemitteilungen/JJJJ-MM.json` | Originaldokumente: Volltext, SHA-256, Quellen, Erfassungszeitpunkte |
| `meldungen/JJJJ-MM.json` | Einzelmeldungen, aus den Dokumenten zerlegt (eine Zeile im Dashboard) |
| `social/JJJJ-MM.json` | Posts offizieller Social-Media-Accounts |
| `index.json` | Übersicht, Monatsdateien, Status des letzten Laufs |
| `state/queue.json` | Entdeckte, noch nicht abgerufene Dokumente |
| `legacy/` | Datenbestand der alten Scraper (nur Archiv, wird nicht mehr genutzt) |

Felder einer Meldung: `id`, `pm_id`, `nr`, `pp`, `veroeffentlicht`, `tatdatum`, `uhrzeit`, `titel`, `ort`, `ort_quelle`, `abschnitt`, `text`, `url`, `kategorie` (Delikt), `erfasst`.

## Betrieb

- **Automatisch:** GitHub Actions läuft täglich um 07:41 und 17:41 Uhr (MESZ).
- **Manuell / Nachladen:** Actions → „Polizeimeldungen erfassen“ → „Run workflow“. Für ältere Zeiträume trägst du ein Datum bei *Nachladen ab* ein (z. B. `2025-01-01`) und erhöhst das Zeitbudget (z. B. `300`). Wird das Budget erreicht, setzt der nächste Lauf automatisch fort.
- **X aktivieren:** Lege unter Settings → Secrets and variables → Actions ein Secret `X_BEARER_TOKEN` an. Die Abrechnung erfolgt über die X-API je Abruf, die Menge ist pro Lauf begrenzt (`X_MAX_POSTS_PER_ACCOUNT`).
- **Weitere Präsidien oder Kanäle** trägst du in `collector/config.py` ein.

## Lokal ausführen

```bash
pip install -r requirements.txt
python tests/test_offline.py      # Parser-Selbsttest ohne Netz
python -m collector               # täglicher Lauf
python tools/validate.py          # Konsistenzprüfung
```
