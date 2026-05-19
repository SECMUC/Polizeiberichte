#!/usr/bin/env python3
"""
PP München + Umland OSINT – GitHub Actions Scraper
Quellen:
  - @PressePolizeiMuenchen (PP München)
  - @PolizeiBayern (RSS-Aggregator aller bayerischen PP – für OBN, OBS, SWN)
Filtert nach: München, Planegg/Würmtal, Wörthsee/Steinebach, Friedberg
"""

import json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# ── Konfiguration ─────────────────────────────────────────────────────────────
DAYS_BACK  = 500
MAX_ARTS   = 1500  # Hoch genug für alle Kanäle kombiniert
SLEEP_SEC  = 0.4
BASE_URL   = "https://www.polizei.bayern.de"

# Telegram-Kanäle die wir lesen
TG_CHANNELS = [
    "PressePolizeiMuenchen",  # PP München (offiziell)
    "PolizeiBayern",          # RSS-Aggregator aller bay. PP
]

# Ortsnamen für Filterung pro Region
# Artikel werden NUR aufgenommen wenn mindestens ein Begriff aus
# EINER der Regionsgruppen im Text vorkommt
REGIONS = {
    "München": [
        "München", "Schwabing", "Maxvorstadt", "Sendling", "Bogenhausen",
        "Haidhausen", "Neuhausen", "Nymphenburg", "Giesing", "Moosach",
        "Milbertshofen", "Pasing", "Hadern", "Laim", "Ramersdorf",
        "Perlach", "Trudering", "Feldmoching", "Hasenbergl", "Allach",
        "Hauptbahnhof München", "Marienplatz", "Ludwigsvorstadt",
        "Isarvorstadt", "Schwanthalerhöhe",
    ],
    "Planegg/Würmtal": [
        "Planegg", "Würmtal", "Martinsried", "Krailling", "Gräfelfing",
        "Gauting", "Neuried", "Germering", "Würm",
    ],
    "Wörthsee/Steinebach": [
        "Wörthsee", "Steinebach", "Herrsching", "Andechs", "Seefeld",
        "Hechendorf", "Walchstadt", "Starnberg", "Landkreis Starnberg",
    ],
    "Friedberg": [
        "Friedberg", "Aichach", "Kissing", "Mering", "Dasing",
        "Eurasburg", "Merching", "Landkreis Aichach-Friedberg",
        "Aichach-Friedberg",
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

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
    # Umland-Regionen
    ("Planegg","Planegg/Würmtal"),("Martinsried","Planegg/Würmtal"),
    ("Krailling","Planegg/Würmtal"),("Gräfelfing","Planegg/Würmtal"),
    ("Gauting","Planegg/Würmtal"),("Neuried","Planegg/Würmtal"),
    ("Germering","Planegg/Würmtal"),("Würmtal","Planegg/Würmtal"),
    ("Wörthsee","Wörthsee/Steinebach"),("Steinebach","Wörthsee/Steinebach"),
    ("Herrsching","Wörthsee/Steinebach"),("Hechendorf","Wörthsee/Steinebach"),
    ("Walchstadt","Wörthsee/Steinebach"),("Andechs","Wörthsee/Steinebach"),
    ("Seefeld","Wörthsee/Steinebach"),("Starnberg","Wörthsee/Steinebach"),
    ("Friedberg","Friedberg"),("Kissing","Friedberg"),("Mering","Friedberg"),
    ("Dasing","Friedberg"),("Aichach","Friedberg"),("Eurasburg","Friedberg"),
    ("Grünwald","Münchner Umland"),("Sauerlach","Münchner Umland"),("Haar","Münchner Umland"),
    ("Dachau","Münchner Umland"),("Unterhaching","Münchner Umland"),
    ("Landkreis","Münchner Umland"),
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


def detect_region(text):
    """Erkennt welcher Region ein Artikel zuzuordnen ist."""
    for region, keywords in REGIONS.items():
        if any(kw in text for kw in keywords):
            return region
    return None  # Artikel nicht relevant


def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status(); r.encoding = "utf-8"; return r.text
    except Exception as e:
        print(f"  ✗ {url[-60:]} → {e}"); return None


def get_urls_from_telegram(channel, from_date, to_date):
    """Liest einen Telegram-Kanal seitenweise und sammelt ALLE polizei.bayern.de Links."""
    print(f"\n  📡 Lese @{channel}…")
    art_pat = re.compile(
        r'https?://(?:www\.)?polizei\.bayern\.de/aktuelles/pressemitteilungen/(\d{6})/index\.html'
    )
    msg_pat = re.compile(r'data-post="[^/]+/(\d+)"')

    seen, urls, before_id = set(), [], None

    for page in range(100):
        url = f"https://t.me/s/{channel}" + (f"?before={before_id}" if before_id else "")
        html = fetch(url, timeout=25)
        if not html: print(f"    Seite {page+1}: nicht erreichbar"); break

        new_count = 0
        for m in art_pat.finditer(html):
            art_url = m.group(0)
            if art_url not in seen:
                seen.add(art_url)
                urls.append(art_url)
                new_count += 1

        msg_ids = [int(x) for x in msg_pat.findall(html)]
        if not msg_ids: print(f"    Seite {page+1}: Ende des Kanals"); break

        min_msg_id = min(msg_ids)
        print(f"    Seite {page+1}: {new_count} neue Links (Post-IDs bis #{min_msg_id})")

        if len(urls) >= MAX_ARTS: print(f"    Maximum erreicht"); break
        if min_msg_id <= 1: break
        if min_msg_id == before_id: break

        before_id = min_msg_id
        time.sleep(0.6)

    print(f"    @{channel}: {len(urls)} Links gesammelt")
    return urls


def parse_article(html, url):
    """Parst eine Pressemitteilung → Liste von Vorfall-Dicts."""
    soup = BeautifulSoup(html, "html.parser")
    title_text = (soup.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", title_text)
    if not dm: return []
    pm_date = datetime(int(dm[3]), int(dm[2]), int(dm[1]))

    # ── Primärfilter über Seitentitel ────────────────────────────────────────
    # "Medieninformation der Polizei München" → München-Artikel
    # "Medieninfo Nordschwaben", "Medieninfo Oberbayern Nord" → andere PP
    # Wir bestimmen welches PP diesen Artikel herausgegeben hat
    title_lower = title_text.lower()
    is_munich_pp = "polizei münchen" in title_lower or "münchen" in title_lower and "nordschwaben" not in title_lower and "schwaben" not in title_lower and "oberbayern nord" not in title_lower and "oberbayern süd" not in title_lower and "niederbayern" not in title_lower and "oberpfalz" not in title_lower and "oberfranken" not in title_lower and "mittelfranken" not in title_lower and "unterfranken" not in title_lower

    for tag in soup(["nav","header","footer","script","style"]): tag.decompose()
    content = soup.find(class_="c-richtext") or soup.find("article") or soup.find("main")
    if not content: return []

    # Fußzeile mit Behördenname entfernen (letzte 300 Zeichen oft "Rückfragen bitte an: PP XYZ")
    full_text = content.get_text(" ", strip=True)

    # Fußzeile abschneiden (nach "Rückfragen bitte" oder "Pressestelle")
    cutoff = re.search(r'Rückfragen bitte an|Pressestelle|Telefon:\s*\d', full_text)
    text_for_region = full_text[:cutoff.start()] if cutoff else full_text

    # ── Regionserkennung ─────────────────────────────────────────────────────
    # München-Artikel vom PP München: alle Vorfälle sind automatisch München
    # Andere PP: nur aufnehmen wenn Orte unserer Umlandregionen vorkommen
    if is_munich_pp:
        # PP München Artikel → direkt parsen, alle Vorfälle sind relevant
        article_region_override = "München"
    else:
        # Anderes PP → nur wenn Umland-Orte im Text
        umland_regions = {k: v for k, v in REGIONS.items() if k != "München"}
        found_region = None
        for region, keywords in umland_regions.items():
            if any(kw in text_for_region for kw in keywords):
                found_region = region
                break
        if not found_region:
            return []  # Artikel aus anderem PP ohne Umland-Bezug → überspringen
        article_region_override = None  # Einzelvorfälle bestimmen ihre Region selbst

    incidents = []
    sections  = content.find_all("h3")

    if not sections:
        kat, sev = categorize(full_text)
        dm2 = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", full_text)
        inc_date = datetime(int(dm2[3]),int(dm2[2]),int(dm2[1])) if dm2 else pm_date
        tm = re.search(r"(\d{1,2})[:.h](\d{2})\s*Uhr", full_text)
        region = article_region_override or detect_region(text_for_region) or "Unbekannt"
        ort = detect_ort(full_text)
        if ort == "Unbekannt": ort = region
        return [_make(inc_date, f"{int(tm[1]):02d}:{tm[2]}" if tm else "",
                      "", kat, sev, ort, full_text[:120], full_text[:1500], url, region)]

    for h in sections:
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

        vorfall_text = titel + " " + body

        if article_region_override:
            # PP München → alle Vorfälle sind München
            vorfall_region = article_region_override
        else:
            # Anderes PP → Einzelvorfall muss Umland-Ort enthalten
            vorfall_region = None
            for region, keywords in REGIONS.items():
                if region == "München": continue  # München aus anderem PP nicht aufnehmen
                if any(kw in vorfall_text for kw in keywords):
                    vorfall_region = region
                    break
            if not vorfall_region:
                continue  # Dieser Einzelvorfall betrifft unsere Umlandregionen nicht

        dm2 = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", body)
        inc_date = datetime(int(dm2[3]),int(dm2[2]),int(dm2[1])) if dm2 else pm_date
        tm = re.search(r"(\d{1,2})[:.h](\d{2})\s*Uhr", body)
        kat, sev = categorize(vorfall_text)
        if ort == "Unbekannt": ort = detect_ort(body)
        if ort == "Unbekannt": ort = vorfall_region

        incidents.append(_make(
            inc_date, f"{int(tm[1]):02d}:{tm[2]}" if tm else "",
            nr, kat, sev, ort, titel[:120], body[:1500], url, vorfall_region
        ))

    return incidents


def _make(dt, time_str, nr, kat, sev, ort, titel, volltext, link, region):
    return {
        "date":        dt.strftime("%d.%m.%Y"),
        "dateSort":    dt.strftime("%Y-%m-%d"),
        "time":        time_str,
        "nr":          nr,
        "kategorie":   kat,
        "schweregrad": sev,
        "ort":         ort,
        "region":      region,
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
    print(f"  Regionen: {', '.join(REGIONS.keys())}")
    print(f"═══════════════════════════════════════════════════")

    # 1. URLs aus allen Telegram-Kanälen sammeln – global dedupliziert
    all_urls = set()
    for channel in TG_CHANNELS:
        urls = get_urls_from_telegram(channel, from_date, to_date)
        all_urls.update(urls)

    urls = sorted(all_urls)[:MAX_ARTS]
    print(f"\n  Gesamt: {len(urls)} einzigartige Artikel-URLs\n")
    print(f"\n  Gesamt: {len(urls)} einzigartige Artikel-URLs\n")

    # 2. Bestehende Daten laden
    existing_data  = []
    existing_links = set()
    try:
        with open("data/incidents.json", "r", encoding="utf-8") as f:
            existing_data  = json.load(f)
            existing_links = {p.get("link","") for p in existing_data}
            print(f"  Bestehende Daten: {len(existing_data)} Vorfälle")
    except:
        print("  Kein bestehender Datensatz – starte frisch")

    # 3. Neue Artikel abrufen
    all_incidents = list(existing_data)
    loaded = 0

    for i, url in enumerate(urls):
        if url in existing_links:
            continue  # Bereits bekannt → überspringen

        art_id = url.split("/")[-2]
        print(f"  [{i+1:3d}/{len(urls)}] {art_id}", end=" … ")
        html = fetch(url)
        if not html or len(html) < 300: print("leer"); continue

        # Datumscheck
        soup_q = BeautifulSoup(html[:2000],"html.parser")
        t = (soup_q.find("title") or type("",(),{"get_text":lambda *a:""})()).get_text()
        dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", t)
        if dm:
            ad = datetime(int(dm[3]),int(dm[2]),int(dm[1]))
            if ad < from_date or ad > to_date:
                print(f"außerhalb ({ad.date()})"); continue

        incidents = parse_article(html, url)
        if incidents:
            regions = set(inc.get("region","?") for inc in incidents)
            print(f"✓ {len(incidents)} Vorfälle [{', '.join(regions)}]")
            all_incidents.extend(incidents)
            existing_links.add(url)
            loaded += 1
        else:
            print("✗ nicht relevant")

        time.sleep(SLEEP_SEC)

    # 4. Sortieren & Deduplizieren
    all_incidents.sort(key=lambda x:(x.get("dateSort",""),x.get("time","")),reverse=True)
    seen, deduped = set(), []
    for inc in all_incidents:
        key = f"{inc.get('dateSort','')}|{inc.get('titel','')[:60]}|{inc.get('nr','')}"
        if key not in seen: seen.add(key); deduped.append(inc)
    all_incidents = deduped

    # Statistik
    from collections import Counter
    region_counts = Counter(inc.get("region","?") for inc in all_incidents)
    print(f"\n  ✅ {loaded} neue Artikel · {len(all_incidents)} Vorfälle gesamt")
    for reg, cnt in sorted(region_counts.items()):
        print(f"     {reg}: {cnt}")

    # 5. Speichern
    Path("data").mkdir(exist_ok=True)
    with open("data/incidents.json","w",encoding="utf-8") as f:
        json.dump(all_incidents,f,ensure_ascii=False,indent=2)

    meta = {
        "updated":     datetime.now().strftime("%d.%m.%Y %H:%M"),
        "updated_iso": datetime.now().isoformat(),
        "from_date":   from_date.strftime("%Y-%m-%d"),
        "to_date":     to_date.strftime("%Y-%m-%d"),
        "articles":    loaded,
        "incidents":   len(all_incidents),
        "regions":     dict(region_counts),
    }
    with open("data/meta.json","w",encoding="utf-8") as f:
        json.dump(meta,f,ensure_ascii=False,indent=2)

    print(f"     → data/incidents.json ({os.path.getsize('data/incidents.json')//1024} KB)")


if __name__ == "__main__":
    main()
