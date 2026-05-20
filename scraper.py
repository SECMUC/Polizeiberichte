#!/usr/bin/env python3
"""
PP München + Umland OSINT – GitHub Actions Scraper
Unterstützt alle PP-Formate korrekt:
  - PP München:         ### NR. Titel – Stadtteil
  - PP Schwaben Nord:   0065 – Ort · Fließtext (kein h3)
  - PP Oberbayern Nord: ORT – Fließtext (kein h3, Großbuchstaben)
  - PP Oberbayern Süd:  ähnlich OBN
"""

import json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Konfiguration ─────────────────────────────────────────────────────────────
DAYS_BACK        = 500
MAX_ARTS         = 200   # Pro Lauf – inkrementell, täglich ergänzt
MAX_PAGES        = 50
SLEEP_SEC        = 1.2
MAX_CONSEC_FAILS = 8

BASE_URL    = "https://www.polizei.bayern.de"
TG_CHANNELS = ["PressePolizeiMuenchen", "PolizeiBayern"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

# ── PP-Erkennung aus Seitentitel ──────────────────────────────────────────────
PP_PATTERNS = [
    ("polizei münchen",  "PP München",          False),
    ("pp münchen",       "PP München",          False),
    ("oberbayern nord",  "PP Oberbayern Nord",  True),
    ("oberbayern süd",   "PP Oberbayern Süd",   True),
    ("schwaben nord",    "PP Schwaben Nord",     True),
    ("nordschwaben",     "PP Schwaben Nord",     True),
    ("schwaben süd",     "PP Schwaben Süd",      True),
    ("mittelfranken",    "PP Mittelfranken",     True),
    ("oberfranken",      "PP Oberfranken",       True),
    ("unterfranken",     "PP Unterfranken",      True),
    ("oberpfalz",        "PP Oberpfalz",         True),
    ("niederbayern",     "PP Niederbayern",      True),
    ("münchen",          "PP München",           False),
]

# ── Relevante Orte für gefilterte PPs ────────────────────────────────────────
RELEVANT_PLACES = [
    # Würmtal / PP Oberbayern Nord
    "Planegg","Martinsried","Krailling","Gräfelfing","Gauting","Neuried",
    "Germering","Stockdorf","Lochham","Würmtal",
    # Wörthsee / Starnberg / PP Oberbayern Süd
    "Wörthsee","Steinebach","Herrsching","Hechendorf","Walchstadt",
    "Andechs","Seefeld","Starnberg","Inning","Weßling","Pöcking",
    "Tutzing","Feldafing","Berg","Münsing","Wörthsee",
    # Friedberg / Aichach / PP Schwaben Nord
    "Friedberg","Kissing","Mering","Dasing","Aichach","Eurasburg",
    "Merching","Ried","Schmiechen","Steindorf","Adelzhausen",
    "Aichach-Friedberg","BAB A8","A 8","Autobahn A8",
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
    ("Prävention",       1, ["prävention","warnt","warnung","hinweis der polizei","fahrradcodier","terminhinweis","mobile wache"]),
]

# Stadtteil-Mapping
ORT_MAP = [
    # München
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
    ("Feldmoching-Hasenbergl","Feldmoching-Hasenbergl"),("Feldmoching","Feldmoching-Hasenbergl"),
    ("Hasenbergl","Feldmoching-Hasenbergl"),("Schwanthalerhöhe","Schwanthalerhöhe"),
    ("Thalkirchen","Thalkirchen"),("Ludwigsvorstadt","Ludwigsvorstadt"),("Isarvorstadt","Isarvorstadt"),
    ("Allach-Untermenzing","Allach-Untermenzing"),("Allach","Allach-Untermenzing"),
    ("Hauptbahnhof","Stadtmitte"),("Marienplatz","Stadtmitte"),("Stachus","Stadtmitte"),
    ("Karlsplatz","Stadtmitte"),("Innenstadt","Stadtmitte"),("Stadtmitte","Stadtmitte"),
    # Würmtal
    ("Planegg","Planegg"),("Martinsried","Martinsried"),("Krailling","Krailling"),
    ("Gräfelfing","Gräfelfing"),("Gauting","Gauting"),("Neuried","Neuried"),
    ("Germering","Germering"),("Stockdorf","Stockdorf"),("Lochham","Lochham"),
    # Wörthsee/Starnberg
    ("Wörthsee","Wörthsee"),("Steinebach","Steinebach"),("Herrsching","Herrsching"),
    ("Starnberg","Starnberg"),("Seefeld","Seefeld"),("Andechs","Andechs"),
    ("Inning","Inning"),("Weßling","Weßling"),("Tutzing","Tutzing"),("Pöcking","Pöcking"),
    # Friedberg/Aichach
    ("Friedberg","Friedberg"),("Kissing","Kissing"),("Mering","Mering"),
    ("Dasing","Dasing"),("Aichach","Aichach"),("Eurasburg","Eurasburg"),("Merching","Merching"),
    # Augsburg Stadtteile (für PP SWN Kontext)
    ("Innenstadt","Augsburg-Innenstadt"),("Oberhausen","Augsburg-Oberhausen"),
    ("Hochzoll","Augsburg-Hochzoll"),("Lechhausen","Augsburg-Lechhausen"),
    ("Haunstetten","Augsburg-Haunstetten"),("Göggingen","Augsburg-Göggingen"),
]


def detect_pp(title_text):
    t = title_text.lower()
    for pattern, pp_name, needs_filter in PP_PATTERNS:
        if pattern in t:
            return pp_name, needs_filter
    return None, False


def is_relevant(text):
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


def get_urls_from_telegram(channel):
    print(f"\n  📡 @{channel}…")
    art_pat = re.compile(r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html')
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')
    seen, urls, before_id = set(), [], None

    for page in range(MAX_PAGES):
        url = f"https://t.me/s/{channel}" + (f"?before={before_id}" if before_id else "")
        html = fetch(url, timeout=20)
        if not html: break
        new = sum(1 for m in art_pat.finditer(html) if m[0] not in seen and not seen.add(m[0]) and urls.append(m[0]) is None)
        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: break
        min_id = min(msg_ids)
        print(f"    Seite {page+1}: {new} neue Links (bis #{min_id})")
        if len(urls) >= MAX_ARTS * 3 or min_id <= 1 or min_id == before_id: break
        before_id = min_id
        time.sleep(0.5)

    print(f"    @{channel}: {len(urls)} Links")
    return urls


# ── Format-spezifische Parser ─────────────────────────────────────────────────

def parse_muenchen(content, pm_date, url):
    """PP München: ### NR. Titel – Stadtteil"""
    incidents = []
    for h in content.find_all("h3"):
        heading = h.get_text(" ", strip=True)
        num_m   = re.match(r"^(\d+)\.\s+", heading)
        nr      = num_m[1] if num_m else ""
        titel   = re.sub(r"^\d+\.\s+", "", heading).strip()
        ort_m   = re.search(r"–\s*(.+)$", titel)
        ort_raw = ort_m[1].strip() if ort_m else ""
        ort     = detect_ort(ort_raw) if ort_raw else "Unbekannt"

        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h3","h2","hr"): break
            parts.append(sib.get_text(" ", strip=True))
        body = " ".join(parts).strip()
        if len(body) < 30: continue

        inc_date = parse_date(body, pm_date)
        kat, sev = categorize(titel + " " + body)
        if ort == "Unbekannt": ort = detect_ort(body)

        incidents.append(_make(inc_date, parse_time(body), nr, kat, sev,
                               ort, titel[:120], body[:1500], url, "PP München"))
    return incidents


def parse_schwaben_nord(content, pm_date, url):
    """PP Schwaben Nord: 0065 – Ort · Fließtext, kein h3"""
    full = content.get_text("\n", strip=True)

    # Abschnitte durch nummeriertes Muster trennen: "0065 – " oder "· Ort –"
    # Alternativ: Vorfälle beginnen mit Ortsname gefolgt von " – "
    sections = re.split(r'\n(?=\d{4}\s*[–-])', full)
    if len(sections) <= 1:
        # Fallback: durch Zeilenumbrüche trennen wo Ortsname steht
        sections = re.split(r'\n(?=[A-ZÄÖÜ][a-zäöüß]+\s+[–-]\s)', full)

    incidents = []
    for sec in sections:
        sec = sec.strip()
        if len(sec) < 40: continue

        # Vorfall-Nummer extrahieren (z.B. "0065")
        nr_m = re.match(r'^(\d{4})\s*[–-]\s*', sec)
        nr   = nr_m[1] if nr_m else ""
        if nr_m: sec = sec[nr_m.end():]

        # Ort: steht vor " – " am Zeilenanfang
        ort_m = re.match(r'^([A-ZÄÖÜa-zäöüß/ -]+?)\s*[–-]\s*', sec)
        ort_raw = ort_m[1].strip() if ort_m else ""
        ort = detect_ort(ort_raw) if ort_raw else "Unbekannt"

        # Nur aufnehmen wenn relevanter Ort
        if not is_relevant(sec): continue

        # Titel: erste Zeile oder erster Satz
        titel = sec.split("\n")[0][:100] if "\n" in sec else sec[:100]
        body  = sec[:1500]

        inc_date = parse_date(body, pm_date)
        kat, sev = categorize(body)
        if ort == "Unbekannt": ort = detect_ort(body)

        incidents.append(_make(inc_date, parse_time(body), nr, kat, sev,
                               ort, titel, body, url, "PP Schwaben Nord"))
    return incidents


def parse_oberbayern(content, pm_date, url, pp_name):
    """PP Oberbayern Nord/Süd: ORT – Fließtext (oft ohne h3)"""
    sections = content.find_all("h3")

    if sections:
        # Hat h3 → ähnlich München-Format
        incidents = []
        for h in sections:
            heading = h.get_text(" ", strip=True)
            titel   = re.sub(r"^\d+\.\s+", "", heading).strip()
            ort_m   = re.search(r"–\s*(.+)$", titel)
            ort_raw = ort_m[1].strip() if ort_m else ""
            ort     = detect_ort(ort_raw) if ort_raw else "Unbekannt"

            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3","h2","hr"): break
                parts.append(sib.get_text(" ", strip=True))
            body = " ".join(parts).strip()
            if len(body) < 30: continue
            if not is_relevant(heading + " " + body): continue

            num_m = re.match(r"^(\d+)\.\s+", heading)
            nr = num_m[1] if num_m else ""
            inc_date = parse_date(body, pm_date)
            kat, sev = categorize(titel + " " + body)
            if ort == "Unbekannt": ort = detect_ort(body)
            incidents.append(_make(inc_date, parse_time(body), nr, kat, sev,
                                   ort, titel[:120], body[:1500], url, pp_name))
        return incidents

    # Kein h3 → Paragraphen parsen
    incidents = []
    for p in content.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) < 40: continue
        if not is_relevant(text): continue

        ort_m = re.match(r'^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß/ -]+?)\s*[–-]\s*', text)
        ort_raw = ort_m[1].strip() if ort_m else ""
        ort = detect_ort(ort_raw) if ort_raw else "Unbekannt"

        inc_date = parse_date(text, pm_date)
        kat, sev = categorize(text)
        if ort == "Unbekannt": ort = detect_ort(text)
        titel = text[:100]

        incidents.append(_make(inc_date, parse_time(text), "", kat, sev,
                               ort, titel, text[:1500], url, pp_name))
    return incidents


def parse_article(html, url, from_date, to_date):
    soup = BeautifulSoup(html, "html.parser")

    title_text = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    pp_name, needs_filter = detect_pp(title_text)
    if not pp_name: return []

    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title_text)
    if not dm: return []
    y = int(dm[3])
    if not (2020 <= y <= 2030): return []
    pm_date = datetime(y, int(dm[2]), int(dm[1]))
    if pm_date < from_date or pm_date > to_date: return []

    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    # Format-spezifisch parsen
    if pp_name == "PP München":
        sections = content.find_all("h3")
        if sections:
            return parse_muenchen(content, pm_date, url)
        else:
            # Einzelner Artikel ohne h3
            body = content.get_text(" ", strip=True)
            if len(body) < 50: return []
            kat, sev = categorize(body)
            return [_make(parse_date(body, pm_date), parse_time(body), "",
                          kat, sev, detect_ort(body), body[:120], body[:1500], url, "PP München")]

    elif pp_name == "PP Schwaben Nord":
        return parse_schwaben_nord(content, pm_date, url)

    else:  # PP Oberbayern Nord/Süd + andere
        return parse_oberbayern(content, pm_date, url, pp_name)


