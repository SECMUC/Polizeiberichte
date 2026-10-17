"""Polizei-Collector – Einstiegspunkt.

  python -m collector                       # täglicher Lauf
  python -m collector --backfill-from 2025-01-01 --budget-min 300
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

from . import config, sources
from .classify import categorize
from .net import BudgetExceeded, Http
from .parse import ParseError, parse_article
from .store import Store, now_iso

MAX_VERSUCHE = 5


def month_windows(d_from: date, d_to: date):
    cur = d_from
    while cur <= d_to:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(nxt - timedelta(days=1), d_to)
        cur = nxt


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-min", type=float, default=config.DEFAULT_BUDGET_MIN)
    ap.add_argument("--backfill-from", type=date.fromisoformat, default=None)
    ap.add_argument("--max-fetch", type=int, default=100000)
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    http = Http(args.budget_min)
    store = Store()
    today = date.today()
    status, fehler = {}, []
    stats = {"neu_pm": 0, "neu_meldungen": 0, "aktualisiert_pm": 0, "abgerufen": 0, "social_neu": 0}

    def ok(name, info):
        status[name] = {"ok": True, **info}
        print(f"  ✓ {name}: {info}")

    def fail(name, e):
        status[name] = {"ok": False, "fehler": str(e)[:300]}
        fehler.append(f"{name}: {e}")
        print(f"  ✗ {name}: {e}")

    print(f"══ Polizei-Collector · {now_iso()} · Budget {args.budget_min:.0f} min ══")
    stopped_by_budget = False
    try:
        # ---------------- 1. Entdecken ----------------
        print("\n[1] Neue Pressemitteilungen entdecken")
        try:
            items, total = sources.discover_listing(http)
            n = sum(store.enqueue(i["id"], i["pp"], "uebersicht", i["ts"], i["titel"]) for i in items)
            ok("uebersicht", {"eintraege_gesamt": total, "relevant": len(items), "neu": n})
        except BudgetExceeded:
            raise
        except Exception as e:
            fail("uebersicht", e)

        d_from = args.backfill_from or (today - timedelta(days=config.DAILY_LOOKBACK_DAYS))
        pending = {pp: list(month_windows(d_from, today)) for pp in config.PRAESIDIEN}
        found_by_pp = {pp: [] for pp in config.PRAESIDIEN}
        for runde in range(3):  # fehlgeschlagene Zeitfenster später erneut versuchen
            if not any(pending.values()):
                break
            if runde:
                print(f"    … Wiederholung Pressearchiv (Runde {runde + 1}) nach Pause")
                time.sleep(60)
            for pp, wins in pending.items():
                still = []
                for a, b in wins:
                    items, failed = sources.discover_archive(http, pp, a, b)
                    found_by_pp[pp] += items
                    still += failed
                pending[pp] = still
        for pp in config.PRAESIDIEN:
            name = f"archiv:{config.PRAESIDIEN[pp]['kurz']}"
            found = found_by_pp[pp]
            n = sum(store.enqueue(i["id"], pp, "archiv", i["ts"], i["titel"]) for i in found)
            info = {"treffer": len(found), "neu": n, "ab": d_from.isoformat()}
            if pending[pp]:
                missing = [f"{a}–{b}" for a, b in pending[pp]]
                if not found:
                    fail(name, "Pressearchiv nicht erreichbar: " + ", ".join(missing[:4]))
                    continue
                info["fehlende_zeitraeume"] = missing
                fehler.append(f"{name}: Zeiträume nicht abgefragt: {', '.join(missing[:6])}")
            ok(name, info)

        for channel, pp in config.TELEGRAM_CHANNELS.items():
            name = f"telegram:{channel}"
            try:
                pages = 30 if args.backfill_from else 3
                found = sources.discover_telegram(http, channel, max_pages=pages)
                n = sum(store.enqueue(i["id"], None, "telegram", i["ts"]) for i in found)
                ok(name, {"links": len(found), "neu": n})
            except BudgetExceeded:
                raise
            except Exception as e:
                fail(name, e)

        if not any(v.get("ok") for v in status.values()):
            raise RuntimeError("Keine Quelle erreichbar")

        # ---------------- 2. Abrufen & zerlegen ----------------
        refresh_cut = datetime.now(timezone.utc) - timedelta(hours=config.REFRESH_RECENT_HOURS)
        recent = [pm for pm in store.rows["pressemitteilungen"].values()
                  if pm["veroeffentlicht"] >= (today - timedelta(days=2)).isoformat()
                  and pm.get("zuletzt_geprueft", "") < (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()]
        todo = sorted((k for k, v in store.queue.items() if v.get("versuche", 0) < MAX_VERSUCHE), reverse=True)
        todo += sorted((pm["id"] for pm in recent), reverse=True)
        print(f"\n[2] Abruf: {len(todo)} Dokumente (Warteschlange {len(store.queue)}, Nachprüfung {len(recent)})")

        for n_done, pm_id in enumerate(todo[:args.max_fetch], 1):
            http.check_budget(reserve_sec=90)
            q = store.queue.get(pm_id)
            existing = store.get("pressemitteilungen", pm_id)
            http.last_error = None
            html = sources.fetch_article(http, pm_id)
            stats["abgerufen"] += 1
            if html is None:
                if q is not None:
                    q["versuche"] = q.get("versuche", 0) + 1
                    q["letzter_fehler"] = http.last_error or "HTTP 404 (nicht vorhanden)"
                continue
            try:
                pm, meldungen = parse_article(html, pm_id, config.ARTICLE_URL.format(id=pm_id))
            except ParseError as e:
                if q is not None:
                    q["versuche"] = q.get("versuche", 0) + 1
                    q["letzter_fehler"] = str(e)
                fehler.append(f"Parser {pm_id}: {e}")
                continue
            if pm["pp"] is None:
                # Dokument eines nicht erfassten Präsidiums (z. B. über Telegram verlinkt)
                store.queue.pop(pm_id, None)
                continue

            ts_now = now_iso()
            if existing and existing["sha256"] == pm["sha256"]:
                existing["zuletzt_geprueft"] = ts_now
                store.dirty["pressemitteilungen"].add(existing["veroeffentlicht"][:7])
                continue

            pm["quellen"] = sorted(set((existing or {}).get("quellen", []) + (q or {}).get("quellen", [])))
            pm["zeitstempel_quelle"] = (existing or {}).get("zeitstempel_quelle") or (q or {}).get("veroeffentlicht_ts")
            pm["erstmals_erfasst"] = (existing or {}).get("erstmals_erfasst") or ts_now
            pm["zuletzt_geprueft"] = ts_now
            pm["revision"] = (existing or {}).get("revision", 0) + (1 if existing else 0)
            store.upsert("pressemitteilungen", pm)
            store.delete_where("meldungen", lambda r, i=pm_id: r["pm_id"] == i)
            for m in meldungen:
                m["kategorie"] = categorize(m["titel"], m["text"])
                m["erfasst"] = pm["erstmals_erfasst"]
                store.upsert("meldungen", m)
            store.queue.pop(pm_id, None)
            if existing:
                stats["aktualisiert_pm"] += 1
            else:
                stats["neu_pm"] += 1
                stats["neu_meldungen"] += len(meldungen)
            if n_done % 25 == 0:
                print(f"    … {n_done}/{len(todo)} abgerufen, {stats['neu_meldungen']} neue Meldungen")
                if n_done % 200 == 0:
                    store.save({"zwischenstand": True, "zeit": now_iso()})

        # ---------------- 3. Social Media (optional) ----------------
        if sources.x_enabled():
            print("\n[3] X-Accounts")
            for account, pp in config.X_ACCOUNTS.items():
                name = f"x:{account}"
                try:
                    since = max((r["post_id"] for r in store.rows["social"].values()
                                 if r.get("account") == account), default=None, key=int)
                    posts = sources.fetch_x(http, account, since)
                    for p in posts:
                        p["pp"] = pp
                        p["veroeffentlicht"] = (p.get("erstellt") or "")[:10]
                        p["kategorie"] = categorize("", p["text"])
                        p["erfasst"] = now_iso()
                        if store.upsert("social", p):
                            stats["social_neu"] += 1
                    ok(name, {"neu": len(posts)})
                except BudgetExceeded:
                    raise
                except Exception as e:
                    fail(name, e)
        else:
            status["x"] = {"ok": None, "hinweis": "nicht aktiv (kein X_BEARER_TOKEN hinterlegt)"}

    except BudgetExceeded:
        stopped_by_budget = True
        print("\n  ⏱ Zeitbudget erreicht – Rest folgt im nächsten Lauf")
    except RuntimeError as e:
        fail("lauf", e)

    run_info = {
        "zeit": now_iso(),
        "dauer_sek": round(time.monotonic() - t0),
        "modus": f"backfill ab {args.backfill_from}" if args.backfill_from else "täglich",
        "budget_erreicht": stopped_by_budget,
        "quellen": status,
        "statistik": stats | {"http_anfragen": http.requests, "http_fehler": http.errors,
                              "fehlerarten": http.error_kinds},
        "warteschlange": len(store.queue),
        "fehler": fehler[:50],
    }
    store.save(run_info)
    print(f"\n══ Fertig: {stats} · Warteschlange {len(store.queue)} · {len(fehler)} Fehler ══")
    if "lauf" in status:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
