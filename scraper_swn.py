#!/usr/bin/env python3
"""PP Schwaben Nord Scraper – Friedberg, Kissing, Mering, Aichach"""

import json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
MAX_PAGES        = 15
SLEEP_SEC        = 0.8
MAX_CONSEC_FAILS = 8
DATA_FILE        = "data/incidents_swn.json"
PP_NAME          = "PP Schwaben Nord"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

# Nur exakte Ortsnamen – KEINE Straßennamen wie "Friedberger Straße"
RELEVANT_PLACES = [
    "Friedberg","Kissing","Mering","Dasing","Aichach","Eurasburg",
    "Merching","Adelzhausen","Schmiechen","Steindorf","Ried",
    "Pöttmes","Rehling","Schiltberg","Todtenweis","Inchenhofen",
]

SKIP_KEYWORDS = [
    "mobile wache","tag der offenen tür","aktionstag","terminhinweis",
    "pressestelle","medienvertreter","verkehrspräventions",
]

# False-Positive Ausschlüsse (Augsburger Straßen)
EXCLUSIONS = ["Friedberger Straße","Friedberger Allee","Friedberger Tor"]

RULES = [
    ("Tötungsdelikt",3,["tötungsdelikt","mord","totschlag","lebensgefahr","tödlich verletzt"]),
    ("Sexualdelikt",3,["vergewaltigung","sexuelle nötigung","missbrauch von kindern"]),
    ("Raub",3,["unter vorhalt einer schusswaffe","unter vorhalt eines messers"]),
    ("Körperverletzung",3,["messer","gestochen","stichverletzung","schwere körperverletzung","notoperation"]),
    ("Einbruch",3,["wohnungseinbruch"]),
    ("Branddelikt",3,["schwere brandstiftung","feuer gelegt","in brand gesetzt"]),
    ("Sexualdelikt",2,["sexuelle belästigung","unsittlich berührt"]),
    ("Raub",2,["raub","beraubt","entrissen","erpressung"]),
    ("Körperverletzung",2,["körperverletzung","schlägerei","geschlagen","getreten","angriff"]),
    ("Einbruch",2,["einbruch","eingebrochen","aufgehebelt","einbruchsversuch"]),
    ("Branddelikt",2,["brandstiftung","brand","flammen"]),
    ("Drogen",2,["kokain","heroin","amphetamin","drogenhandel"]),
    ("Betrug",2,["enkeltrick","schockanruf","falscher polizist"]),
    ("Vermisstenfall",2,["vermisst","abgängig","kind vermisst"]),
    ("Fahndung",2,["öffentlichkeitsfahndung","haftbefehl","festgenommen"]),
    ("Diebstahl",1,["diebstahl","gestohlen","entwendet","fahrraddiebstahl"]),
    ("Drogen",1,["cannabis","marihuana","btm","dealer"]),
    ("Betrug",1,["betrug","betrüger","phishing"]),
    ("Verkehr",1,["verkehrsunfall","unfall","unfallflucht","alkohol am steuer"]),
    ("Vandalismus",1,["sachbeschädigung","graffiti"]),
    ("Fahndung",1,["zeugenaufruf","zeugen gesucht","hinweise erbeten"]),
]

def categorize(text):
    t = text.lower()
    for kat, sev, words in RULES:
        if any(w in t for w in words): return kat, sev
    return "Sonstiges", 1

def is_relevant(text):
    clean = text
    for excl in EXCLUSIONS: clean = clean.replace(excl, "")
    return any(p in clean for p in RELEVANT_PLACES)

def detect_ort(text):
    clean = text
    for excl in EXCLUSIONS: clean = clean.replace(excl, "")
    for place in RELEVANT_PLACES:
        if place in clean: return place
    return "Unbekannt"

def parse_date(text, fallback):
    for m in re.finditer(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text):
        y = int(m[3])
        if 2020 <= y <= 2030:
            try: return datetime(y, int(m[2]), int(m[1]))
            except: pass
    return fallback

def parse_time(text):
    m = re.search(r"(\d{1,2})[:.h](\d{2})\s*Uhr", text)
    return f"{int(m[1]):02d}:{m[2]}" if m else ""

def fetch(url, timeout=8):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status(); r.encoding = "utf-8"; return r.text
        except Exception as e:
            if attempt == 0: time.sleep(1.5)
            else: print(f"  ✗ {url[-50:]} → {e}")
    return None

