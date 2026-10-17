"""Prüft die Datenbank auf Konsistenz. Bricht den Lauf ab (Exit 1), wenn etwas nicht stimmt.

Prüfungen
- jede Meldung verweist auf ein vorhandenes Originaldokument von polizei.bayern.de
- IDs sind eindeutig, Pflichtfelder sind gesetzt
- Veröffentlichungsdatum plausibel; Tatdatum (falls gesetzt) liegt im erlaubten Fenster
- Meldungstext ist wörtlich im Originaldokument enthalten (kein erzeugter Text)
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector import config  # noqa: E402


def load(table):
    rows = []
    for f in sorted((config.DATA / table).glob("*.json")):
        recs = json.loads(f.read_text(encoding="utf-8"))
        for r in recs:
            if r.get("veroeffentlicht", "")[:7] != f.stem:
                yield ("monat", f"{r.get('id')} liegt in {f.name}, gehört nach {r.get('veroeffentlicht', '')[:7]}")
        rows += recs
    yield ("rows", rows)


def main():
    errors = []
    tables = {}
    for t in ("pressemitteilungen", "meldungen", "social"):
        rows = []
        for kind, val in load(t):
            if kind == "rows":
                rows = val
            else:
                errors.append(val)
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)):
            errors.append(f"{t}: doppelte IDs")
        tables[t] = {r["id"]: r for r in rows}

    pms = tables["pressemitteilungen"]
    today = date.today()
    for m in tables["meldungen"].values():
        pm = pms.get(m.get("pm_id"))
        if not pm:
            errors.append(f"{m['id']}: Originaldokument fehlt")
            continue
        if not m.get("url", "").startswith(config.BASE + "/aktuelles/pressemitteilungen/"):
            errors.append(f"{m['id']}: Quelle ist nicht polizei.bayern.de")
        if m.get("pp") not in config.PRAESIDIEN:
            errors.append(f"{m['id']}: unbekanntes Präsidium {m.get('pp')}")
        v = date.fromisoformat(m["veroeffentlicht"])
        if not (date(2020, 1, 1) <= v <= today + timedelta(days=1)):
            errors.append(f"{m['id']}: Veröffentlichungsdatum unplausibel {v}")
        if m.get("tatdatum"):
            t = date.fromisoformat(m["tatdatum"])
            if not (v - timedelta(days=config.MAX_TAT_VOR_PM_TAGE) <= t <= v + timedelta(days=1)):
                errors.append(f"{m['id']}: Tatdatum {t} außerhalb des Fensters")
        # Wörtlichkeit: jeder Absatz der Meldung muss im Originaltext stehen
        for para in (m.get("text") or "").split("\n"):
            if para and para not in pm["text"]:
                errors.append(f"{m['id']}: Text nicht wörtlich im Original enthalten")
                break

    for s in tables["social"].values():
        if not s.get("url", "").startswith("https://x.com/"):
            errors.append(f"{s['id']}: ungültige Quelle")

    print(f"Geprüft: {len(pms)} Dokumente, {len(tables['meldungen'])} Meldungen, {len(tables['social'])} Posts")
    if errors:
        print(f"✗ {len(errors)} Fehler:")
        for e in errors[:50]:
            print("  -", e)
        return 1
    print("✓ Datenbank konsistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
