#!/usr/bin/env python3
"""
PP München + Umland OSINT – GitHub Actions Scraper
Quellen: @PressePolizeiMuenchen + @PolizeiBayern (Telegram)
Polizeipräsidien: PP München, PP Oberbayern Nord, PP Oberbayern Süd, PP Schwaben Nord
"""

import json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Konfiguration ─────────────────────────────────────────────────────────────
DAYS_BACK  = 500
MAX_ARTS   = 1500
SLEEP_SEC  = 0.4

BASE_URL   = "https://www.polizei.bayern.de"
TG_CHANNELS = ["PressePolizeiMuenchen", "PolizeiBayern"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

# ── Polizeipräsidium-Erkennung aus Seitentitel ────────────────────────────────
# (Titelmuster → (PP-Name, Ortsfilter nötig?))
PP_PATTERNS = [
    ("polizei münchen",  "PP München",          False),
    ("pp münchen",       "PP München",          False),
    ("oberbayern nord",  "PP Oberbayern Nord",  True),
    ("oberbayern süd",   "PP Oberbayern Süd",   True),
    ("schwaben nord",    "PP Schwaben Nord",     True),
    ("nordschwaben",     "PP Schwaben Nord",     True),
]

# Orte die bei PP OBN / OBS / SWN relevant sind
RELEVANT_PLACES = [
    # Würmtal
    "Planegg","Martinsried","Krailling","Gräfelfing","Gauting","Neuried",
    "Germering","Stockdorf","Lochham","Würmtal",
    # Wörthsee / Starnberg
    "Wörthsee","Steinebach","Herrsching","Hechendorf","Walchstadt",
    "Andechs","Seefeld","Starnberg","Inning","Weßling","Pöcking",
    "Tutzing","Feldafing","Berg","Münsing",
    # Friedberg / Aichach
    "Friedberg","Kissing","Mering","Dasing","Aichach","Eurasburg",
    "Merching","Ried","Schmiechen","Steindorf","Adelzhausen",
    "Aichach-Friedberg",
]

# ── Kategorisierung ───────────────────────────────────────────────────────────
RULES = [
    ("Tötungsdelikt",    3, ["tötungsdelikt","mord","totschlag","mordkommission","kommissariat 11","lebensgefahr","tödlich verletzt"]),
    ("Sexualdelikt",     3, ["vergewaltigung","sexuelle nötigung","missbrauch von kindern","sexueller missbrauch"]),
    ("Raub",             3, ["unter vorhalt einer schusswaffe","unter vorhalt eines messers","bewaffneter raubüberfall"]),
    ("Körperverletzung", 3, ["messer","gestochen","stichverletzung","schwere körperverletzung","gefährliche körperverletzung","notoperation"]),
    ("Einbruch",         3, ["wohnungseinbruch"]),
    ("Branddelikt",      3, ["schwere brandstiftung","vorsätzliche brandleg","feuer gelegt","in brand gesetzt"]),
    ("Sexualdelikt",     2, ["sexuelle belästigung","unsittlich berührt","exhibitionistisch"]),
    ("Raub",             2, ["raub","beraubt","entrissen","handtaschenraub","erpressung"]),
    ("Körperverletzung", 2, ["körperverletzung","schlägerei","geschlagen","getreten","faustschlag","bewusstlos","angriff"]),
    ("Einbruch",         2, ["einbruch","einbrecher","eingebrochen","aufgehebelt","aufgebrochen","einbruchsversuch","gewaltsam zutritt"]),
    ("Branddelikt",      2, ["brandstiftung","brand","flammen"]),
    ("Drogen",           2, ["kokain","heroin","amphetamin","crystal","drogenhandel"]),
    ("Betrug",           2, ["enkeltrick","schockanruf","falscher polizist","trickbetrug"]),
    ("Vermisstenfall",   2, ["vermisst","vermisstenfall","abgängig","kind vermisst"]),
    ("Fahndung",         2, ["öffentlichkeitsfahndung","haftbefehl","festgenommen"]),
    ("Verkehr",          2, ["rettungshubschrauber","kollision mit","zusammenstoß mit"]),
    ("Diebstahl",        1, ["diebstahl","gestohlen","entwendet","taschendiebstahl","ladendiebstahl","fahrraddiebstahl","kfz-diebstahl"]),
    ("Drogen",           1, ["cannabis","marihuana","btm","betäubungsmittel","dealer"]),
    ("Betrug",           1, ["betrug","betrüger","phishing","cybercrime"]),
    ("Verkehr",          1, ["verkehrsunfall","unfall","auffahrunfall","unfallflucht","fahrerflucht","alkohol am steuer","überladung","stürzte","rotlicht"]),
    ("Vandalismus",      1, ["sachbeschädigung","graffiti","beschmiert","schmähschrift"]),
    ("Fahndung",         1, ["zeugenaufruf","zeugen gesucht","hinweise erbeten"]),
    ("Prävention",       1, ["prävention","warnt","warnung","hinweis der polizei","fahrradcodier","terminhinweis"]),
]

ORT_MAP = [
    # München Stadtteile
    ("Altstadt-Lehel","Altstadt-Lehel"),("Altstadt","Altstadt-Lehel"),("Lehel","Altstadt-Lehel"),
    ("Maxvorstadt","Maxvorstadt"),("Schwabing-West","Schwabing-West"),("Schwabing","Schwabing"),
    ("Neuhausen-Nymphenburg","Neuhausen-Nymphenburg"),("Neuhausen","Neuhausen-Nymphenburg"),("Nymphenburg","Neuhausen-Nymphenburg"),
    ("Sendling","Sendling"),("Au-Haidhausen","Au-Haidhausen"),("Haidhausen","Au-Haidhausen"),
    ("Bogenhausen","Bogenhausen"),("Pasing-Obermenzing","Pasing-Obermenzing"),
    ("Pasing","Pasing-Obermenzing"),("Obermenzing","Pasing-Obermenzing"),
    ("Obergiesing","Obergiesing"),("Untergiesing","Untergiesing"),("Harlaching","Harlaching"),
    ("Giesing","Giesing"),("Moosach","Moosach"),
    ("Ramersdorf-Perlach","Ramersdorf-Perlach"),("Ramersdorf","Ramersdorf-Perlach"),("Perlach","Ramersdorf-Perlach"),
    ("Milbertshofen","Milbertshofen"),("Freimann","Milbertshofen"),
    ("Trudering","Trudering"),("Hadern","Hadern"),("Laim","Laim"),("Berg am Laim","Berg am Laim"),
    ("Feldmoching-Hasenbergl","Feldmoching-Hasenbergl"),("Feldmoching","Feldmoching-Hasenbergl"),("Hasenbergl","Feldmoching-Hasenbergl"),
    ("Schwanthalerhöhe","Schwanthalerhöhe"),("Thalkirchen","Thalkirchen"),
    ("Ludwigsvorstadt","Ludwigsvorstadt"),("Isarvorstadt","Isarvorstadt"),
    ("Allach-Untermenzing","Allach-Untermenzing"),("Allach","Allach-Untermenzing"),
    ("Hauptbahnhof","Stadtmitte"),("Marienplatz","Stadtmitte"),("Stachus","Stadtmitte"),
    ("Karlsplatz","Stadtmitte"),("Innenstadt","Stadtmitte"),("Stadtmitte","Stadtmitte"),
    # Würmtal
    ("Planegg","Planegg"),("Martinsried","Martinsried"),("Krailling","Krailling"),
    ("Gräfelfing","Gräfelfing"),("Gauting","Gauting"),("Neuried","Neuried"),
    ("Germering","Germering"),("Stockdorf","Stockdorf"),("Lochham","Lochham"),
    # Wörthsee / Starnberg
    ("Wörthsee","Wörthsee"),("Steinebach","Steinebach"),("Herrsching","Herrsching"),
    ("Hechendorf","Hechendorf"),("Walchstadt","Walchstadt"),("Andechs","Andechs"),
    ("Seefeld","Seefeld"),("Starnberg","Starnberg"),("Inning","Inning"),("Weßling","Weßling"),
    ("Tutzing","Tutzing"),("Feldafing","Feldafing"),("Pöcking","Pöcking"),
    # Friedberg
    ("Friedberg","Friedberg"),("Kissing","Kissing"),("Mering","Mering"),
    ("Dasing","Dasing"),("Aichach","Aichach"),("Eurasburg","Eurasburg"),("Merching","Merching"),
]


def detect_pp(title_text):
    t = title_text.lower()
    for pattern, pp_name, needs_filter in PP_PATTERNS:
        if pattern in t:
            return pp_name, needs_filter
    return None, False


def is_relevant_place(text):
    return any(p in text for p in RELEVANT_PLACES)


def categorize(text):
    t = text.lower()
    for kat, sev, words in RULES:
        if any(w in t for w in words): return kat, sev
    return "Sonstiges", 1


def detect_ort(text):
    for term, canonical in ORT_MAP:
        if term in text: return canonical
    return "Unbekannt"


def parse_date(text, fallback):
    """Parst erstes gültiges Datum (2020-2030) aus Text."""
    for m in re.finditer(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text):
        y = int(m[3])
        if 2020 <= y <= 2030:
            try: return datetime(y, int(m[2]), int(m[1]))
            except: pass
    return fallback


def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status(); r.encoding = "utf-8"; return r.text
    except Exception as e:
        print(f"  ✗ {url[-60:]} → {e}"); return None


def get_urls_from_telegram(channel):
    """Liest Telegram-Kanal seitenweise, sammelt alle polizei.bayern.de Links."""
    print(f"\n  📡 @{channel}…")
    art_pat = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')
    seen, urls, before_id = set(), [], None

    for page in range(100):
        url = f"https://t.me/s/{channel}" + (f"?before={before_id}" if before_id else "")
        html = fetch(url, timeout=25)
        if not html: break

        new = 0
        for m in art_pat.finditer(html):
            if m[0] not in seen:
                seen.add(m[0]); urls.append(m[0]); new += 1

        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        print(f"    Seite {page+1}: {new} neue Links (bis Post #{min_id})")
        if len(urls) >= MAX_ARTS or min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.6)

    print(f"    @{channel}: {len(urls)} Links gesamt")
    return urls


