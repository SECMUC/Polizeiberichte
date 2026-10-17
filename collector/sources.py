"""Quellen: polizei.bayern.de (Übersicht + Pressearchiv), Telegram, X (optional)."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from . import config

PM_ID = re.compile(r"/aktuelles/pressemitteilungen/(\d{5,7})/index\.html")


def _ts_to_iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return None


def _norm_id(x: str) -> str:
    return f"{int(x):06d}"


# ---------------------------------------------------------------- polizei.bayern.de
def discover_listing(http):
    """Seite 'Neueste Pressemeldungen': eingebettete Liste der letzten ca. 14 Tage."""
    r = http.get(config.LISTING_URL)
    if not r:
        raise RuntimeError("Übersichtsseite nicht erreichbar")
    r.encoding = "utf-8"
    html = r.text
    i = html.find("window.montagedata")
    if i < 0:
        raise RuntimeError("Übersichtsseite: Datenblock 'montagedata' fehlt (Seitenaufbau geändert?)")
    data, _ = json.JSONDecoder().raw_decode(html[html.index("[", i):])
    out = []
    for item in data:
        pp = config.OG2K_TO_PP.get((item.get("organization") or {}).get("og2k"))
        m = PM_ID.search(item.get("href", ""))
        if pp and m:
            out.append({"id": _norm_id(m[1]), "pp": pp, "ts": _ts_to_iso(item.get("date")),
                        "titel": item.get("title")})
    return out, len(data)


def _archive_query(http, pp_name, d_from: date, d_to: date):
    q = {"queryStr": False, "datefr": d_from.strftime("%d.%m.%Y"),
         "dateto": d_to.strftime("%d.%m.%Y"), "author": pp_name}
    r = http.post(config.SEARCH_URL, data=json.dumps({"type": "presse", "q": json.dumps(q)}),
                  headers={"Content-Type": "application/json", "Accept": "*/*",
                           "Origin": config.BASE, "Referer": config.SEARCH_REFERER})
    if not r:
        raise RuntimeError(f"Pressearchiv: keine Antwort für {pp_name} {d_from}–{d_to}")
    hits = r.json().get("hits", {})
    total = (hits.get("total") or {}).get("value", 0)
    return hits.get("hits", []), total


def discover_archive(http, pp, d_from: date, d_to: date):
    """Pressearchiv-Suche je Präsidium. Fenster werden geteilt, falls Treffer gekappt sind.
    Liefert (Treffer, nicht abfragbare Zeitfenster)."""
    pp_name = config.PRAESIDIEN[pp]["name"]
    out, windows, failed = [], [(d_from, d_to)], []
    while windows:
        a, b = windows.pop()
        try:
            hits, total = _archive_query(http, pp_name, a, b)
        except RuntimeError:
            failed.append((a, b))
            continue
        if len(hits) < total:
            if a == b:
                print(f"    ⚠ Archiv {pp} {a}: {len(hits)}/{total} Treffer (nicht teilbar)")
            else:
                mid = a + (b - a) // 2
                windows += [(a, mid), (mid + timedelta(days=1), b)]
                continue
        for h in hits:
            src = h.get("_source", {})
            if src.get("creating_organization") != pp_name:
                continue
            m = PM_ID.search((src.get("directory") or "") + "/" + (src.get("filename") or "index.html"))
            if m:
                out.append({"id": _norm_id(m[1]), "pp": pp, "ts": _ts_to_iso(src.get("sort_date_js")),
                            "titel": src.get("title")})
    return out, failed


def fetch_article(http, pm_id):
    r = http.get(config.ARTICLE_URL.format(id=pm_id))
    if not r:
        return None
    r.encoding = "utf-8"
    return r.text


# ---------------------------------------------------------------- Telegram
def discover_telegram(http, channel, max_pages=3):
    """Öffentliche Vorschau t.me/s/<kanal>: verlinkte Pressemitteilungen."""
    ids, before = {}, None
    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        r = http.get(url)
        if not r:
            raise RuntimeError(f"Telegram @{channel} nicht erreichbar")
        soup = BeautifulSoup(r.text, "html.parser")
        msgs = soup.select(".tgme_widget_message")
        if not msgs:
            break
        for msg in msgs:
            t = msg.find("time")
            for a in msg.find_all("a", href=True):
                m = PM_ID.search(a["href"])
                if m:
                    ids.setdefault(_norm_id(m[1]), t.get("datetime") if t else None)
        post_ids = [int(x.split("/")[-1]) for x in (m.get("data-post", "") for m in msgs) if x]
        if not post_ids or min(post_ids) <= 1:
            break
        before = min(post_ids)
    return [{"id": k, "ts": v} for k, v in ids.items()]


# ---------------------------------------------------------------- X (optional)
def x_enabled():
    return bool(os.environ.get("X_BEARER_TOKEN"))


def fetch_x(http, username, since_id=None):
    """Posts eines offiziellen Accounts über die X-API v2 (kostenpflichtig, pay-per-use)."""
    token = os.environ["X_BEARER_TOKEN"]
    hdr = {"Authorization": f"Bearer {token}"}
    r = http.get(f"https://api.x.com/2/users/by/username/{username}", headers=hdr, retries=1)
    if not r:
        raise RuntimeError(f"X: Account @{username} nicht abrufbar")
    uid = r.json()["data"]["id"]
    params = {"max_results": min(100, max(5, config.X_MAX_POSTS_PER_ACCOUNT)),
              "tweet.fields": "created_at,entities,referenced_tweets",
              "exclude": "replies"}
    if since_id:
        params["since_id"] = since_id
    r = http.get(f"https://api.x.com/2/users/{uid}/tweets", headers=hdr, params=params, retries=1)
    if not r:
        raise RuntimeError(f"X: Posts von @{username} nicht abrufbar")
    out = []
    for tw in r.json().get("data", []):
        links = [u.get("expanded_url") for u in (tw.get("entities") or {}).get("urls", []) if u.get("expanded_url")]
        out.append({"id": f"x-{tw['id']}", "post_id": tw["id"], "account": username,
                    "erstellt": tw.get("created_at"), "text": tw.get("text", ""),
                    "links": links, "url": f"https://x.com/{username}/status/{tw['id']}",
                    "ist_repost": any(rt.get("type") == "retweeted" for rt in tw.get("referenced_tweets", []) or [])})
    return out
