"""Distance from home: look places up once on OpenStreetMap, then measure the straight line between them."""

import math
import re
import time

import requests

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "shortlist-job-tracker/2.0 (personal job search tool)"}
REMOTE_WORDS = ("remote", "anywhere", "worldwide", "home office", "telework")


def haversine_km(a, b):
    # Great circle distance between two (lat, lon) points in kilometres.
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


class Geocoder:
    """Looks up places on OpenStreetMap Nominatim and caches every answer in the database, also misses."""

    def __init__(self, con, get=requests.get, pause=1.0):
        self.con, self.get, self.pause, self._last = con, get, pause, 0.0
        con.execute("CREATE TABLE IF NOT EXISTS places (query TEXT PRIMARY KEY, lat REAL, lon REAL)")
        con.commit()

    def locate(self, place):
        q = " ".join(str(place or "").split()).lower()
        if not q or any(w in q for w in REMOTE_WORDS):
            return None
        row = self.con.execute("SELECT lat, lon FROM places WHERE query = ?", (q,)).fetchone()
        if row:
            return (row[0], row[1]) if row[0] is not None else None
        if self.get is None:
            return None
        # Job locations are towns, so look for a town first: a plain search for "Luxembourg City" finds an embassy in London.
        plain = re.sub(r"\b(?:city|centre|center|area|region|greater|metropolitan)\b", " ", q)
        plain = " ".join(plain.replace(" ,", ",").split()).strip(" ,")
        tries = [(q, "settlement")] + ([(plain, "settlement")] if plain and plain != q else []) + [(q, None)]
        point = None
        for query, kind in tries:
            try:
                hits = self._search(query, kind)
            except Exception:
                return None  # offline: try again next time
            if hits:
                point = (float(hits[0]["lat"]), float(hits[0]["lon"]))
                break
        self.con.execute("INSERT OR REPLACE INTO places (query, lat, lon) VALUES (?, ?, ?)", (q, *(point or (None, None))))
        self.con.commit()
        return point

    def _search(self, q, kind):
        wait = self.pause - (time.monotonic() - self._last)  # Nominatim asks for at most one request per second
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        params = {"q": q, "format": "json", "limit": 1, **({"featureType": kind} if kind else {})}
        return self.get(NOMINATIM, params=params, headers=HEADERS, timeout=10).json()

    def distance_km(self, home, place):
        a, b = self.locate(home), self.locate(place)
        return round(haversine_km(a, b)) if a and b else None