def parse_article(html, url, from_date, to_date):
    """Parst eine Pressemitteilung – unterstützt verschiedene PP-Formate."""
    soup = BeautifulSoup(html, "html.parser")

    # ── PP aus Seitentitel ────────────────────────────────────────────────────
    title_text = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    pp_name, needs_filter = detect_pp(title_text)
    if not pp_name:
        return []  # Nicht relevantes PP

    # ── Datum der Pressemitteilung ────────────────────────────────────────────
    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title_text)
    if not dm: return []
    y = int(dm[3])
    if not (2020 <= y <= 2030): return []
    pm_date = datetime(y, int(dm[2]), int(dm[1]))

    if pm_date < from_date or pm_date > to_date:
        return []

    # ── DOM bereinigen ────────────────────────────────────────────────────────
    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    full_text = content.get_text(" ", strip=True)

    # Fußzeile abschneiden für Ortsfilterung
    cutoff = re.search(r'Rückfragen bitte|Pressestelle\b|Tel\.:\s*\d', full_text)
    text_for_filter = full_text[:cutoff.start()] if cutoff else full_text

    # ── Ortsfilter für andere PP ──────────────────────────────────────────────
    if needs_filter and not is_relevant_place(text_for_filter):
        return []

    # ── Vorfälle aus h3-Überschriften extrahieren ─────────────────────────────
    incidents = []
    sections  = content.find_all("h3")

    if not sections:
        # Kein h3-Format (z.B. PP OBN schreibt manchmal anders)
        # Versuche Vorfälle per Absatz zu trennen
        paragraphs = [p.get_text(" ", strip=True) for p in content.find_all("p") if len(p.get_text(strip=True)) > 50]
        if not paragraphs:
            paragraphs = [full_text]

        for body in paragraphs[:10]:
            if needs_filter and not is_relevant_place(body):
                continue
            inc_date = parse_date(body, pm_date)
            tm = re.search(r"(\d{1,2})[:.h](\d{2})\s*Uhr", body)
            kat, sev = categorize(body)
            ort = detect_ort(body)
            incidents.append(_make(
                inc_date, f"{int(tm[1]):02d}:{tm[2]}" if tm else "",
                "", kat, sev, ort, body[:120], body[:1500], url, pp_name
            ))
        return incidents

    # Standard-Format mit h3 (PP München + die meisten anderen PP)
    for h in sections:
        heading = h.get_text(" ", strip=True)
        num_m   = re.match(r"^(\d+)\.\s+", heading)
        nr      = num_m[1] if num_m else ""
        titel   = re.sub(r"^\d+\.\s+", "", heading).strip()

        # Ort aus Titel (nach "–")
        ort_m   = re.search(r"–\s*(.+)$", titel)
        ort_raw = ort_m[1].strip() if ort_m else ""
        ort     = detect_ort(ort_raw) if ort_raw else "Unbekannt"

        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h3","h2","hr"): break
            parts.append(sib.get_text(" ", strip=True))
        body = " ".join(parts).strip()
        if len(body) < 30: continue

        vorfall_text = titel + " " + body

        # Für andere PP: Ortsfilter auf Vorfall-Ebene
        if needs_filter and not is_relevant_place(vorfall_text):
            continue

        inc_date = parse_date(body, pm_date)
        tm = re.search(r"(\d{1,2})[:.h](\d{2})\s*Uhr", body)
        kat, sev = categorize(vorfall_text)
        if ort == "Unbekannt": ort = detect_ort(body)

        incidents.append(_make(
            inc_date, f"{int(tm[1]):02d}:{tm[2]}" if tm else "",
            nr, kat, sev, ort, titel[:120], body[:1500], url, pp_name
        ))

    return incidents


