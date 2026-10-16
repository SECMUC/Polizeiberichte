"""Zentrale Konfiguration des Polizei-Collectors."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

BASE = "https://www.polizei.bayern.de"
LISTING_URL = f"{BASE}/aktuelles/pressemitteilungen/index.html"
SEARCH_URL = f"{BASE}/es/search"
SEARCH_REFERER = f"{BASE}/suche/presse/index.html"
ARTICLE_URL = BASE + "/aktuelles/pressemitteilungen/{id}/index.html"

# Erfasste Polizeipräsidien. "fokus" = Region München und Umgebung.
# og2k = interne Organisationskennung der Bayerischen Polizei (aus der Website).
PRAESIDIEN = {
    "PP München": {
        "name": "Polizeipräsidium München", "og2k": "0900800000000", "kurz": "MUC", "fokus": True,
    },
    "PP Oberbayern Nord": {
        "name": "Polizeipräsidium Oberbayern Nord", "og2k": "0900100000000", "kurz": "OBN", "fokus": True,
    },
    "PP Oberbayern Süd": {
        "name": "Polizeipräsidium Oberbayern Süd", "og2k": "0901700000000", "kurz": "OBS", "fokus": True,
    },
    "PP Schwaben Nord": {
        "name": "Polizeipräsidium Schwaben Nord", "og2k": "0900700000000", "kurz": "SWN", "fokus": False,
    },
}
NAME_TO_PP = {v["name"]: k for k, v in PRAESIDIEN.items()}
OG2K_TO_PP = {v["og2k"]: k for k, v in PRAESIDIEN.items()}

# Offizielle Telegram-Kanäle (nur Kanäle, die von der Polizei selbst betrieben werden)
TELEGRAM_CHANNELS = {
    "PressePolizeiMuenchen": "PP München",
}

# Offizielle X-Accounts. Wird nur genutzt, wenn das Secret X_BEARER_TOKEN gesetzt ist.
X_ACCOUNTS = {
    "PolizeiMuenchen": "PP München",
}
X_MAX_POSTS_PER_ACCOUNT = 50   # Kostenbremse pro Lauf

# Netzwerkverhalten
REQUEST_TIMEOUT = 25
REQUEST_PAUSE_SEC = 1.0        # Höflicher Abstand zwischen Abrufen
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Täglicher Lauf
DAILY_LOOKBACK_DAYS = 7        # Archivsuche: so viele Tage rückwirkend prüfen
REFRESH_RECENT_HOURS = 48      # Meldungen dieses Alters werden erneut geprüft (Korrekturen)
DEFAULT_BUDGET_MIN = 25        # Zeitbudget pro Lauf

# Plausibilität: Tatdatum darf höchstens so weit vor der Veröffentlichung liegen
MAX_TAT_VOR_PM_TAGE = 60
