#!/usr/bin/env python3
"""PP München Scraper
Quelle: @PressePolizeiMuenchen (Telegram)
Format: h3-Tags (ältere Artikel) ODER Fließtext-Paragraphen (neuere Artikel)
Jeder Paragraph = ein Vorfall
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
MAX_PAGES        = 60
SLEEP_SEC        = 0.8
MAX_CONSEC_FAILS = 8
MAX_NEW_PER_RUN  = 200
DATA_FILE        = "data/incidents_muenchen.json"
PP_NAME          = "PP München"
TG_CHANNEL       = "PressePolizeiMuenchen"
TITLE_MUST_CONTAIN = "münchen"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

RULES = [
    ("Tötungsdelikt",3,["tötungsdelikt","mord","totschlag","mordkommission","kommissariat 11","lebensgefahr","tödlich verletzt"]),
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
    ("Prävention",1,["prävention","warnt","warnung","hinweis der polizei","fahrradcodier","terminhinweis"]),
]

ORT_MAP = [
    ("Altstadt-Lehel","Altstadt-Lehel"),("Altstadt","Altstadt-Lehel"),("Lehel","Altstadt-Lehel"),
    ("Maxvorstadt","Maxvorstadt"),("Schwabing-West","Schwabing-West"),("Schwabing","Schwabing"),
    ("Neuhausen-Nymphenburg","Neuhausen-Nymphenburg"),("Neuhausen","Neuhausen-Nymphenburg"),("Nymphenburg","Neuhausen-Nymphenburg"),
    ("Sendling","Sendling"),("Au-Haidhausen","Au-Haidhausen"),("Haidhausen","Au-Haidhausen"),
    ("Bogenhausen","Bogenhausen"),("Pasing-Obermenzing","Pasing-Obermenzing"),("Pasing","Pasing-Obermenzing"),("Obermenzing","Pasing-Obermenzing"),
    ("Obergiesing","Obergiesing"),("Untergiesing","Untergiesing"),("Harlaching","Harlaching"),
    ("Giesing","Giesing"),("Moosach","Moosach"),("Ramersdorf-Perlach","Ramersdorf-Perlach"),
    ("Ramersdorf","Ramersdorf-Perlach"),("Perlach","Ramersdorf-Perlach"),
    ("Milbertshofen","Milbertshofen"),("Freimann","Milbertshofen"),("Trudering","Trudering"),
    ("Hadern","Hadern"),("Laim","Laim"),("Berg am Laim","Berg am Laim"),
    ("Feldmoching-Hasenbergl","Feldmoching-Hasenbergl"),("Feldmoching","Feldmoching-Hasenbergl"),("Hasenbergl","Feldmoching-Hasenbergl"),
    ("Schwanthalerhöhe","Schwanthalerhöhe"),("Thalkirchen","Thalkirchen"),
    ("Ludwigsvorstadt","Ludwigsvorstadt"),("Isarvorstadt","Isarvorstadt"),
    ("Allach-Untermenzing","Allach-Untermenzing"),("Allach","Allach-Untermenzing"),
    ("Hauptbahnhof","Stadtmitte"),("Marienplatz","Stadtmitte"),("Stachus","Stadtmitte"),
    ("Karlsplatz","Stadtmitte"),("Bahnhofsviertel","Stadtmitte"),("Innenstadt","Stadtmitte"),
    ("Neuperlach","Neuperlach"),("Fürstenried","Fürstenried"),("Solln","Solln"),
    ("Aubing","Aubing"),("Lochhausen","Lochhausen"),
]

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
    print(f"  📡 @{TG_CHANNEL}…")
    art_pat = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')
    seen, urls, before_id = set(), [], None
    for page in range(MAX_PAGES):
        url = f"https://t.me/s/{TG_CHANNEL}" + (f"?before={before_id}" if before_id else "")
        html = fetch(url, timeout=20)
        if not html: break
        new = 0
        for m in art_pat.finditer(html):
            if m[0] not in seen: seen.add(m[0]); urls.append(m[0]); new += 1
        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        print(f"    Seite {page+1}: {new} neue, {len(urls)} gesamt (bis #{min_id})")
        if min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.5)
    print(f"  {len(urls)} einzigartige Links")
    return urls

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    if TITLE_MUST_CONTAIN not in title.lower(): return []

    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title)
    if not dm: return []
    y = int(dm[3])
    if not (2020 <= y <= 2030): return []
    pm_date = datetime(y, int(dm[2]), int(dm[1]))
    if pm_date < from_date or pm_date > to_date: return []

    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    # ── Format 1: h3-Tags (ältere Artikel) ───────────────────────────────────
    sections = content.find_all("h3")
    if sections:
        incidents = []
        for h in sections:
            heading = h.get_text(" ", strip=True)
            num_m = re.match(r"^(\d+)\.\s+", heading)
            nr = num_m[1] if num_m else ""
            titel = re.sub(r"^\d+\.\s+", "", heading).strip()
            ort_m = re.search(r"–\s*(.+)$", titel)
            ort = detect_ort(ort_m[1].strip()) if ort_m else "Unbekannt"
            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3","h2","hr"): break
                parts.append(sib.get_text(" ", strip=True))
            body = " ".join(parts).strip()
            if len(body) < 30: continue
            inc_date = parse_date(body, pm_date)
            kat, sev = categorize(titel + " " + body)
            if ort == "Unbekannt": ort = detect_ort(body)
            incidents.append(_inc(inc_date, parse_time(body), nr, kat, sev, ort, titel[:120], body[:1500], url))
        return incidents

    # ── Format 2: Fließtext-Paragraphen (neuere Artikel) ─────────────────────
    # Jeder <p>-Tag ist ein eigenständiger Vorfall
    # Erkennungsmuster: Paragraphen beginnen mit "Am [Wochentag], [Datum]..."
    incidents = []
    paragraphs = content.find_all("p")

    # Gruppiere zusammengehörige Paragraphen zu Vorfällen
    # Neuer Vorfall: Paragraph beginnt mit "Am [Wochentag]" UND enthält ein Datum
    WOCHENTAGE = r'(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)'
    new_incident_pat = re.compile(rf'^Am {WOCHENTAGE},\s+\d{{1,2}}\.\d{{1,2}}\.\d{{4}}')

    groups = []  # Liste von Paragraph-Gruppen, je Gruppe = ein Vorfall
    current_group = []

    for p in paragraphs:
        text = p.get_text(" ", strip=True)
        if len(text) < 20: continue

        if new_incident_pat.match(text):
            # Neuer Vorfall beginnt
            if current_group:
                groups.append(current_group)
            current_group = [text]
        elif current_group:
            # Continuation: zum aktuellen Vorfall hinzufügen
            current_group.append(text)
        else:
            # Noch kein Vorfall begonnen (z.B. Einleitung) → eigene Gruppe
            current_group = [text]

    if current_group:
        groups.append(current_group)

    for i, group in enumerate(groups):
        body = " ".join(group).strip()
        if len(body) < 50: continue

        inc_date = parse_date(body, pm_date)
        kat, sev = categorize(body)
        ort = detect_ort(body)

        # Titel: erster Satz (bis zum ersten Punkt/Komma nach mindestens 30 Zeichen)
        first = group[0]
        titel = first[:120]

        incidents.append(_inc(inc_date, parse_time(body), str(i+1), kat, sev, ort, titel, body[:1500], url))

    # Fallback: gesamter Text als ein Eintrag
    if not incidents:
        full = content.get_text(" ", strip=True)
        if len(full) > 50:
            kat, sev = categorize(full)
            incidents.append(_inc(pm_date, parse_time(full), "1", kat, sev, detect_ort(full), full[:120], full[:1500], url))

    return incidents

def _inc(dt, time_str, nr, kat, sev, ort, titel, volltext, link):
    return {
        "date": dt.strftime("%d.%m.%Y"), "dateSort": dt.strftime("%Y-%m-%d"),
        "time": time_str, "nr": nr, "kategorie": kat, "schweregrad": sev,
        "ort": ort, "pp": PP_NAME, "region": PP_NAME,
        "titel": titel, "volltext": volltext, "link": link,
    }

def main():
    to_date = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)
    print(f"══ {PP_NAME} · {from_date.date()} → {to_date.date()} ══")

    urls = get_urls()
    existing, existing_links = [], set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f: existing = json.load(f)
        existing_links = {p.get("link","") for p in existing}
        print(f"  Bestehend: {len(existing)} Vorfälle")
    except: print("  Starte frisch")

    new_urls = [u for u in urls if u not in existing_links]
    if len(new_urls) > MAX_NEW_PER_RUN:
        print(f"  ⚠ {len(new_urls)} neue → verarbeite erste {MAX_NEW_PER_RUN}")
        new_urls = new_urls[:MAX_NEW_PER_RUN]
    print(f"  Verarbeite: {len(new_urls)} URLs\n")

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
