"""Looking for jobs: ask several public job sites for the job titles and places in your profile, and keep what was found.

Every source is asked the way a visitor's browser asks it: one request per job title, a second apart, no account and
no way around a block. A site that answers with a captcha or a login wall is simply not a source (Indeed, Monster and
Moovijob do that). The sources run side by side, so a full search is a few dozen requests and takes some seconds."""

import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup

from . import db, ingest
from .extract import DOMAIN_RULES, _first
from .score import LU, NL, wanted

LINKEDIN = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
EURES = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
EFC = "https://job-search-api.efinancialcareers.com/v1/efc/jobs/search"
# LinkedIn's own levels: 1 internship, 2 entry level, 3 associate, 4 mid-senior.
LEVEL_CODES = {"intern": ["1"], "junior": ["2", "3"], "mid": ["3", "4"], "senior": ["4"]}
MAX_ROLES, MAX_PLACES, MAX_PER_SOURCE = 4, 2, 40
READY_TEXT = 400  # a description this long that came with the search result counts as the posting itself

# Country code: name, three letter code, capital (latitude, longitude), and the words that mean this country.
COUNTRIES = {
    "lu": ("Luxembourg", "LUX", 49.6117, 6.1319, LU + r"|luxemb|l[ëe]tzebuerg"),
    "de": ("Germany", "DEU", 52.52, 13.405, r"germany|deutschland|allemagne|berlin|munich|m[üu]nchen|frankfurt|hamburg|cologne|k[öo]ln|trier|saarbr"),
    "fr": ("France", "FRA", 48.8566, 2.3522, r"france|frankreich|paris|lyon|metz|thionville|nancy|strasbourg"),
    "be": ("Belgium", "BEL", 50.8503, 4.3517, r"belgi|brussel|bruxelles|arlon|li[eè]ge|antwerp|ghent|\bgent\b"),
    "nl": ("Netherlands", "NLD", 52.3676, 4.9041, r"nederland|pays-bas|holland|" + NL),
    "ch": ("Switzerland", "CHE", 46.948, 7.4474, r"switzerland|schweiz|suisse|z[üu]rich|gen[eè]ve|geneva|basel|\bbern\b|lausanne"),
    "at": ("Austria", "AUT", 48.2082, 16.3738, r"austria|[öo]sterreich|autriche|vienna|wien|graz|linz|salzburg"),
}


def country_of(place):
    """The country code a place name belongs to, or "" when the name says nothing this module knows."""
    return next((cc for cc, c in COUNTRIES.items() if re.search(c[4], place or "", re.I)), "")


# Telling the same job apart from a different one, and a job you asked for from one that only shares a word

_GENDER = re.compile(r"\(?\s*\b[mfhwdxn](?:\s*/\s*[mfhwdxn]){1,2}\b\s*\)?|\(\s*(?:all genders|gn)\s*\)", re.I)
_LEGAL = re.compile(r"\b(?:s\.?\s?[àa]\.?\s?r\.?\s?l|sarl|s\.?a|gmbh|ag|ltd|llc|inc|plc|sas|se|group|groupe|luxembourg|europe|eu)\b\.?", re.I)
_NO_NAME = re.compile(r"non renseign|not specified|not available|confidenti|unknown|^n/?a$|^-*$", re.I)
_DATA_WORD = re.compile(r"\bdata\b|donn[ée]es|daten|\bbi\b|analytics|statisti|quantitat|insight|intelligence", re.I)
# The same job word in French and German, so "Analyste de données" answers a search for "Data Analyst".
OTHER_WORDS = {"data": ["données", "donnees", "daten"], "analyst": ["analyste", "analytiker"], "scientist": ["scientifique"],
               "engineer": ["ingénieur", "ingenieur"], "developer": ["développeur", "developpeur", "entwickler"],
               "consultant": ["berater"], "researcher": ["chercheur", "forscher"], "accountant": ["comptable", "buchhalter"],
               "lawyer": ["juriste", "avocat", "jurist"], "nurse": ["infirmier", "infirmière", "pfleger"],
               "teacher": ["enseignant", "lehrer"], "designer": ["concepteur"], "manager": ["responsable", "gestionnaire", "leiter"]}


def clean_title(title):
    """A job title without the "(m/f/d)" kind of mark, which every site writes its own way."""
    t = " ".join(_GENDER.sub(" ", (title or "").replace("⁠", "")).split())
    return t.strip(" -–|,/") or " ".join((title or "").split())


