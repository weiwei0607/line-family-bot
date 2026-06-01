"""
LINE Family Bot — Centralized configuration.
"""

import os

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_GROUP_ID = os.environ.get("LINE_GROUP_ID", "")

# Validate required env vars at startup
_MISSING = [k for k, v in {
    "LINE_CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
    "LINE_CHANNEL_SECRET": LINE_CHANNEL_SECRET,
}.items() if not v]
if _MISSING:
    raise RuntimeError(f"Missing required env vars: {', '.join(_MISSING)}")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TMDB_KEY = os.environ.get("TMDB_KEY", "")
NASA_API_KEY = os.environ.get("NASA_API_KEY", "")
APININJAS_KEY = os.environ.get("APININJAS_KEY", "")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

FAMILY_SHEET_ID = os.environ.get("FAMILY_SHEET_ID", "")
POINTS_THRESHOLD = int(os.environ.get("POINTS_THRESHOLD", "5"))
CRON_SECRET = os.environ.get("CRON_SECRET", "")

LOCATION_LAT = os.environ.get("LOCATION_LAT", "25.04")
LOCATION_LON = os.environ.get("LOCATION_LON", "121.53")
WEATHER_CITY = os.environ.get("WEATHER_CITY", "Taipei")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