def get_urls():
    seen, urls = set(), []
    print("  📡 @PolizeiBayern (SWN-Filter)…")
    art_pat = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')
    before_id = None
    for page in range(MAX_PAGES):
        url = "https://t.me/s/PolizeiBayern" + (f"?before={before_id}" if before_id else "")
        html = fetch(url, timeout=20)
        if not html: break
        for m in art_pat.finditer(html):
            if m[0] not in seen: seen.add(m[0]); urls.append(m[0])
        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        if min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.5)
    print(f"  {len(urls)} Links")
    return urls

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    t = title.lower()
    if "schwaben nord" not in t and "nordschwaben" not in t: return []
    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title)
    if not dm: return []
    y = int(dm[3])
    if not (2020 <= y <= 2030): return []
    pm_date = datetime(y, int(dm[2]), int(dm[1]))
    if pm_date < from_date or pm_date > to_date: return []
    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    incidents = []
    # PP SWN nutzt Bold-Tags als Abschnittstrenner: **0701 – Ort**
    for bold in content.find_all(["strong","b"]):
        heading = bold.get_text(" ", strip=True)
        # Nur nummerierte Vorfälle
        nr_m = re.match(r'^(\d{4})\s*[–-]\s*(.+)$', heading)
        if not nr_m: continue
        nr      = nr_m[1]
        ort_raw = nr_m[2].strip()

        # Prävention/Termine überspringen
        full_lower = heading.lower()
        if any(kw in full_lower for kw in SKIP_KEYWORDS): continue

        # Fließtext sammeln
        body_parts = []
        for sib in bold.parent.find_next_siblings():
            next_bold = sib.find(["strong","b"])
            if next_bold and re.match(r'^\d{4}\s*[–-]', next_bold.get_text(strip=True)): break
            body_parts.append(sib.get_text(" ", strip=True))
        # Text im gleichen Absatz nach dem Bold
        parent_text = bold.parent.get_text(" ", strip=True)
        bold_text   = bold.get_text(" ", strip=True)
        after = parent_text[parent_text.find(bold_text)+len(bold_text):].strip()
        body = (after + " " + " ".join(body_parts)).strip()
        if len(body) < 20: continue

        # Relevanzcheck
        if not is_relevant(ort_raw + " " + body): continue

        inc_date = parse_date(body, pm_date)
        ort = detect_ort(ort_raw) if detect_ort(ort_raw) != "Unbekannt" else detect_ort(body)
        kat, sev = categorize(body)

        incidents.append({
            "date": inc_date.strftime("%d.%m.%Y"), "dateSort": inc_date.strftime("%Y-%m-%d"),
            "time": parse_time(body), "nr": nr, "kategorie": kat, "schweregrad": sev,
            "ort": ort, "pp": PP_NAME, "region": PP_NAME,
            "titel": f"{nr} – {ort_raw}"[:120], "volltext": body[:1500], "link": url,
        })
    return incidents

def main():
    to_date   = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)
    print(f"══ {PP_NAME} Scraper · {from_date.date()} → {to_date.date()} ══")
    urls = get_urls()
    existing, existing_links = [], set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_links = {p.get("link","") for p in existing}
        print(f"  Bestehend: {len(existing)} Vorfälle")
    except: print("  Starte frisch")
    new_urls = [u for u in urls if u not in existing_links]
    print(f"  Neu: {len(new_urls)} URLs\n")
    all_incidents = list(existing)
    loaded = 0; consec_fails = 0
    for i, url in enumerate(new_urls):
        art_id = url.split("/")[-2]
        print(f"  [{i+1:3d}/{len(new_urls)}] {art_id}", end=" … ")
        html = fetch(url)
        if not html or len(html) < 300:
            print("leer"); consec_fails += 1
            if consec_fails >= MAX_CONSEC_FAILS: print("  ⚠ Stoppe"); break
            continue
        consec_fails = 0
        incidents = parse_article(html, url, from_date, to_date)
        if incidents: print(f"✓ {len(incidents)}"); all_incidents.extend(incidents); existing_links.add(url); loaded += 1
        else: print("✗")
        time.sleep(SLEEP_SEC)
    all_incidents.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)
    seen, deduped = set(), []
    for inc in all_incidents:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ {loaded} neue Artikel · {len(deduped)} Vorfälle → {DATA_FILE}")

if __name__ == "__main__":
    main()