def _fold(s):
    """Lower case and without accents, so "à Luxembourg" and "a Luxembourg" are one spelling."""
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))


def same_key(company, title):
    """Company and title boiled down to what two sites would agree on. None when the company is not named."""
    co = re.sub(r"[^a-z0-9]", "", _LEGAL.sub(" ", re.sub(r"\([^)]*\)", " ", _fold(company))))
    ti = re.sub(r"[^a-z0-9]", "", _fold(clean_title(title)))
    return (co, ti) if co and ti else None


class Seen:
    """The jobs met so far. The same title at the same company is the same job, and "CSSF - Commission de Surveillance
    du Secteur Financier" is the same company as "Commission de Surveillance du Secteur Financier"."""

    def __init__(self, pairs=()):
        self.by_title = {}
        for company, title in pairs:
            self.add(company, title)

    def add(self, company, title):
        if key := same_key(company, title):
            self.by_title.setdefault(key[1], []).append(key[0])

    def has(self, company, title):
        key = same_key(company, title)
        return bool(key) and any(c in key[0] or key[0] in c for c in self.by_title.get(key[1], []))


def relevant(title, profile):
    """Is this title one of the jobs the profile asks for? Used for the sites whose own search matches any one word."""
    w, t = wanted(profile), (title or "").lower()
    field = _first(DOMAIN_RULES, t)
    if field in w["domains"] and (field != "analytics" or _DATA_WORD.search(t)):
        return True  # "KYC Analyst" is an analyst too, but not the kind somebody looking for data jobs means
    words = re.findall(r"[a-zà-ÿ]+", t)

    def has(word):
        return any(x == v if len(v) <= 4 else x.startswith(v[:7]) for v in [word, *OTHER_WORDS.get(word, [])] for x in words)
    return any(role and all(has(x) for x in role) for role in w["titles"])


MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _day(value, today=None):
    """The day a listing was posted as YYYY-MM-DD, from whatever the site wrote: "09 Nov", "1 Day Ago", "23/09", a timestamp."""
    today, s = today or date.today(), " ".join(str(value or "").split()).lower()

    def near(day, month):  # a date without a year is the latest one that is not in the future
        try:
            d = date(today.year, month, day)
            return (d if d <= today + timedelta(days=2) else date(today.year - 1, month, day)).isoformat()
        except ValueError:
            return ""
    if not s:
        return ""
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    if re.fullmatch(r"\d{12,14}", s):
        return datetime.fromtimestamp(int(s) / 1000).date().isoformat()
    if re.search(r"today|hour|minute|just now", s):
        return today.isoformat()
    if "yesterday" in s:
        return (today - timedelta(days=1)).isoformat()
    if m := re.match(r"(\d+)\s+days?\s+ago", s):
        return (today - timedelta(days=int(m[1]))).isoformat()
    if m := re.match(r"(\d{1,2})[/.](\d{1,2})$", s):
        return near(int(m[1]), int(m[2]))
    if (m := re.match(r"(\d{1,2})\s+([a-z]{3})", s)) and m[2] in MONTHS:
        return near(int(m[1]), MONTHS[m[2]])
    if (m := re.match(r"([a-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})", s)) and m[1] in MONTHS:
        return f"{m[3]}-{MONTHS[m[1]]:02d}-{int(m[2]):02d}"
    return ""


def _text(node, sel):
    hit = node.select_one(sel)
    return " ".join(hit.get_text(" ").replace("⁠", "").split()) if hit else ""


def _plain(html):
    """Text of a description that came as HTML, with its headings and bullets on their own lines."""
    return ingest.text_lines(BeautifulSoup(html, "html.parser")) if "<" in (html or "") else (html or "").strip()


def _find(prefix, num, title, company, location, link, posted, source, text=""):
    return {"id": f"{prefix}-{re.sub(r'[^A-Za-z0-9_-]', '', str(num))}", "title": title, "company": company, "location": location,
            "link": link, "posted": posted, "source": source, "text": text}


# The sources. Each one takes a job title, a spot ({"place", "cc", "country"}) and the two ways to ask (get, post).

