import json
import re
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8,de;q=0.7",
}
WIKI_HEADERS = {"User-Agent": "shortlist-job-tracker/2.0 (personal use)"}
ORG_WORDS = re.compile(r"company|corporation|bank|firm|group|multinational|manufactur|institut|organi[sz]ation|consult|"
                       r"retail|airline|software|insurer|insurance|conglomerate|business|enterprise|university|agency|startup|operator", re.I)


def detect_source(url):
    host = urlparse(url).netloc.lower()
    if "linkedin." in host:
        return "LinkedIn"
    if "indeed." in host:
        return "Indeed"
    if "moovijob" in host:
        return "Moovijob"
    return "Company site"


def canonical_link(url):
    u = urlparse(url)
    host = u.netloc.lower()
    if "linkedin." in host:
        m = re.search(r"(?:jobs/view/(?:[^/?]*-)?|currentJobId=)(\d{6,})", url)
        if m:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    if "indeed." in host:
        q = parse_qs(u.query)
        jk = (q.get("jk") or q.get("vjk") or [None])[0]
        if jk:
            return f"https://{host}/viewjob?jk={jk}"
    return url.split("#")[0]


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _clean(text):
    return " ".join(BeautifulSoup(text, "html.parser").get_text(" ").split())


def _json_ld(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", " ".join(text.split())) if s.strip()]


def summarize(text, n=3, limit=380):
    out = []
    for s in sentences(text):
        if out and (len(out) >= n or len(" ".join(out + [s])) > limit):
            break
        out.append(s)
    return " ".join(out)[:limit]


def about_section(text, company=""):
    names = ["about us", "about the company", "who we are", "our company"] + ([f"about {company}"] if company else [])
    m = re.search(r"(?:" + "|".join(re.escape(n) for n in names) + r")\s*[:\-]?\s*(.+)", text, re.I | re.S)
    return summarize(m.group(1), n=2, limit=320) if m else ""


def wikipedia_about(company, get=requests.get):
    # Short description of the employer from Wikipedia, only when the match is clearly an organisation.
    try:
        hits = get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch", "search": company, "limit": 1, "format": "json"},
                   timeout=8, headers=WIKI_HEADERS).json()
        if not hits[1]:
            return ""
        page = get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(hits[1][0])}", timeout=8, headers=WIKI_HEADERS).json()
    except Exception:
        return ""
    if page.get("type") == "disambiguation" or not ORG_WORDS.search(page.get("description", "") + " " + page.get("extract", "")[:200]):
        return ""
    return summarize(page.get("extract", ""), n=2, limit=320)


