"""Datenhaltung als Textdateien im Repo (eine JSON-Datei pro Monat und Tabelle).

Tabellen
  data/pressemitteilungen/YYYY-MM.json  Originaldokumente (Volltext, Hash, Herkunft)
  data/meldungen/YYYY-MM.json           Einzelmeldungen, aus den Dokumenten zerlegt
  data/social/YYYY-MM.json              Posts offizieller Social-Media-Accounts
  data/state/queue.json                 entdeckte, noch nicht abgerufene Dokumente
  data/index.json                       Übersicht für Dashboard und Auswertung
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import config

TABLES = ("pressemitteilungen", "meldungen", "social")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _month(rec):
    return (rec.get("veroeffentlicht") or rec.get("erstellt") or "0000-00")[:7]


def _sort_key(rec):
    return (rec.get("veroeffentlicht") or rec.get("erstellt") or "", rec.get("id", ""))


class Store:
    def __init__(self):
        self.rows = {t: {} for t in TABLES}
        self.dirty = {t: set() for t in TABLES}
        for t in TABLES:
            d = config.DATA / t
            if d.exists():
                for f in sorted(d.glob("*.json")):
                    for rec in json.loads(f.read_text(encoding="utf-8")):
                        self.rows[t][rec["id"]] = rec
        qf = config.DATA / "state" / "queue.json"
        self.queue = json.loads(qf.read_text(encoding="utf-8")) if qf.exists() else {}

    # ---------- Zugriff ----------
    def has(self, table, rid):
        return rid in self.rows[table]

    def get(self, table, rid):
        return self.rows[table].get(rid)

    def upsert(self, table, rec):
        old = self.rows[table].get(rec["id"])
        if old is not None and old != rec:
            self.dirty[table].add(_month(old))
        if old != rec:
            self.rows[table][rec["id"]] = rec
            self.dirty[table].add(_month(rec))
            return True
        return False

    def delete_where(self, table, pred):
        for rid in [r for r, rec in self.rows[table].items() if pred(rec)]:
            self.dirty[table].add(_month(self.rows[table][rid]))
            del self.rows[table][rid]

    # ---------- Warteschlange ----------
    def enqueue(self, pm_id, pp, via, published=None, titel=None):
        if pm_id in self.rows["pressemitteilungen"]:
            pm = self.rows["pressemitteilungen"][pm_id]
            if via not in pm.get("quellen", []):
                pm.setdefault("quellen", []).append(via)
                self.dirty["pressemitteilungen"].add(_month(pm))
            return False
        q = self.queue.setdefault(pm_id, {"pp": pp, "quellen": [], "versuche": 0})
        if via not in q["quellen"]:
            q["quellen"].append(via)
        if published and not q.get("veroeffentlicht_ts"):
            q["veroeffentlicht_ts"] = published
        if titel and not q.get("titel"):
            q["titel"] = titel
        if pp and not q.get("pp"):
            q["pp"] = pp
        return True

    # ---------- Speichern ----------
    def save(self, run_info: dict):
        for t in TABLES:
            if not self.dirty[t]:
                continue
            by_month = defaultdict(list)
            for rec in self.rows[t].values():
                by_month[_month(rec)].append(rec)
            d = config.DATA / t
            d.mkdir(parents=True, exist_ok=True)
            for m in self.dirty[t]:
                f = d / f"{m}.json"
                recs = sorted(by_month.get(m, []), key=_sort_key, reverse=True)
                if recs:
                    f.write_text(json.dumps(recs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                elif f.exists():
                    f.unlink()
        qd = config.DATA / "state"
        qd.mkdir(parents=True, exist_ok=True)
        (qd / "queue.json").write_text(
            json.dumps(dict(sorted(self.queue.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self._write_index(run_info)

    def _write_index(self, run_info):
        months = defaultdict(lambda: {"meldungen": 0, "pressemitteilungen": 0, "social": 0, "pp": Counter()})
        for t in TABLES:
            for rec in self.rows[t].values():
                m = months[_month(rec)]
                m[t] += 1
                if t == "meldungen":
                    m["pp"][rec.get("pp") or "?"] += 1
        mel = self.rows["meldungen"].values()
        idx = {
            "schema": 2,
            "aktualisiert": now_iso(),
            "zeitraum": {
                "von": min((r["veroeffentlicht"] for r in mel), default=None),
                "bis": max((r["veroeffentlicht"] for r in mel), default=None),
            },
            "summen": {t: len(self.rows[t]) for t in TABLES} | {"warteschlange": len(self.queue)},
            "praesidien": {k: {"name": v["name"], "kurz": v["kurz"], "fokus": v["fokus"]}
                           for k, v in config.PRAESIDIEN.items()},
            "monate": [
                {"monat": k, "datei_meldungen": f"meldungen/{k}.json" if v["meldungen"] else None,
                 "datei_social": f"social/{k}.json" if v["social"] else None,
                 "meldungen": v["meldungen"], "pressemitteilungen": v["pressemitteilungen"],
                 "social": v["social"], "pp": dict(v["pp"])}
                for k, v in sorted(months.items(), reverse=True)
            ],
            "letzter_lauf": run_info,
        }
        (config.DATA / "index.json").write_text(
            json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