def parse_linkedin_search(html):
    """The result cards of one LinkedIn search page as [{"id", "title", "company", "location", "link", "posted", "source"}]."""
    out = []
    for card in BeautifulSoup(html or "", "html.parser").select("li"):
        a = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        m = re.search(r"-(\d{6,})(?:\?|$)|/jobs/view/(\d{6,})", a.get("href", "") if a else "")
        urn = card.select_one("[data-entity-urn]")
        num = (m and (m.group(1) or m.group(2))) or (urn and urn["data-entity-urn"].rsplit(":", 1)[-1])
        title = _text(card, ".base-search-card__title")
        if not num or not title:
            continue
        when = card.select_one("time")
        out.append({"id": f"li-{num}", "title": title, "company": _text(card, ".base-search-card__subtitle"),
                    "location": _text(card, ".job-search-card__location"), "link": f"https://www.linkedin.com/jobs/view/{num}/",
                    "posted": when.get("datetime", "") if when else "", "source": "LinkedIn"})
    return out


def linkedin_url(query, where, levels=(), start=0, days=30):
    codes = sorted({c for lv in levels for c in LEVEL_CODES.get(lv, [])})
    params = {"keywords": query, "location": where, "f_TPR": f"r{days * 86400}", "start": start}
    if codes:
        params["f_E"] = ",".join(codes)
    return f"{LINKEDIN}?{urlencode(params)}"


def linkedin(role, spot, get, post, profile):
    return parse_linkedin_search(get(linkedin_url(role, spot["place"], profile.get("levels") or ())))


def parse_eures(data, country=""):
    out = []
    for j in (data or {}).get("jvs") or []:
        if not j.get("id") or not j.get("title"):
            continue
        employer = " ".join(((j.get("employer") or {}).get("name") or "").split())
        out.append(_find("eu", j["id"], j["title"], "" if _NO_NAME.search(employer) else employer, country,
                         f"https://europa.eu/eures/portal/jv-se/jv-details/{quote(str(j['id']), safe='')}?lang=en",
                         _day(j.get("creationDate")), "EURES", _plain(j.get("description") or "")))
    return out


def eures(role, spot, get, post, profile):
    """The European job portal, which carries the vacancies of the national employment agencies (ADEM for Luxembourg)."""
    body = {"resultsPerPage": 50, "page": 1, "sortSearch": "MOST_RECENT", "keywords": [{"keyword": role, "specificSearchCode": "TITLE"}],
            "publicationPeriod": "LAST_MONTH", "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [],
            "positionScheduleCodes": [], "sectorCodes": [], "educationAndQualificationLevelCodes": [], "positionOfferingCodes": [],
            "locationCodes": [spot["cc"]], "euresFlagCodes": [], "otherBenefitsCodes": [], "requiredLanguages": [],
            "minNumberPost": None, "sessionId": "shortlist"}
    return parse_eures(json.loads(post(EURES, body)), spot["country"])


def parse_jobs_lu(html, today=None):
    out = []
    for card in BeautifulSoup(html or "", "html.parser").select("article.job-list-item"):
        a = card.select_one("a.job-title")
        m = re.search(r"Id=(\d+)", a.get("href", "") if a else "") or re.search(r"(\d+)$", card.get("id", ""))
        if not a or not m:
            continue
        out.append(_find("jl", m[1], " ".join(a.get_text(" ").split()), _text(card, ".recruiter-name"), _text(card, ".location"),
                         f"https://en.jobs.lu/ApplyForJob.aspx?Id={m[1]}", _day(_text(card, ".date"), today), "jobs.lu"))
    return out


def jobs_lu(role, spot, get, post, profile):
    return parse_jobs_lu(get(f"https://en.jobs.lu/Jobs.aspx?{urlencode({'Keywords': role})}"))


def parse_ictjob(html, today=None):
    out = []
    for card in BeautifulSoup(html or "", "html.parser").select("li.search-item"):
        a = card.select_one("a.job-title")
        m = re.search(r"/job/[^/]+/([\w-]+)/?$", a.get("href", "").strip() if a else "")
        if not m:
            continue
        out.append(_find("ict", m[1], " ".join(a.get_text(" ").split()), _text(card, ".job-company"),
                         _text(card, "[itemprop=addressLocality]") or "Luxembourg", a["href"].strip(), _day(_text(card, ".job-date"), today),
                         "ICTjob.lu"))
    return out


def ictjob(role, spot, get, post, profile):
    return parse_ictjob(get(f"https://www.ictjob.lu/en/search-it-jobs?{urlencode({'keywords': role})}"))


