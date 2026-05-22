#!/usr/bin/env python3
"""
PP Schwaben Nord Scraper
Strategie: Bekannte Artikel-IDs als Startpunkte + sequentielles Scanning
Da @PolizeiBayern von GitHub Actions geblockt wird, nutzen wir:
1. Bekannte Seed-IDs die wir bereits kennen
2. Vom letzten bekannten ID vorwärts scannen
Format: Bold-Tags "0701 – Ort – Titel"
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
SLEEP_SEC        = 0.5
MAX_CONSEC_FAILS = 15   # Mehr Toleranz beim sequentiellen Scan
MAX_NEW_PER_RUN  = 150
DATA_FILE        = "data/incidents_swn.json"
PP_NAME          = "PP Schwaben Nord"
PP_IDENTIFIERS   = ["schwaben nord", "polizeipräsidium schwaben nord", "nordschwaben"]

# Bekannte SWN Artikel-IDs als Startpunkte (aus alten Daten + Recherche)
SEED_IDS = [
    79373, 81162, 84371, 85854, 87620,
    98869, 98949, 99005, 99064, 99276, 99546,
    100490, 100646, 100776, 100891, 101038,
    101761, 101830, 101989, 102184,
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

RULES = [
    ("Tötungsdelikt",3,["tötungsdelikt","mord","totschlag","mordkommission","lebensgefahr","tödlich verletzt"]),
    ("Sexualdelikt",3,["vergewaltigung","sexuelle nötigung","missbrauch von kindern","sexueller missbrauch"]),
    ("Raub",3,["unter vorhalt einer schusswaffe","unter vorhalt eines messers","bewaffneter raubüberfall"]),
    ("Körperverletzung",3,["messer","gestochen","stichverletzung","schwere körperverletzung","gefährliche körperverletzung","notoperation"]),
    ("Einbruch",3,["wohnungseinbruch"]),
    ("Branddelikt",3,["schwere brandstiftung","vorsätzliche brandleg","feuer gelegt","in brand gesetzt"]),
    ("Sexualdelikt",2,["sexuelle belästigung","unsittlich berührt","exhibitionistisch"]),
    ("Raub",2,["raub","beraubt","entrissen","handtaschenraub","erpressung"]),
    ("Körperverletzung",2,["körperverletzung","schlägerei","geschlagen","getreten","faustschlag","bewusstlos","angriff"]),
    ("Einbruch",2,["einbruch","einbrecher","eingebrochen","aufgehebelt","aufgebrochen","einbruchsversuch","gewaltsam zutritt"]),
    ("Branddelikt",2,["brandstiftung","brand","flammen"]),
    ("Drogen",2,["kokain","heroin","amphetamin","crystal","drogenhandel"]),
    ("Betrug",2,["enkeltrick","schockanruf","falscher polizist","trickbetrug"]),
    ("Vermisstenfall",2,["vermisst","vermisstenfall","abgängig","kind vermisst"]),
    ("Fahndung",2,["öffentlichkeitsfahndung","haftbefehl","festgenommen"]),
    ("Verkehr",2,["rettungshubschrauber","kollision mit","zusammenstoß mit"]),
    ("Diebstahl",1,["diebstahl","gestohlen","entwendet","taschendiebstahl","ladendiebstahl","fahrraddiebstahl","kfz-diebstahl"]),
    ("Drogen",1,["cannabis","marihuana","btm","betäubungsmittel","dealer"]),
    ("Betrug",1,["betrug","betrüger","phishing","cybercrime"]),
    ("Verkehr",1,["verkehrsunfall","unfall","auffahrunfall","unfallflucht","fahrerflucht","alkohol am steuer","überladung","stürzte","rotlicht"]),
    ("Vandalismus",1,["sachbeschädigung","graffiti","beschmiert","schmähschrift"]),
    ("Fahndung",1,["zeugenaufruf","zeugen gesucht","hinweise erbeten"]),
    ("Prävention",1,["prävention","warnt","warnung","hinweis der polizei","terminhinweis","mobile wache"]),
]

def categorize(text):
    t = text.lower()
    for kat, sev, words in RULES:
        if any(w in t for w in words): return kat, sev
    return "Sonstiges", 1

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
            if r.status_code == 404: return None  # Artikel existiert nicht
            r.raise_for_status(); r.encoding = "utf-8"; return r.text
        except Exception as e:
            if attempt == 0: time.sleep(1)
            else: pass  # Kein Print beim sequentiellen Scan
    return None

def is_swn(title, body_start=""):
    combined = (title + " " + body_start).lower()
    return any(ident in combined for ident in PP_IDENTIFIERS)

def get_urls(existing_links, from_date):
    """
    Generiert URLs zum Scannen:
    1. Bekannte Seed-IDs die noch nicht verarbeitet wurden
    2. Sequentiell vorwärts vom höchsten bekannten ID
    """
    seen = set(existing_links)
    urls = []

    # Alle bereits bekannten IDs aus existing_links
    known_ids = set()
    for link in existing_links:
        m = re.search(r'/(\d{6})/', link)
        if m: known_ids.add(int(m[1]))

    # Seed-IDs die noch nicht bekannt sind
    for art_id in SEED_IDS:
        url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{art_id:06d}/index.html"
        if url not in seen:
            urls.append(url)

    # Höchste bekannte ID ermitteln
    all_known = known_ids | set(SEED_IDS)
    if all_known:
        max_known = max(all_known)
        # Vorwärts scannen ab max_known bis aktuelle ID
        # Schätzung: SWN postet ~1-2x/Tag, also ~1 SWN-ID pro 200-400 gesamt-IDs
        # Wir scannen jeden 50. ID vorwärts (SWN ist ca. 1 von 10 PPs)
        current_max = max_known + 1
        while current_max <= max_known + 5000:  # Max 5000 IDs vorwärts
            url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{current_max:06d}/index.html"
            if url not in seen:
                urls.append(url)
            current_max += 1

    print(f"  {len(urls)} URLs zum Scannen")
    return urls

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    body_start = html[:500]

    if not is_swn(title, body_start): return []

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

    # SWN Format: Bold-Tags "0701 – Ort – Titel"
    for bold in content.find_all(["strong","b"]):
        heading = bold.get_text(" ", strip=True)
        nr_m = re.match(r'^(\d{3,4})\s*[–-]\s*(.+)$', heading)
        if not nr_m: continue

        nr   = nr_m[1]
        rest = nr_m[2].strip()
        ort_m = re.match(r'^([^–-]+?)\s*[–-]\s*', rest)
        ort   = ort_m[1].strip() if ort_m else rest[:50]
        titel_part = rest[ort_m.end():].strip() if ort_m else rest
        titel = f"{nr} – {ort}" + (f" – {titel_part}" if titel_part else "")

        parent = bold.parent
        parent_full = parent.get_text(" ", strip=True)
        bold_text = bold.get_text(" ", strip=True)
        after = parent_full[parent_full.find(bold_text)+len(bold_text):].strip()

        body_parts = [after] if after else []
        for sib in parent.find_next_siblings():
            nb = sib.find(["strong","b"])
            if nb and re.match(r'^\d{3,4}\s*[–-]', nb.get_text(strip=True)): break
            t = sib.get_text(" ", strip=True)
            if t: body_parts.append(t)

        body = " ".join(body_parts).strip()
        if len(body) < 20: continue
        if "mobile wache" in (heading+body).lower() and len(body) < 100: continue

        inc_date = parse_date(body, pm_date)
        kat, sev = categorize(heading + " " + body)

        incidents.append({
            "date": inc_date.strftime("%d.%m.%Y"), "dateSort": inc_date.strftime("%Y-%m-%d"),
            "time": parse_time(body), "nr": nr, "kategorie": kat, "schweregrad": sev,
            "ort": ort[:80], "pp": PP_NAME, "region": PP_NAME,
            "titel": titel[:120], "volltext": body[:1500], "link": url,
        })

    # Fallback: Paragraphen
    if not incidents:
        for p in content.find_all("p"):
            text = p.get_text(" ", strip=True)
            if len(text) < 50: continue
            ort_m = re.match(r'^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß/ -]+?)\s*[–-]\s*', text)
            ort = ort_m[1].strip() if ort_m else "Unbekannt"
            kat, sev = categorize(text)
            incidents.append({
                "date": pm_date.strftime("%d.%m.%Y"), "dateSort": pm_date.strftime("%Y-%m-%d"),
                "time": parse_time(text), "nr": "", "kategorie": kat, "schweregrad": sev,
                "ort": ort, "pp": PP_NAME, "region": PP_NAME,
                "titel": text[:100], "volltext": text[:1500], "link": url,
            })

    return incidents

def main():
    to_date   = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)
    print(f"══ {PP_NAME} · {from_date.date()} → {to_date.date()} ══")

    existing, existing_links = [], set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f: existing = json.load(f)
        existing_links = {p.get("link","") for p in existing}
        # Normalisiere URLs (mit/ohne www)
        existing_links |= {l.replace("//www.", "//").replace("//polizei", "//www.polizei") for l in existing_links}
        print(f"  Bestehend: {len(existing)} Vorfälle")
    except: print("  Starte frisch")

    urls = get_urls(existing_links, from_date)

    if len(urls) > MAX_NEW_PER_RUN:
        print(f"  ⚠ {len(urls)} URLs → verarbeite erste {MAX_NEW_PER_RUN}")
        urls = urls[:MAX_NEW_PER_RUN]

    print(f"  Verarbeite: {len(urls)} URLs\n")

    all_incidents = list(existing)
    loaded = 0; consec_non_swn = 0

    for i, url in enumerate(urls):
        html = fetch(url)
        if not html:
            consec_non_swn += 1
            if consec_non_swn >= MAX_CONSEC_FAILS:
                print(f"  {MAX_CONSEC_FAILS} nicht-SWN Artikel in Folge – stoppe")
                break
            continue

        # Prüfe ob SWN-Artikel
        if not is_swn(html[:300]):
            consec_non_swn += 1
            if i % 50 == 0:
                art_id = url.split("/")[-2]
                print(f"  [{i+1}/{len(urls)}] {art_id}: kein SWN")
            continue
        else:
            consec_non_swn = 0

        art_id = url.split("/")[-2]
        print(f"  [{i+1}/{len(urls)}] {art_id}", end=" … ")
        incidents = parse_article(html, url, from_date, to_date)
        if incidents:
            print(f"✓ {len(incidents)}")
            all_incidents.extend(incidents); existing_links.add(url); loaded += 1
        else:
            print("✗")

        if loaded > 0 and loaded % 20 == 0: _save(all_incidents, loaded, True)
        time.sleep(SLEEP_SEC)

    _save(all_incidents, loaded)

def _save(data, loaded, partial=False):
    data.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")), reverse=True)
    seen, deduped = set(), []
    for inc in data:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    if not partial:
        print(f"\n  ✅ {loaded} neue · {len(deduped)} Vorfälle → {DATA_FILE}")

if __name__ == "__main__": main()
