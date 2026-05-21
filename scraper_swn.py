#!/usr/bin/env python3
"""
PP Schwaben Nord Scraper
Format: "DD.MM.YYYY, Polizeipräsidium Schwaben Nord"
        dann "0701 – Ort – Vorfallstitel" als Bold-Tags
Quelle: @PolizeiBayern Telegram + polizei.bayern.de Listenseite
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK       = 500
SLEEP_SEC       = 0.8
MAX_CONSEC_FAILS= 8
MAX_NEW_PER_RUN = 150
DATA_FILE       = "data/incidents_swn.json"
PP_NAME         = "PP Schwaben Nord"
PP_IDENTIFIERS  = ["schwaben nord", "polizeipräsidium schwaben nord", "nordschwaben"]

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

def fetch(url, timeout=10):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status(); r.encoding = "utf-8"; return r.text
        except Exception as e:
            if attempt == 0: time.sleep(1.5)
            else: print(f"  ✗ {url[-50:]} → {e}")
    return None

def get_urls(existing_links):
    seen = set(existing_links)
    urls = []

    # 1. Sucharchiv (Hauptquelle für historische Artikel)
    print(f"  🗄 Sucharchiv (SWN)…")
    art_pat = re.compile(r'href="(/aktuelles/pressemitteilungen/(\d{6})/index\.html)"')
    from_date = (datetime.now() - timedelta(days=500)).strftime('%d.%m.%Y')
    to_date_str = datetime.now().strftime('%d.%m.%Y')
    for page in range(1, 60):
        params = f"?Verband=SWN&Suchbegriff=&Zeitraum=eigeneDaten&DatumVon={from_date}&DatumBis={to_date_str}&page={page}"
        html = fetch("https://www.polizei.bayern.de/suche/presse/index.html" + params, timeout=15)
        if not html:
            print("    Archiv nicht erreichbar – überspringe")
            break
        found = 0
        for m in art_pat.finditer(html):
            full = f"https://www.polizei.bayern.de{m[1]}"
            if full not in seen: seen.add(full); urls.append(full); found += 1
        print(f"    Seite {page}: {found} neue ({len(urls)} gesamt)")
        if found == 0: break
        time.sleep(0.5)

    # 2. Telegram als Ergänzung
    print("  📡 @PolizeiBayern…")
    art_pat2 = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat  = re.compile(r'data-post="[^/]+/(\d+)"')
    before_id = None
    for page in range(15):
        tg_url = "https://t.me/s/PolizeiBayern" + (f"?before={before_id}" if before_id else "")
        html = fetch(tg_url, timeout=20)
        if not html: break
        for m in art_pat2.finditer(html):
            if m[0] not in seen: seen.add(m[0]); urls.append(m[0])
        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        if min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.5)

    print(f"  {len(urls)} neue URLs total")
    return urls

def is_swn_article(title, body_start):
    combined = (title + " " + body_start).lower()
    return any(ident in combined for ident in PP_IDENTIFIERS)

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()

    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    full_text = content.get_text(" ", strip=True)
    body_start = full_text[:300]

    if not is_swn_article(title, body_start): return []

    # Datum aus Artikelanfang: "20.05.2026, Polizeipräsidium Schwaben Nord"
    pm_date = parse_date(body_start, None) or parse_date(title, None)
    if not pm_date: return []
    if pm_date < from_date or pm_date > to_date: return []

    incidents = []

    # SWN Format: Bold-Tags als Abschnittstrenner
    # "0701 – Ort – Vorfallstitel" oder "Ort – Vorfallstitel"
    bolds = content.find_all(["strong", "b"])

    for bold in bolds:
        heading = bold.get_text(" ", strip=True)

        # Nummeriertes Format: "0701 – Ort" oder "0701 - Ort"
        nr_m = re.match(r'^(\d{3,4})\s*[–-]\s*(.+)$', heading)
        if not nr_m: continue

        nr   = nr_m[1]
        rest = nr_m[2].strip()

        # Ort aus "Ort – Vorfallstitel" extrahieren
        ort_m = re.match(r'^([^–-]+?)\s*[–-]\s*', rest)
        ort   = ort_m[1].strip() if ort_m else rest[:50]

        # Titel: Rest nach dem Ort
        titel_part = rest[ort_m.end():].strip() if ort_m else rest
        titel = f"{nr} – {ort} – {titel_part}" if titel_part else f"{nr} – {ort}"

        # Fließtext: Text im gleichen Absatz nach dem Bold + folgende Absätze
        parent = bold.parent
        parent_full = parent.get_text(" ", strip=True)
        bold_text   = bold.get_text(" ", strip=True)
        after_bold  = parent_full[parent_full.find(bold_text) + len(bold_text):].strip()

        body_parts = [after_bold] if after_bold else []
        for sib in parent.find_next_siblings():
            # Stoppe beim nächsten nummerierten Bold
            next_bold = sib.find(["strong", "b"])
            if next_bold:
                nb_text = next_bold.get_text(strip=True)
                if re.match(r'^\d{3,4}\s*[–-]', nb_text): break
            t = sib.get_text(" ", strip=True)
            if t: body_parts.append(t)

        body = " ".join(body_parts).strip()
        if len(body) < 20: continue

        # "Mobile Wache" Einträge überspringen
        if "mobile wache" in (heading + body).lower() and len(body) < 100: continue

        inc_date = parse_date(body, pm_date)
        kat, sev = categorize(heading + " " + body)

        incidents.append({
            "date": inc_date.strftime("%d.%m.%Y"), "dateSort": inc_date.strftime("%Y-%m-%d"),
            "time": parse_time(body), "nr": nr, "kategorie": kat, "schweregrad": sev,
            "ort": ort[:80], "pp": PP_NAME, "region": PP_NAME,
            "titel": titel[:120], "volltext": body[:1500], "link": url,
        })

    # Fallback: keine Bold-Tags → Paragraphen parsen
    if not incidents:
        for p in content.find_all("p"):
            text = p.get_text(" ", strip=True)
            if len(text) < 50: continue
            # Ort – Fließtext Format
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
        print(f"  Bestehend: {len(existing)} Vorfälle")
    except: print("  Starte frisch")

    new_urls = get_urls(existing_links)
    if len(new_urls) > MAX_NEW_PER_RUN:
        print(f"  ⚠ {len(new_urls)} URLs → verarbeite erste {MAX_NEW_PER_RUN}")
        new_urls = new_urls[:MAX_NEW_PER_RUN]
    print(f"  Verarbeite: {len(new_urls)} URLs\n")

    all_incidents = list(existing)
    
    if not new_urls:
        print("  ⚠ Keine neuen URLs gefunden (Quellen nicht erreichbar)")
        print(f"  ✅ Bestehende Daten unverändert: {len(all_incidents)} Vorfälle")
        return
    
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
        if incidents:
            print(f"✓ {len(incidents)}")
            all_incidents.extend(incidents); existing_links.add(url); loaded += 1
        else: print("✗")
        if loaded > 0 and loaded % 30 == 0: _save(all_incidents, loaded, True)
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