def parse_efc(data):
    out = []
    for j in (data or {}).get("data") or []:
        if not j.get("jobId") or not j.get("title") or not j.get("detailsPageUrl"):
            continue
        out.append(_find("efc", j["jobId"], j["title"], j.get("companyName") or "", (j.get("jobLocation") or {}).get("displayName") or "",
                         "https://www.efinancialcareers.com" + j["detailsPageUrl"], _day(j.get("postedDate")), "eFinancialCareers",
                         _plain(j.get("description") or "")))
    return out


def efc(role, spot, get, post, profile):
    """eFinancialCareers: banks, funds and the firms around them."""
    _, _, lat, lon, _ = COUNTRIES[spot["cc"]]
    params = {"q": role, "countryCode2": spot["cc"].upper(), "locationPrecision": "Country", "latitude": lat, "longitude": lon,
              "radius": 50, "radiusUnit": "km", "page": 1, "pageSize": 30}
    # Past the jobs in the country it pads the page with jobs from all over the world; those are not what was asked.
    return [f for f in parse_efc(json.loads(get(f"{EFC}?{urlencode(params)}"))) if country_of(f["location"]) == spot["cc"]]


def parse_amazon(data):
    out = []
    for j in (data or {}).get("jobs") or []:
        if not j.get("id_icims") or not j.get("title"):
            continue
        text = "\n".join(x for x in [_plain(j.get("description") or ""),
                                     j.get("basic_qualifications") and "Basic qualifications\n" + _plain(j["basic_qualifications"]),
                                     j.get("preferred_qualifications") and "Preferred qualifications\n" + _plain(j["preferred_qualifications"])]
                         if x)
        out.append(_find("amz", j["id_icims"], j["title"], "Amazon", j.get("normalized_location") or j.get("location") or "",
                         "https://www.amazon.jobs" + (j.get("job_path") or f"/en/jobs/{j['id_icims']}"), _day(j.get("posted_date")),
                         "Amazon", text))
    return out


def amazon(role, spot, get, post, profile):
    """Amazon's own job site: one employer, but one of the largest in Luxembourg, and it publishes a plain search feed."""
    params = {"base_query": role, "country": COUNTRIES[spot["cc"]][1], "result_limit": 20, "sort": "recent"}
    return parse_amazon(json.loads(get(f"https://www.amazon.jobs/en/search.json?{urlencode(params)}")))


def _next_data(html):
    node = BeautifulSoup(html or "", "html.parser").select_one("script#__NEXT_DATA__")
    data = json.loads(node.string) if node and node.string else {}
    return [q.get("state", {}).get("data") for q in data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])]


def _any_language(value):
    return next((v for v in value.values() if v), "") if isinstance(value, dict) else (value or "")


def parse_jobfinder(html):
    out = []
    for data in _next_data(html):
        for o in (data.get("offers") or []) if isinstance(data, dict) else []:
            offer, title = o.get("offer") or {}, _any_language((o.get("offer") or {}).get("title"))
            if offer.get("id") and title:
                out.append(_find("jf", offer["id"], " ".join(title.split()), (o.get("company") or {}).get("name") or "", "Luxembourg",
                                 f"https://www.jobfinder.lu/en/jobs/{offer['id']}", _day(offer.get("visible_online")), "Jobfinder.lu"))
    return out


def jobfinder(role, spot, get, post, profile):
    return parse_jobfinder(get(f"https://www.jobfinder.lu/en/jobs?{urlencode({'q': role})}"))


def jobfinder_text(html):
    for data in _next_data(html):
        job = ((data.get("offer") or {}).get("job") or {}) if isinstance(data, dict) else {}
        if job.get("description"):
            return _plain(_any_language(job["description"]))
    return ""


# key, name, where it works ("any" place, a known "country", or only "lu"), and whether its search matches any single word
SOURCES = [
    ("linkedin", "LinkedIn", "any", False, linkedin),
    ("jobs_lu", "jobs.lu", "lu", True, jobs_lu),
    ("ictjob", "ICTjob.lu", "lu", True, ictjob),
    ("efc", "eFinancialCareers", "country", True, efc),
    ("amazon", "Amazon", "country", True, amazon),
    ("jobfinder", "Jobfinder.lu", "lu", True, jobfinder),
    ("eures", "EURES", "country", True, eures),
]


def _spots(scope, places):
    """Where one source is asked: every place for a source that takes any place name, each country once for the others."""
    out = []
    for p in places:
        cc = country_of(p)
        spot = {"place": p, "cc": cc, "country": COUNTRIES[cc][0] if cc else ""}
        if scope == "any" or (cc and (scope == "country" or cc == "lu") and cc not in [s["cc"] for s in out]):
            out.append(spot)
    return out


