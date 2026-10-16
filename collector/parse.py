"""Zerlegt eine Pressemitteilung von polizei.bayern.de in einzelne Meldungen.

Grundsatz: Es wird nur übernommen, was wörtlich im Dokument steht.
Felder, die sich nicht eindeutig bestimmen lassen, bleiben leer (None) –
es wird nichts geraten oder ergänzt.
"""
import hashlib
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup, NavigableString, Tag

from . import config


class ParseError(Exception):
    pass


STOP_SECTIONS = {"bp-searchfield", "bp-icon-list", "bp-infobox", "bp-contentpool",
                 "bp-linklist", "bp-carousel"}
SKIP_SECTIONS = {"bp-breadcrumb", "bp-page-date", "bp-autotoc"}
BLOCK_TAGS = {"p", "h2", "h3", "h4", "h5", "li", "bp-headline"}

NUM_HEAD = re.compile(r"^\s*(\d{1,4})\s*(?:\.|–|—|-)\s*(\S.*)$")
DASH_SPLIT = re.compile(r"\s+[–—]\s+")
PAGE_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*,\s*(Polizeipräsidium[^\n]+)")
MONATE = {m: i + 1 for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
     "september", "oktober", "november", "dezember"])}
DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d{2})(?!\d)")
DATE_LONG = re.compile(r"(?<!\d)(\d{1,2})\.\s*(" + "|".join(MONATE) + r")\s+(20\d{2})", re.I)
TIME = re.compile(r"(?<![\d.,])([01]?\d|2[0-3])[:.]([0-5]\d)\s*Uhr")
ORT_BODY = re.compile(r"^([A-ZÄÖÜ][\wÄÖÜäöüß./()\- ]{1,45}?)\s+(?:–|—|--|-)\s+\S")
ORT_DATELINE = re.compile(r"^([A-ZÄÖÜ][A-ZÄÖÜ\-/ ]{2,45}?)\s*(?:,|\.\s|_)")


