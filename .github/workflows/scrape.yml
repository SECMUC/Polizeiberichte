#!/usr/bin/env python3
"""PP Oberbayern Süd Scraper – Wörthsee, Steinebach, Starnberg"""

import json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
MAX_PAGES        = 15
SLEEP_SEC        = 0.8
MAX_CONSEC_FAILS = 8
DATA_FILE        = "data/incidents_obs.json"
PP_NAME          = "PP Oberbayern Süd"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

RELEVANT_PLACES = [
    "Wörthsee","Steinebach","Herrsching","Hechendorf","Walchstadt",
    "Andechs","Seefeld","Inning","Weßling","Pöcking","Tutzing",
    "Feldafing","Berg","Münsing","Bernried","Seeshaupt",
    "Bad Tölz","Wolfratshausen","Geretsried","Miesbach","Rosenheim",
]

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
    ("Verkehr",1,["verkehrsunfall","unfall","unfallflucht","fahrerflucht","alkohol am steuer"]),
    ("Vandalismus",1,["sachbeschädigung","graffiti"]),
    ("Fahndung",1,["zeugenaufruf","zeugen gesucht","hinweise erbeten"]),
]

def categorize(text):
    t = text.lower()
    for kat, sev, words in RULES:
        if any(w in t for w in words): return kat, sev
    return "Sonstiges", 1

def is_relevant(text):
    return any(p in text for p in RELEVANT_PLACES)

def detect_ort(text):
    for place in RELEVANT_PLACES:
        if place in text: return place
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
    print("  📡 @PolizeiBayern (OBS-Filter)…")
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
    tl = title.lower()
    if "oberbayern süd" not in tl and "oberbayern sued" not in tl: return []
    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title)
    if not dm: return []
    y = int(dm[3])
    if not (2020 <= y <= 2030): return []
    pm_date = datetime(y, int(dm[2]), int(dm[1]))
    if pm_date < from_date or pm_date > to_date: return []
    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []
    full_text = content.get_text(" ", strip=True)
    if not is_relevant(full_text): return []
    incidents = []
    sections = content.find_all("h3")
    if sections:
        for h in sections:
            heading = h.get_text(" ", strip=True)
            num_m = re.match(r"^(\d+)\.\s+", heading)
            nr = num_m[1] if num_m else ""
            titel = re.sub(r"^\d+\.\s+", "", heading).strip()
            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3","h2","hr"): break
                parts.append(sib.get_text(" ", strip=True))
            body = " ".join(parts).strip()
            if len(body) < 30 or not is_relevant(heading+" "+body): continue
            inc_date = parse_date(body, pm_date)
            ort_m = re.search(r"–\s*(.+)$", titel)
            ort = detect_ort(ort_m[1].strip() if ort_m else body)
            kat, sev = categorize(titel + " " + body)
            incidents.append({
                "date": inc_date.strftime("%d.%m.%Y"), "dateSort": inc_date.strftime("%Y-%m-%d"),
                "time": parse_time(body), "nr": nr, "kategorie": kat, "schweregrad": sev,
                "ort": ort, "pp": PP_NAME, "region": PP_NAME,
                "titel": titel[:120], "volltext": body[:1500], "link": url,
            })
    else:
        for p in content.find_all("p"):
            text = p.get_text(" ", strip=True)
            if len(text) < 50 or not is_relevant(text): continue
            inc_date = parse_date(text, pm_date)
            kat, sev = categorize(text)
            incidents.append({
                "date": inc_date.strftime("%d.%m.%Y"), "dateSort": inc_date.strftime("%Y-%m-%d"),
                "time": parse_time(text), "nr": "", "kategorie": kat, "schweregrad": sev,
                "ort": detect_ort(text), "pp": PP_NAME, "region": PP_NAME,
                "titel": text[:100], "volltext": text[:1500], "link": url,
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
