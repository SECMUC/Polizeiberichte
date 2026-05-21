#!/usr/bin/env python3
"""
Merge-Script – fasst alle PP-Datensätze zu incidents.json zusammen.
Läuft nach allen Scrapern.
"""

import json, os
from datetime import datetime
from pathlib import Path
from collections import Counter

DATA_FILES = [
    "data/incidents_muenchen.json",
    "data/incidents_obn.json",
    "data/incidents_obs.json",
    "data/incidents_swn.json",
]

def main():
    print("══ Merge ══")
    all_incidents = []

    for f in DATA_FILES:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            print(f"  {f}: {len(data)} Vorfälle")
            all_incidents.extend(data)
        except FileNotFoundError:
            print(f"  {f}: nicht gefunden (übersprungen)")
        except Exception as e:
            print(f"  {f}: Fehler – {e}")

    # Sortieren
    all_incidents.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)

    # Deduplizieren
    seen, deduped = set(), []
    for inc in all_incidents:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)

    pp_counts = Counter(inc.get("pp","?") for inc in deduped)

    print(f"\n  Gesamt: {len(deduped)} Vorfälle")
    for pp, cnt in sorted(pp_counts.items(), key=lambda x:-x[1]):
        print(f"    {pp}: {cnt}")

    Path("data").mkdir(exist_ok=True)
    with open("data/incidents.json","w",encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    meta = {
        "updated":     datetime.now().strftime("%d.%m.%Y %H:%M"),
        "updated_iso": datetime.now().isoformat(),
        "from_date":   min((p.get("dateSort","9") for p in deduped if p.get("dateSort","")), default=""),
        "to_date":     max((p.get("dateSort","0") for p in deduped if p.get("dateSort","")), default=""),
        "incidents":   len(deduped),
        "pp_counts":   dict(pp_counts),
    }
    with open("data/meta.json","w",encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    size = os.path.getsize("data/incidents.json") // 1024
    print(f"\n  ✅ data/incidents.json ({size} KB) – Web-App aktualisiert")

if __name__ == "__main__":
    main()
