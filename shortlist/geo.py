"""Distance from home: look places up once on OpenStreetMap, then measure the straight line between them."""

import json
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

    def locate(self, place, near=None):
        """`near` is a point: a name without a country ("Belval") then means the place of that name nearest to it."""
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
                hits = self._search(query, kind, 8 if near and "," not in q else 1)
            except Exception:
                return None  # offline: try again next time
            if hits:
                spots = [(float(h["lat"]), float(h["lon"])) for h in hits]
                point = min(spots, key=lambda s: haversine_km(near, s)) if near else spots[0]
                break
        self.con.execute("INSERT OR REPLACE INTO places (query, lat, lon) VALUES (?, ?, ?)", (q, *(point or (None, None))))
        self.con.commit()
        return point

    def _search(self, q, kind, limit=1):
        wait = self.pause - (time.monotonic() - self._last)  # Nominatim asks for at most one request per second
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        params = {"q": q, "format": "json", "limit": limit, **({"featureType": kind} if kind else {})}
        return self.get(NOMINATIM, params=params, headers=HEADERS, timeout=10).json()

    def distance_km(self, home, place):
        a = self.locate(home)
        b = self.locate(place, near=a)
        return round(haversine_km(a, b)) if a and b else None



ROUTER = "https://routing.openstreetmap.de"
MODES = {"car": ("routed-car", "driving"), "bike": ("routed-bike", "cycling"), "walk": ("routed-foot", "walking")}


class Router:
    """Travel time and the way there, by car, bike or on foot, from the OpenStreetMap routing servers. Every answer is kept."""

    def __init__(self, con, get=requests.get):
        self.con, self.get = con, get
        con.execute("CREATE TABLE IF NOT EXISTS routes (key TEXT PRIMARY KEY, minutes REAL, km REAL, line TEXT)")
        con.commit()

    def route(self, a, b, mode="car", fetch=True):
        """{"minutes", "km", "line": [[lat, lon], ...]} from a to b, or None."""
        if not a or not b or mode not in MODES:
            return None
        key = f"{mode}:{a[0]:.4f},{a[1]:.4f}:{b[0]:.4f},{b[1]:.4f}"
        row = self.con.execute("SELECT minutes, km, line FROM routes WHERE key = ?", (key,)).fetchone()
        if row:
            return {"minutes": row[0], "km": row[1], "line": json.loads(row[2])} if row[0] is not None else None
        if self.get is None or not fetch:
            return None
        server, profile = MODES[mode]
        try:
            r = self.get(f"{ROUTER}/{server}/route/v1/{profile}/{a[1]},{a[0]};{b[1]},{b[0]}",
                         params={"overview": "simplified", "geometries": "geojson"}, headers=HEADERS, timeout=15).json()
        except Exception:
            return None  # offline: try again next time
        out = None
        if r.get("code") == "Ok" and r.get("routes"):
            best = r["routes"][0]
            out = {"minutes": round(best["duration"] / 60), "km": round(best["distance"] / 1000, 1),
                   "line": [[round(y, 5), round(x, 5)] for x, y in best["geometry"]["coordinates"]]}
        self.con.execute("INSERT OR REPLACE INTO routes (key, minutes, km, line) VALUES (?, ?, ?, ?)",
                         (key, out and out["minutes"], out and out["km"], json.dumps(out["line"] if out else [])))
        self.con.commit()
        return out