def _make(dt, time_str, nr, kat, sev, ort, titel, volltext, link, pp):
    return {
        "date":        dt.strftime("%d.%m.%Y"),
        "dateSort":    dt.strftime("%Y-%m-%d"),
        "time":        time_str,
        "nr":          nr,
        "kategorie":   kat,
        "schweregrad": sev,
        "ort":         ort,
        "pp":          pp,       # Polizeipräsidium (neu – ersetzt "region")
        "region":      pp,       # Rückwärtskompatibilität
        "titel":       titel,
        "volltext":    volltext,
        "link":        link,
    }


def main():
    to_date   = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)

    print(f"═══════════════════════════════════════════════════")
    print(f"  PP München + Umland OSINT Scraper")
    print(f"  Zeitraum: {from_date.date()} → {to_date.date()}")
    print(f"  PP: München · OBN (Planegg/Würmtal/Starnberg) · SWN (Friedberg)")
    print(f"═══════════════════════════════════════════════════")

    # 1. URLs aus Telegram
    all_urls = set()
    for ch in TG_CHANNELS:
        all_urls.update(get_urls_from_telegram(ch))
    urls = sorted(all_urls)
    print(f"\n  Gesamt: {len(urls)} einzigartige Artikel-URLs\n")

    # 2. Bestehende Daten laden (inkrementell)
    existing_data, existing_links = [], set()
    try:
        with open("data/incidents.json", "r", encoding="utf-8") as f:
            existing_data  = json.load(f)
            existing_links = {p.get("link","") for p in existing_data}
            print(f"  Bestehende Daten: {len(existing_data)} Vorfälle")
    except: print("  Starte frisch")

    all_incidents = list(existing_data)
    loaded = 0

    # 3. Artikel abrufen
    for i, url in enumerate(urls):
        if url in existing_links: continue

        art_id = url.split("/")[-2]
        print(f"  [{i+1:4d}/{len(urls)}] {art_id}", end=" … ")
        html = fetch(url)
        if not html or len(html) < 300: print("leer"); continue

        incidents = parse_article(html, url, from_date, to_date)
        if incidents:
            pps = set(inc["pp"] for inc in incidents)
            print(f"✓ {len(incidents)} [{', '.join(pps)}]")
            all_incidents.extend(incidents)
            existing_links.add(url)
            loaded += 1
        else:
            print("✗")

        time.sleep(SLEEP_SEC)

    # 4. Sortieren & Deduplizieren
    all_incidents.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)
    seen, deduped = set(), []
    for inc in all_incidents:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)

    from collections import Counter
    pp_counts = Counter(inc.get("pp","?") for inc in deduped)
    print(f"\n  ✅ {loaded} neue Artikel · {len(deduped)} Vorfälle gesamt")
    for pp, cnt in sorted(pp_counts.items()): print(f"     {pp}: {cnt}")

    # 5. Speichern
    Path("data").mkdir(exist_ok=True)
    with open("data/incidents.json","w",encoding="utf-8") as f:
        json.dump(deduped,f,ensure_ascii=False,indent=2)

    meta = {
        "updated":     datetime.now().strftime("%d.%m.%Y %H:%M"),
        "updated_iso": datetime.now().isoformat(),
        "from_date":   from_date.strftime("%Y-%m-%d"),
        "to_date":     to_date.strftime("%Y-%m-%d"),
        "articles":    loaded,
        "incidents":   len(deduped),
        "pp_counts":   dict(pp_counts),
    }
    with open("data/meta.json","w",encoding="utf-8") as f:
        json.dump(meta,f,ensure_ascii=False,indent=2)

    print(f"     → {os.path.getsize('data/incidents.json')//1024} KB")


if __name__ == "__main__":
    main()
