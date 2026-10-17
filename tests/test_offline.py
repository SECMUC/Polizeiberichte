"""Offline-Test: Collector gegen gespeicherte HTML-Proben (tests/samples) ohne Netzwerk."""
import json, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector import config, sources, __main__ as cli  # noqa: E402

SAMPLES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "samples"


def run():
    tmp = Path(tempfile.mkdtemp())
    config.DATA = tmp
    ids = sorted(p.stem for p in SAMPLES.glob("*.html") if p.stem.isdigit())
    sources.discover_listing = lambda http: ([{"id": i, "pp": None, "ts": None, "titel": None} for i in ids], len(ids))
    sources.discover_archive = lambda http, pp, a, b: ([], [])
    sources.discover_telegram = lambda http, ch, max_pages=3: []
    sources.fetch_article = lambda http, i: (SAMPLES / f"{i}.html").read_text(encoding="utf-8")
    rc = cli.main(["--budget-min", "5"])
    idx = json.loads((tmp / "index.json").read_text())
    mel = [r for f in (tmp / "meldungen").glob("*.json") for r in json.loads(f.read_text())]
    assert rc == 0, rc
    assert idx["summen"]["pressemitteilungen"] == len(ids), idx["summen"]
    assert all(r["url"].startswith("https://www.polizei.bayern.de/") for r in mel)
    for r in mel:
        if r["tatdatum"]:
            assert r["tatdatum"] <= r["veroeffentlicht"] or r["tatdatum"][:7] == r["veroeffentlicht"][:7], r["id"]
    # Zweiter Lauf darf nichts duplizieren
    cli.main(["--budget-min", "5"])
    mel2 = [r for f in (tmp / "meldungen").glob("*.json") for r in json.loads(f.read_text())]
    assert len(mel2) == len(mel)
    import importlib.util
    spec = importlib.util.spec_from_file_location("validate", ROOT / "tools" / "validate.py")
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    assert v.main() == 0, "Validierung fehlgeschlagen"
    print(f"OK: {len(ids)} Dokumente → {len(mel)} Meldungen")
    from collections import Counter
    print(Counter(r["kategorie"] for r in mel).most_common())
    shutil.rmtree(tmp)


if __name__ == "__main__":
    run()