def _norm(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip()


def _section_classes(tag: Tag) -> set:
    out = set()
    for sec in tag.find_parents("section"):
        out.update(sec.get("class", []))
    return out


def _is_heading(tag: Tag, text: str) -> bool:
    if tag.name == "bp-headline" or tag.name in ("h2", "h3", "h4", "h5"):
        return True
    if len(text) > 260:
        return False
    strong = "".join(s.get_text(" ", strip=True) for s in tag.find_all(["strong", "b"]))
    return len(strong) >= 0.6 * len(text.replace(" ", "")) if text else False


def _heading_text(tag: Tag) -> tuple[str, str]:
    """(Überschrift, Zusatz) – bei fetten Absätzen ist der Zusatz der nicht-fette Rest."""
    if tag.name == "bp-headline":
        return _norm(tag.get("title", "")), ""
    if tag.name.startswith("h"):
        return _norm(tag.get_text(" ", strip=True)), ""
    head = _norm(" ".join(s.get_text(" ", strip=True) for s in tag.find_all(["strong", "b"])))
    full = _norm(tag.get_text(" ", strip=True))
    rest = _norm(full.replace(head, "", 1)) if head and full.startswith(head[:20]) else ""
    return head, rest


def _blocks(main: Tag, page_title: str):
    blocks = []
    for tag in main.find_all(True):
        if tag.name not in BLOCK_TAGS:
            continue
        secs = _section_classes(tag)
        if secs & STOP_SECTIONS:
            break
        if secs & SKIP_SECTIONS:
            continue
        if tag.find_parent(["p", "li", "h2", "h3", "h4", "h5"]):
            continue
        if tag.name == "li" and tag.find("p"):
            continue
        if tag.name == "bp-headline":
            text = _norm(tag.get("title", ""))
        else:
            text = _norm(tag.get_text("\n" if tag.find("br") else " ", strip=True))
        if not text:
            continue
        if tag.name == "bp-headline" and text == page_title:
            continue
        if _is_heading(tag, text):
            head, rest = _heading_text(tag)
            structural = tag.name == "bp-headline" or tag.name.startswith("h")
            blocks.append({"kind": "head", "text": head or text, "rest": rest,
                           "structural": structural, "full": text})
        else:
            blocks.append({"kind": "text", "text": text})
    return blocks


def _ort_from_heading(head: str):
    parts = DASH_SPLIT.split(head)
    if len(parts) < 2:
        return None
    cand = parts[-1].strip()
    if 2 <= len(cand) <= 45 and not re.search(r"\d|;", cand) and len(cand.split()) <= 5:
        return cand
    return None


def _ort_from_body(body: str):
    first = body.split("\n", 1)[0][:120]
    m = ORT_DATELINE.match(first)
    if m and m[1].strip().isupper() and len(m[1].strip()) >= 3:
        return m[1].strip()
    m = ORT_BODY.match(first)
    if m:
        cand = m[1].strip()
        if len(cand.split()) <= 4 and not re.match(r"^(Am|Im|In|Seit|Bereits|Gegen|Nach|Wie)\b", cand):
            return cand
    return None


DATELINE_DATE = re.compile(r"^[^\n]{0,60}?,\s*\d{1,2}\.\d{1,2}\.20\d{2}\s*_")


def _tatdatum(body: str, pm_date: date):
    head = DATELINE_DATE.sub("", body[:460], count=1)[:400]
    found = []
    for m in DATE_NUM.finditer(head):
        try:
            found.append((m.start(), date(int(m[3]), int(m[2]), int(m[1]))))
        except ValueError:
            pass
    for m in DATE_LONG.finditer(head):
        try:
            found.append((m.start(), date(int(m[3]), MONATE[m[2].lower()], int(m[1]))))
        except ValueError:
            pass
    lo = pm_date - timedelta(days=config.MAX_TAT_VOR_PM_TAGE)
    hi = pm_date + timedelta(days=1)
    for _, d in sorted(found):
        if lo <= d <= hi:
            return d
    return None


def _uhrzeit(body: str):
    m = TIME.search(body[:400])
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def parse_article(html: str, pm_id: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(id="readspeaker_lesen")
    if not main:
        raise ParseError("Inhaltsbereich fehlt")

    pd_sec = main.select_one("section.bp-page-date")
    m = PAGE_DATE.search(_norm(pd_sec.get_text(" ", strip=True))) if pd_sec else None
    if not m:
        raise ParseError("Datum/Präsidium im Kopf nicht gefunden")
    pm_date = date(int(m[3]), int(m[2]), int(m[1]))
    pp_name = _norm(m[4])
    pp = config.NAME_TO_PP.get(pp_name)

    h1 = main.find("bp-headline", attrs={"size": "h1"})
    title = _norm(h1.get("title", "")) if h1 else ""
    if not title and soup.title:
        title = _norm(soup.title.get_text()).replace("Die Bayerische Polizei - ", "")

    blocks = _blocks(main, title)
    full_text = "\n".join(b.get("full") or b["text"] for b in blocks)

    meldungen = []
    numbered = [b for b in blocks if b["kind"] == "head" and NUM_HEAD.match(b["text"])]
    if numbered:
        current, abschnitt = None, None
        for b in blocks:
            nm = NUM_HEAD.match(b["text"]) if b["kind"] == "head" else None
            if b["kind"] == "head" and (nm or b["structural"]):
                if current:
                    meldungen.append(current)
                    current = None
                if nm:
                    current = {"nr": nm[1], "titel": _norm(nm[2]), "abschnitt": abschnitt,
                               "body": [b["rest"]] if b.get("rest") else []}
                else:
                    abschnitt = b["text"]
            elif current is not None:
                current["body"].append(b.get("full") or b["text"])
        if current:
            meldungen.append(current)
        # Inhaltsverzeichnis-Dubletten: pro Nummer die Fassung mit dem längsten Text behalten
        best = {}
        for mm in meldungen:
            mm["text"] = _norm("\n".join(mm.pop("body")))
            if mm["nr"] not in best or len(mm["text"]) > len(best[mm["nr"]]["text"]):
                best[mm["nr"]] = mm
        meldungen = [mm for mm in best.values() if len(mm["text"]) >= 20]
    else:
        body = _norm("\n".join((b.get("full") or b["text"]) for b in blocks if not (b["kind"] == "head" and b["text"] == title)))
        if len(body) >= 20:
            meldungen = [{"nr": None, "titel": title, "abschnitt": None, "text": body}]

    out = []
    for mm in meldungen:
        # "Titel – Ort" ist das feste Überschriftenformat des PP München
        ort, ort_q = (_ort_from_heading(mm["titel"]), "ueberschrift") if pp == "PP München" else (None, None)
        if not ort:
            ort, ort_q = _ort_from_body(mm["text"]), "text"
        if not ort:
            ort_q = None
        tat = _tatdatum(mm["text"], pm_date)
        out.append({
            "id": f"{pm_id}-{mm['nr'] or 0}",
            "pm_id": pm_id,
            "nr": mm["nr"],
            "pp": pp,
            "veroeffentlicht": pm_date.isoformat(),
            "tatdatum": tat.isoformat() if tat else None,
            "uhrzeit": _uhrzeit(mm["text"]) if tat else None,
            "titel": mm["titel"],
            "ort": ort,
            "ort_quelle": ort_q,
            "abschnitt": mm["abschnitt"],
            "text": mm["text"],
            "url": url,
        })

    pm = {
        "id": pm_id,
        "url": url,
        "pp": pp,
        "pp_name": pp_name,
        "veroeffentlicht": pm_date.isoformat(),
        "titel": title,
        "text": full_text,
        "sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
        "anzahl_meldungen": len(out),
    }
    return pm, out
