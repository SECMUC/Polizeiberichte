#!/usr/bin/env python3
"""PP Oberbayern Nord Scraper
Strategie: Bekannte Seed-IDs + Scan jedes N-ten IDs um neue SWN-Artikel zu finden.
Da @PolizeiBayern geblockt ist, wird direkt polizei.bayern.de gescannt.
Format: Bold-Tags "0701 – Ort – Titel" oder Paragraphen
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
SLEEP_SEC        = 0.5
MAX_CONSEC_FAILS = 20
MAX_NEW_PER_RUN  = 50    # Weniger pro Lauf
MAX_SCAN_IDS     = 300   # Absolutes Maximum an IDs pro Lauf
SCAN_STEP        = 50    # Jeden 50. ID prüfen
DATA_FILE        = "data/incidents_obn.json"
PP_NAME          = "PP Oberbayern Nord"
PP_IDENTIFIERS   = ["oberbayern nord", "polizeipräsidium oberbayern nord"]

# Bekannte SWN Artikel-IDs (aus Recherche + alten Daten)
# Werden als Ankerpunkte für den Scan genutzt
KNOWN_IDS = sorted([
    78183, 83328, 84365, 91806, 96149, 99819,
    100426, 101879,
])

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
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 404: return None
        r.raise_for_status(); r.encoding = "utf-8"; return r.text
    except: return None

def is_swn(text):
    t = text.lower()
    return any(ident in t for ident in PP_IDENTIFIERS)

def get_scan_ids(existing_links, from_date):
    """Generiert eine kurze, effiziente Liste von IDs zum Scannen."""
    known = set(KNOWN_IDS)
    for link in existing_links:
        m = re.search(r'/(\d{6})/', link)
        if m: known.add(int(m[1]))

    max_known = max(known) if known else 103000
    to_scan = []

    # 1. Bekannte IDs die noch nicht verarbeitet wurden (höchste Priorität)
    for art_id in sorted(known, reverse=True):
        url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{art_id:06d}/index.html"
        if url not in existing_links:
            to_scan.append(art_id)

    # 2. Vorwärts ab höchstem bekanntem ID – nur 500 IDs
    # (SWN postet ~1 Artikel pro 1800 IDs, also ~0.3 Treffer erwartet → reicht für täglich)
    for scan_id in range(max_known + 1, max_known + 501):
        url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{scan_id:06d}/index.html"
        if url not in existing_links:
            to_scan.append(scan_id)

    # 3. Rückwärts-Stichproben in Lücken (nur wenn noch Kapazität)
    if len(to_scan) < MAX_SCAN_IDS:
        sorted_known = sorted(known)
        for i in range(len(sorted_known)-1, 0, -1):  # Von neuesten rückwärts
            start = sorted_known[i-1] + SCAN_STEP
            end   = sorted_known[i]
            for scan_id in range(start, end, SCAN_STEP):
                url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{scan_id:06d}/index.html"
                if url not in existing_links:
                    to_scan.append(scan_id)
                    if len(to_scan) >= MAX_SCAN_IDS:
                        break
            if len(to_scan) >= MAX_SCAN_IDS:
                break

    result = sorted(set(to_scan))[:MAX_SCAN_IDS]
    print(f"  {len(result)} IDs zum Scannen (max {MAX_SCAN_IDS})")
    return result

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()

    if not is_swn(title): return []

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

    # Format 1: h3-Tags
    sections = content.find_all("h3")
    if sections:
        for h in sections:
            heading = h.get_text(" ", strip=True)
            titel = re.sub(r"^\d+\.\s+", "", heading).strip()
            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3","h2","hr"): break
                parts.append(sib.get_text(" ", strip=True))
            body = " ".join(parts).strip()
            if len(body) < 30: continue
            ort_m = re.search(r"–\s*(.+)$", titel)
            ort = ort_m[1].strip() if ort_m else "Unbekannt"
            kat, sev = categorize(titel + " " + body)
            incidents.append(_inc(pm_date, parse_time(body), "", kat, sev, ort[:80], titel[:120], body[:1500], url))
        return incidents

    # Format 2: Bold "0701 – Ort – Titel" (Haupt-SWN-Format)
    bolds = [b for b in content.find_all(["strong","b"])
             if re.match(r'^\d{3,4}\s*[–-]', b.get_text(strip=True))]
    if bolds:
        for bold in bolds:
            heading = bold.get_text(" ", strip=True)
            nr_m = re.match(r'^(\d{3,4})\s*[–-]\s*(.+)$', heading)
            if not nr_m: continue
            nr = nr_m[1]; rest = nr_m[2].strip()
            ort_m = re.match(r'^([^–-]+?)\s*[–-]\s*', rest)
            ort = ort_m[1].strip() if ort_m else rest[:50]
            titel_r = rest[ort_m.end():].strip() if ort_m else ""
            titel = f"{nr} – {ort}" + (f" – {titel_r}" if titel_r else "")
            parent = bold.parent
            pt = parent.get_text(" ", strip=True)
            bt = bold.get_text(" ", strip=True)
            after = pt[pt.find(bt)+len(bt):].strip()
            body_parts = [after] if after else []
            for sib in parent.find_next_siblings():
                nb = sib.find(["strong","b"])
                if nb and re.match(r'^\d{3,4}\s*[–-]', nb.get_text(strip=True)): break
                t = sib.get_text(" ", strip=True)
                if t: body_parts.append(t)
            body = " ".join(body_parts).strip()
            if len(body) < 20: continue
            inc_date = parse_date(body, pm_date)
            kat, sev = categorize(heading + " " + body)
            incidents.append(_inc(inc_date, parse_time(body), nr, kat, sev, ort[:80], titel[:120], body[:1500], url))
        return incidents

    # Format 3: Paragraphen "Ort – Fließtext"
    for p in content.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) < 50: continue
        ort_m = re.match(r'^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß/ -]+?)\s*[–-]\s*', text)
        ort = ort_m[1].strip() if ort_m else "Unbekannt"
        kat, sev = categorize(text)
        incidents.append(_inc(pm_date, parse_time(text), "", kat, sev, ort[:80], text[:100], text[:1500], url))

    return incidents

def _inc(dt, t, nr, kat, sev, ort, titel, volltext, link):
    return {"date":dt.strftime("%d.%m.%Y"),"dateSort":dt.strftime("%Y-%m-%d"),
            "time":t,"nr":nr,"kategorie":kat,"schweregrad":sev,
            "ort":ort,"pp":PP_NAME,"region":PP_NAME,
            "titel":titel,"volltext":volltext,"link":link}

def main():
    to_date   = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)
    print(f"══ {PP_NAME} · {from_date.date()} → {to_date.date()} ══")

    existing, existing_links = [], set()
    try:
        with open(DATA_FILE,"r",encoding="utf-8") as f: existing = json.load(f)
        existing_links = {p.get("link","") for p in existing}
        # Normalisiere URLs
        existing_links |= {l.replace("https://polizei","https://www.polizei") for l in existing_links}
        print(f"  Bestehend: {len(existing)} Vorfälle")
    except: print("  Starte frisch")

    scan_ids = get_scan_ids(existing_links, from_date)
    print(f"  {len(scan_ids)} IDs zum Scannen")

    all_incidents = list(existing)
    loaded = 0; scanned = 0

    for art_id in scan_ids:
        if loaded >= MAX_NEW_PER_RUN:
            print(f"  Maximum {MAX_NEW_PER_RUN} neue Artikel erreicht")
            break

        url = f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{art_id:06d}/index.html"
        html = fetch(url)
        scanned += 1

        if not html:
            continue

        # Schnell-Check ob SWN
        if not is_swn(html[:500]):
            continue

        print(f"  [{scanned}] {art_id}", end=" … ")
        incidents = parse_article(html, url, from_date, to_date)
        if incidents:
            print(f"✓ {len(incidents)}")
            all_incidents.extend(incidents); existing_links.add(url); loaded += 1
        else:
            print("✗")

        if loaded > 0 and loaded % 20 == 0: _save(all_incidents, loaded, True)
        time.sleep(SLEEP_SEC)

    print(f"\n  Gescannt: {scanned} IDs, {loaded} neue SWN-Artikel")
    _save(all_incidents, loaded)

def _save(data, loaded, partial=False):
    data.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)
    seen, deduped = set(), []
    for inc in data:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(deduped,f,ensure_ascii=False,indent=2)
    if not partial:
        print(f"  ✅ {loaded} neue · {len(deduped)} Vorfälle → {DATA_FILE}")

if __name__ == "__main__": main()
