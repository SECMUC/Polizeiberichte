#!/usr/bin/env python3
"""PP Oberbayern Süd Scraper
Quellen: @PolizeiBayern Telegram + polizei.bayern.de/suche/presse (Archiv)
Format: Fließtext mit Orts-Markern
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAYS_BACK        = 500
SLEEP_SEC        = 0.8
MAX_CONSEC_FAILS = 8
MAX_NEW_PER_RUN  = 150
DATA_FILE        = "data/incidents_obs.json"
PP_NAME          = "PP Oberbayern Süd"
PP_IDENTIFIERS   = ["oberbayern süd", "polizeipräsidium oberbayern süd", "südliches oberbayern"]
# Sucharchiv-Parameter für dieses PP
ARCHIVE_VERBAND  = "OBS"

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
    ("Prävention",1,["prävention","warnt","warnung","hinweis der polizei","terminhinweis"]),
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

def detect_ort(text):
    m = re.match(r'^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß ,.()\-]+?)(?:\s*[,\n]|\s*[–-]\s|\s+\d{2}\.)', text.strip())
    if m:
        ort = m[1].strip().rstrip(',').strip()
        if 2 < len(ort) < 60: return ort
    return "Unbekannt"

def fetch(url, timeout=10):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status(); r.encoding = "utf-8"; return r.text
        except Exception as e:
            if attempt == 0: time.sleep(1.5)
            else: print(f"  ✗ {url[-50:]} → {e}")
    return None

def get_urls_from_archive(from_date, existing_links):
    """Crawlt das polizei.bayern.de Sucharchiv seitenweise."""
    seen = set(existing_links)
    urls = []
    art_pat = re.compile(r'href="(/aktuelles/pressemitteilungen/(\d{6})/index\.html)"')

    print(f"  🗄 Sucharchiv ({ARCHIVE_VERBAND})…")
    base = f"https://www.polizei.bayern.de/suche/presse/index.html"

    for page in range(1, 60):  # Max 60 Seiten à ~10 Artikel = ~600 Artikel
        params = f"?Verband={ARCHIVE_VERBAND}&Suchbegriff=&Zeitraum=eigeneDaten&DatumVon={from_date.strftime('%d.%m.%Y')}&DatumBis={datetime.now().strftime('%d.%m.%Y')}&page={page}"
        html = fetch(base + params, timeout=15)
        if not html: break

        found = 0
        for m in art_pat.finditer(html):
            full = f"https://www.polizei.bayern.de{m[1]}"
            if full not in seen:
                seen.add(full); urls.append(full); found += 1

        print(f"    Seite {page}: {found} neue Links ({len(urls)} gesamt)")
        if found == 0: break  # Keine neuen Links → Ende
        time.sleep(0.5)

    return urls

def get_urls_from_telegram(existing_links):
    """Ergänzend: @PolizeiBayern Telegram."""
    seen = set(existing_links)
    urls = []
    art_pat = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')
    before_id = None
    for page in range(15):
        tg_url = "https://t.me/s/PolizeiBayern" + (f"?before={before_id}" if before_id else "")
        html = fetch(tg_url, timeout=20)
        if not html: break
        for m in art_pat.finditer(html):
            if m[0] not in seen: seen.add(m[0]); urls.append(m[0])
        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        if min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.5)
    return urls

def is_pp_article(title, body_start):
    combined = (title + " " + body_start).lower()
    return any(ident in combined for ident in PP_IDENTIFIERS)

def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()

    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    full_text = content.get_text(" ", strip=True)
    body_start = full_text[:400]

    if not is_pp_article(title, body_start): return []

    pm_date = parse_date(body_start, None) or parse_date(title, None)
    if not pm_date: return []
    if pm_date < from_date or pm_date > to_date: return []

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
            ort = detect_ort(ort_m[1].strip()) if ort_m else detect_ort(body)
            kat, sev = categorize(titel + " " + body)
            incidents.append(_inc(pm_date, parse_time(body), kat, sev, ort, titel[:120], body[:1500], url))
        return incidents

    # Format 2: Paragraphen mit Orts-Markern (typisch OBN)
    paragraphs = content.find_all("p")
    current_ort = "Unbekannt"
    collected = []

    for p in paragraphs:
        text = p.get_text(" ", strip=True)
        if len(text) < 5: continue

        bold = p.find(["strong","b"])
        bold_text = bold.get_text(" ", strip=True) if bold else ""

        # Orts-Marker: Bold-Text der kurz ist und mit Großbuchstabe beginnt
        is_ort = bold_text and len(bold_text) < 80 and (
            ", Lkr." in bold_text or
            re.match(r'^[A-ZÄÖÜ][A-ZÄÖÜa-zäöüß]', bold_text) and len(bold_text.split()) <= 6
        )

        if is_ort:
            if collected:
                body = " ".join(collected)
                kat, sev = categorize(body)
                incidents.append(_inc(pm_date, parse_time(body), kat, sev, current_ort, collected[0][:120], body[:1500], url))
                collected = []
            ort = detect_ort(bold_text)
            current_ort = ort if ort != "Unbekannt" else bold_text[:60]
        elif len(text) > 30:
            collected.append(text)

    if collected:
        body = " ".join(collected)
        kat, sev = categorize(body)
        incidents.append(_inc(pm_date, parse_time(body), kat, sev, current_ort, collected[0][:120], body[:1500], url))

    # Fallback
    if not incidents and len(full_text) > 50:
        kat, sev = categorize(full_text)
        incidents.append(_inc(pm_date, "", kat, sev, detect_ort(full_text), title[:120], full_text[:1500], url))

    return incidents

def _inc(dt, time_str, kat, sev, ort, titel, volltext, link):
    return {
        "date": dt.strftime("%d.%m.%Y"), "dateSort": dt.strftime("%Y-%m-%d"),
        "time": time_str, "nr": "", "kategorie": kat, "schweregrad": sev,
        "ort": ort, "pp": PP_NAME, "region": PP_NAME,
        "titel": titel, "volltext": volltext, "link": link,
    }

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

    # URLs aus Archiv + Telegram sammeln
    urls = get_urls_from_archive(from_date, existing_links)
    urls += get_urls_from_telegram(existing_links | set(urls))
    print(f"  {len(urls)} neue URLs total\n")

    if len(urls) > MAX_NEW_PER_RUN:
        print(f"  ⚠ Verarbeite erste {MAX_NEW_PER_RUN}")
        urls = urls[:MAX_NEW_PER_RUN]

    all_incidents = list(existing)
    loaded = 0; consec_fails = 0

    for i, url in enumerate(urls):
        art_id = url.split("/")[-2]
        print(f"  [{i+1:3d}/{len(urls)}] {art_id}", end=" … ")
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
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}"
        if key not in seen: seen.add(key); deduped.append(inc)
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    if not partial:
        print(f"\n  ✅ {loaded} neue · {len(deduped)} Vorfälle → {DATA_FILE}")

if __name__ == "__main__": main()