def search(profile, fetch=ingest.fetch, post=ingest.post_json, pause=1.0, sleep=time.sleep, sources=None, report=None):
    """Every listing found for the profile, each job once, however many sites carry it. `report` (a dict) gets, per
    source name, how many it gave and whether it answered. Raises only when no request at all went through."""
    roles = [r for r in profile.get("roles") or [] if r.strip()][:MAX_ROLES]
    places = [p for p in profile.get("where") or [] if p.strip()][:MAX_PLACES] or [""]

    def run(source):
        key, name, scope, loose, ask = source
        got, failed, asked = [], 0, 0
        for spot in _spots(scope, places):
            for role in roles:
                if asked:
                    sleep(pause)
                asked += 1
                try:
                    found = ask(role, spot, fetch, post, profile)
                except Exception:
                    failed += 1
                    continue
                got += [{**f, "query": role} for f in found if not loose or relevant(f["title"], profile)]
        return name, got[:MAX_PER_SOURCE * len(roles)], asked, failed

    chosen = [s for s in SOURCES if sources is None or s[0] in sources]
    with ThreadPoolExecutor(max_workers=max(1, len(chosen))) as pool:
        results = list(pool.map(run, chosen))

    ids, seen, out, kept = set(), Seen(), [], {}
    for name, got, _, _ in results:
        for f in got:
            f = {**f, "title": clean_title(f["title"])}
            if f["id"] in ids or seen.has(f["company"], f["title"]):
                continue
            ids.add(f["id"])
            seen.add(f["company"], f["title"])
            out.append(f)
            kept[name] = kept.get(name, 0) + 1
    if report is not None:
        for name, _, asked, failed in results:
            if asked:
                report[name] = {"found": kept.get(name, 0), "ok": failed < asked}
    asked, failed = sum(r[2] for r in results), sum(r[3] for r in results)
    if asked and failed == asked:
        raise RuntimeError("The job search did not answer. Try again in a few minutes.")
    return out


def read(find, fetch=ingest.fetch):
    """The full text of a found posting, from its own page."""
    if find.get("source") == "Jobfinder.lu":
        return jobfinder_text(fetch(find["link"]))
    return ingest.read_posting(find["link"], fetch=fetch).get("text") or ""


class Finds:
    """What a search turned up, kept in the database: new ones to look at, and the ones you saved or skipped,
    so the same job never comes back."""

    COLS = ["id", "title", "company", "location", "link", "source", "posted", "score", "fit", "facts", "reasons", "text",
            "work_setup", "distance_km", "state", "read", "found_at"]

    def __init__(self, con):
        self.con = con
        con.execute("""CREATE TABLE IF NOT EXISTS finds (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT DEFAULT '', location TEXT DEFAULT '', link TEXT DEFAULT '',
            source TEXT DEFAULT '', posted TEXT DEFAULT '', score INTEGER, fit TEXT DEFAULT '', facts TEXT DEFAULT '',
            reasons TEXT DEFAULT '', text TEXT DEFAULT '', work_setup TEXT DEFAULT '', distance_km REAL,
            state TEXT NOT NULL DEFAULT 'new', read INTEGER DEFAULT 0, found_at TEXT NOT NULL)""")
        con.commit()

    def get(self, fid):
        r = self.con.execute("SELECT * FROM finds WHERE id = ?", (fid,)).fetchone()
        return dict(r) if r else None

    def known(self, fid):
        return self.con.execute("SELECT 1 FROM finds WHERE id = ?", (fid,)).fetchone() is not None

    def seen(self):
        """Everything ever found, so a job skipped on one site does not return from another."""
        return Seen((r["company"], r["title"]) for r in self.con.execute("SELECT company, title FROM finds"))

    def add(self, f):
        row = {k: f.get(k) for k in self.COLS if k in f}
        row.setdefault("found_at", db.now())
        cols = list(row)
        self.con.execute(f"INSERT OR IGNORE INTO finds ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
        self.con.commit()

    def update(self, fid, fields):
        fields = {k: v for k, v in fields.items() if k in self.COLS and k != "id"}
        if fields:
            self.con.execute(f"UPDATE finds SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", [*fields.values(), fid])
            self.con.commit()
        return self.get(fid)

    def new(self):
        return [dict(r) for r in self.con.execute("SELECT * FROM finds WHERE state = 'new' ORDER BY score DESC, posted DESC")]