def parse_posting(html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {"company": "", "role": "", "location": "", "text": "", "about": ""}

    ld = _json_ld(soup)
    if ld:
        org = ld.get("hiringOrganization") or {}
        loc = ld.get("jobLocation") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        out.update(
            company=org.get("name", "") if isinstance(org, dict) else str(org),
            role=ld.get("title", ""),
            location=", ".join(x for x in [addr.get("addressLocality", ""), addr.get("addressCountry", "")] if x),
            text=_clean(ld.get("description", "")),
            about=_clean(org.get("description", "")) if isinstance(org, dict) else "",
        )

    og = soup.find("meta", property="og:title")
    title = (og.get("content") if og else None) or (soup.title.string if soup.title else "") or ""
    for pattern, order in [(r"^(?P<a>.+?) hiring (?P<b>.+?) in (?P<l>.+?) \| LinkedIn", ("company", "role")),
                           (r"^(?P<a>.+?) - (?P<b>.+?) - (?P<l>.+?) \| Indeed", ("role", "company"))]:
        m = re.match(pattern, title)
        if m:
            out[order[0]] = out[order[0]] or m["a"].strip()
            out[order[1]] = out[order[1]] or m["b"].strip()
            out["location"] = out["location"] or m["l"].strip()
    if not out["role"]:
        out["role"] = title.split("|")[0].strip()
    if not out["company"]:
        site = soup.find("meta", property="og:site_name")
        out["company"] = site.get("content", "") if site else urlparse(url).netloc.replace("www.", "")

    if not out["text"]:
        for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            t.decompose()
        main = soup.select_one(".description, .show-more-less-html__markup, #jobDescriptionText, main, article") or soup.body or soup
        out["text"] = " ".join(main.get_text(" ").split())
    out["text"] = out["text"][:20000]
    out["about"] = summarize(out["about"], n=2, limit=320) if out["about"] else about_section(out["text"], out["company"])
    return out


# Links shared from a phone

URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
JOB_URL = re.compile(r"linkedin\.[a-z.]+/(?:comm/)?jobs|indeed\.|stepstone|glassdoor|moovijob|jobs\.lu|monster\.|welcometothejungle|"
                     r"greenhouse\.io|lever\.co|myworkdayjobs|smartrecruiters|personio|join\.com|recruitee|teamtailor|workable|"
                     r"successfactors|taleo|/jobs?/|/careers?/|/vacanc|/stellen|/emploi|/offres?|/job-|career|karriere|vacature", re.I)
SKIP_URL = re.compile(r"accounts\.google|support\.google|unsubscribe|/settings|/help/|privacy|\.(?:png|jpe?g|gif|css|js)(?:\?|$)", re.I)


def find_links(text):
    seen, out = set(), []
    for m in URL.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?*")
        if u not in seen and not SKIP_URL.search(u):
            seen.add(u)
            out.append(u)
    return out


def looks_like_job(url):
    return bool(JOB_URL.search(url))


def parse_shared(text, url=""):
    """Company and role from the text a phone app adds when you share a job, for example
    "Check out this job at Northwind: Data Scientist" (LinkedIn) or "Data Scientist - Northwind - Luxembourg" (Indeed)."""
    text = text or ""
    if url:
        text = text.replace(url, " ")
    lines = [ln.strip(" -–|:\t") for ln in URL.sub(" ", text).splitlines()]
    lines = [ln for ln in lines if ln]
    first = lines[0] if lines else ""
    m = re.match(r"^(?:check out this job|have a look at this job|schau dir diesen job an)?\s*(?:at|bei|chez)\s+(?P<company>.+?):\s*(?P<role>.+)$", first, re.I)
    if m:
        return {"company": m["company"].strip(), "role": m["role"].strip(), "location": ""}
    first = re.sub(r"^(?:i found this job|check out this job|have a look at this job|job)[^:]*:\s*", "", first, flags=re.I).strip()
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+", first) if p.strip()]
    if len(parts) >= 3:
        return {"role": parts[0], "company": parts[1], "location": parts[2]}
    if len(parts) == 2:
        return {"role": parts[0], "company": parts[1], "location": ""}
    m = re.match(r"^(?P<role>.+?)\s+(?:at|bei|chez)\s+(?P<company>.+)$", first, re.I)
    if m:
        return {"company": m["company"].strip(), "role": m["role"].strip(), "location": ""}
    return {"company": "", "role": first[:120], "location": ""}


def linkedin_guest_url(link):
    m = re.search(r"linkedin\.com/jobs/view/(\d{6,})", link)
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}" if m else ""


def parse_linkedin_guest(html):
    # The public job card LinkedIn serves without a login.
    soup = BeautifulSoup(html, "html.parser")
    pick = lambda sel: " ".join(soup.select_one(sel).get_text(" ").split()) if soup.select_one(sel) else ""
    return {
        "company": pick(".topcard__org-name-link") or pick(".topcard__flavor"),
        "role": pick(".top-card-layout__title") or pick(".topcard__title"),
        "location": pick(".topcard__flavor--bullet"),
        "text": pick(".show-more-less-html__markup") or pick(".description__text"),
        "about": "",
    }


def read_posting(link, fetch=fetch):
    """Read a posting. LinkedIn's public job card first, since the normal page often shows a login wall."""
    guest = linkedin_guest_url(link)
    if guest:
        try:
            p = parse_linkedin_guest(fetch(guest))
            if p["company"] and p["text"]:
                p["about"] = about_section(p["text"], p["company"])
                return p
        except Exception:
            pass
    return parse_posting(fetch(link), link)