def _make(dt, time_str, nr, kat, sev, ort, titel, volltext, link, pp):
    return {
        "date":        dt.strftime("%d.%m.%Y"),
        "dateSort":    dt.strftime("%Y-%m-%d"),
        "time":        time_str,
        "nr":          nr,
        "kategorie":   kat,
        "schweregrad": sev,
        "ort":         ort,
        "pp":          pp,
        "region":      pp,
        "titel":       titel,
        "volltext":    volltext,
        "link":        link,
    }


def _save(all_incidents, from_date, to_date, loaded, partial=False):
    from collections import Counter
    all_incidents.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)
    seen, deduped = set(), []
    for inc in all_incidents:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)

    pp_counts = Counter(inc.get("pp","?") for inc in deduped)
    if not partial:
        print(f"\n  ✅ {loaded} neue Artikel · {len(deduped)} Vorfälle")
        for pp, cnt in sorted(pp_counts.items(), key=lambda x:-x[1]):
            print(f"     {pp}: {cnt}")

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
        "partial":     partial,
    }
    with open("data/meta.json","w",encoding="utf-8") as f:
        json.dump(meta,f,ensure_ascii=False,indent=2)

    if not partial:
        print(f"     → {os.path.getsize('data/incidents.json')//1024} KB")


def main():
    to_date   = datetime.now().replace(hour=23, minute=59, second=59)
    from_date = (to_date - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0)

    print(f"═══════════════════════════════════════════════════")
    print(f"  PP München + Umland OSINT Scraper")
    print(f"  Zeitraum: {from_date.date()} → {to_date.date()}")
    print(f"═══════════════════════════════════════════════════")

    # URLs aus Telegram
    all_urls = set()
    for ch in TG_CHANNELS:
        all_urls.update(get_urls_from_telegram(ch))
    urls = sorted(all_urls)
    print(f"\n  Gesamt: {len(urls)} URLs\n")

    # Bestehende Daten laden
    existing_data, existing_links = [], set()
    try:
        with open("data/incidents.json","r",encoding="utf-8") as f:
            existing_data = json.load(f)
        needs_rebuild = existing_data and "pp" not in existing_data[0]
        if needs_rebuild:
            print("  Altes Format – baue neu auf")
            existing_data, existing_links = [], set()
        else:
            existing_links = {p.get("link","") for p in existing_data}
            print(f"  Bestehend: {len(existing_data)} Vorfälle")
    except: print("  Starte frisch")

    all_incidents = list(existing_data)
    loaded = 0
    consec_fails = 0

    for i, url in enumerate(urls):
        if url in existing_links: continue

        art_id = url.split("/")[-2]
        print(f"  [{i+1:4d}/{len(urls)}] {art_id}", end=" … ")
        html = fetch(url)
        if not html or len(html) < 300:
            print("leer")
            consec_fails += 1
            if consec_fails >= MAX_CONSEC_FAILS:
                print(f"\n  ⚠ Server blockt – speichere und stoppe")
                break
            continue

        consec_fails = 0
        incidents = parse_article(html, url, from_date, to_date)
        if incidents:
            pps = set(inc["pp"] for inc in incidents)
            print(f"✓ {len(incidents)} [{', '.join(pps)}]")
            all_incidents.extend(incidents)
            existing_links.add(url)
            loaded += 1
        else:
            print("✗")

        if loaded > 0 and loaded % 30 == 0:
            _save(all_incidents, from_date, to_date, loaded, partial=True)
            print(f"  💾 Zwischenspeicherung ({loaded} neue)")

        time.sleep(SLEEP_SEC)

    _save(all_incidents, from_date, to_date, loaded)


if __name__ == "__main__":
    main()
