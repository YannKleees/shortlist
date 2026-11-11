"""What a job actually is: the tasks, what kind of work fills the day, and the degree it asks for next to yours.
Everything here is read from the words of the posting and the CV with plain rules, so it works without any model."""

import re
from datetime import date

# Section headings. A heading is a short line; what follows a "tasks" heading, up to the next heading, is the work.
TASK_HEAD = (r"responsibilit|responsabilit|what you(?:['’]| wi)ll (?:do|be doing|work on)|what you do|ce que vous ferez|"
             r"your (?:role|tasks|missions?|impact|job|day|work)|votre r[oô]le|vos missions|votre mission|ta mission|tes missions|"
             r"the role|role overview|about the (?:role|job|position)|key (?:tasks|duties|accountabilities)|main (?:tasks|duties|activities)|"
             r"\bduties|\btasks\b|in this role|job description|description d[ue] poste|\bmissions\b|"
             r"aufgaben|das erwartet dich|deine rolle|ihre rolle|t[äa]tigkeiten")
OTHER_HEAD = (r"requirement|qualification|who you are|your profile|what you(?:['’]| wi)ll (?:need|bring)|what we(?:['’]| a)re looking for|"
              r"what we look for|what we want|about you|skills|must[- ]have|nice[- ]to[- ]have|even better|profil|offer|benefits|perks|"
              r"why (?:join )?us|pourquoi|raisons|about us|who we are|about the company|wir bieten|how to apply|equal opportunit|"
              r"education|experience|your background|what you bring|we expect|expect from us|preferred|bonus|compensation|salary|location|"
              r"contract|what(?:['’]| i)s in it for you|ideal candidate|you have|you are|you bring|to succeed|diversity|informations|"
              r"about the team|a day in|contact|comp[ée]tences|anforderungen")
_TASK = re.compile(TASK_HEAD, re.I)
_OTHER = re.compile(OTHER_HEAD, re.I)
_BULLET = " \t•*·▪◦■●○–—-/"
# The end of a sentence, but not the dot in "e.g." or "i.e.".
_SENT = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<!etc\.)(?<=[.!?])\s+(?=[A-Z])")
_NOT_A_TASK = re.compile(r"apply (?:now|here|online|today|via)|your application|confidential|contact (?:us|me)|@|www\.|https?:|"
                         r"equal opportunit|privacy (?:notice|policy)", re.I)


def _pieces(line):
    # Some postings put a whole list on one line, with slashes between the items.
    return [x for x in re.split(r"\s+/\s+", line) if x.strip()] if len(line) > 200 and line.count(" / ") >= 2 else [line]


def _is_head(line, pattern):
    s = line.strip(_BULLET).rstrip(":").strip()
    return 2 < len(s) <= 60 and not s.endswith((".", ",", ";")) and len(s.split()) <= 8 and bool(pattern.search(s))


def _tidy(s, limit=150):
    s = " ".join(s.strip(_BULLET).split())
    first = _SENT.split(s)[0]
    s = first if len(first) >= 30 else s
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s.rstrip(".;")


def _sections(text):
    """The posting cut at its headings: [(kind, lines)] where kind is "task", "other" or "" for the top of the page."""
    out, kind, cur = [], "", []
    for ln in (ln.strip() for ln in (text or "").splitlines()):
        if not ln:
            continue
        head = None if ln[0] in _BULLET else "task" if _is_head(ln, _TASK) else "other" if _is_head(ln, _OTHER) else None
        if head:
            out.append((kind, cur))
            kind, cur = head, []
        else:
            cur.append(ln)
    return out + [(kind, cur)]


def _bullets(lines, least=2):
    # The first run of bullet lines, at least `least` long.
    run = []
    for ln in lines:
        if ln[0] in _BULLET and len(ln) > 3:
            run.append(ln)
        elif len(run) >= least:
            break
        else:
            run = []
    return run if len(run) >= least else []


def tasks(text, limit=5):
    """Up to `limit` short lines on what you would do in the job."""
    sections = _sections(text)
    work = [lines for kind, lines in sections if kind == "task"]
    before = []
    for kind, lines in sections:
        if kind == "other":
            break
        before.append(lines)
    # Bullets under a tasks heading are the best answer; then a list near the top; then the sentences under the heading.
    found = next((b for b in map(_bullets, work) if b), []) or next((b for b in (_bullets(x, 3) for x in before) if b), [])
    if not found:
        for lines in work:
            items = [x for ln in lines for x in _pieces(ln) if 25 <= len(x) <= 260]
            if len(items) < 2:
                items = [x for ln in lines for x in _SENT.split(ln) if 25 <= len(x) <= 260]
            if len(items) >= 2:
                found = items
                break
    if not found:
        flat = " ".join((text or "").split())
        found = [x for x in _SENT.split(flat) if 30 <= len(x) <= 260 and re.match(r"(?:you will|you['’]ll|in this role|vous (?:serez|allez))", x, re.I)][:3]
    out, seen = [], set()
    for f in found:
        t = _tidy(f)
        if len(t) >= 20 and t.lower() not in seen and not _NOT_A_TASK.search(t):
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


# What kind of work it is, by the words the posting uses. A "Data Scientist" who mostly builds dashboards shows up here.
MIX = [
    ("modelling", "Modelling and ML", r"machine learning|\bml\b|deep learning|neural|\bmodel(?:s|ing|ling)?\b|predict|forecast|\bnlp\b|"
     r"computer vision|\bllms?\b|generative|recommend|classification|regression|statistic|experiment|a/b test|algorithm|data scien"),
    ("analysis", "Analysis and reporting", r"dashboard|report|\bkpis?\b|power ?bi|tableau|looker|excel|insight|analy[sz]|visuali[sz]|"
     r"business intelligence|\bbi\b|ad[- ]hoc|metrics"),
    ("engineering", "Data engineering", r"pipeline|\betl\b|\belt\b|\bspark\b|airflow|\bdbt\b|kafka|warehouse|data lake|snowflake|databricks|"
     r"ingest|data platform|data quality|orchestrat|data model"),
    ("software", "Software and deployment", r"software|back[- ]?end|front[- ]?end|full[- ]stack|\bapis?\b|microservice|docker|kubernetes|"
     r"ci/cd|deploy|production|devops|mlops|\bcloud\b|\baws\b|azure|\bgcp\b|unit test|scalab"),
    ("people", "Clients and coordination", r"client|customer|consult|presentation|workshop|project manag|coordinat|mentor|sales|"
     r"stakeholder|requirements|cross[- ]functional|communicat"),
]
_MIX = [(k, label, re.compile(p)) for k, label, p in MIX]


def mix(text):
    """[{"key", "label", "share"}] adding up to 100, biggest first. Empty when the posting says too little."""
    t = (text or "").lower()
    counts = [(k, label, min(len(p.findall(t)), 12)) for k, label, p in _MIX]
    total = sum(n for _, _, n in counts)
    if total < 5:
        return []
    parts = [{"key": k, "label": label, "share": round(100 * n / total)} for k, label, n in counts if n / total >= 0.08]
    parts.sort(key=lambda p: -p["share"])
    if parts:
        parts[0]["share"] += 100 - sum(p["share"] for p in parts)
    return parts


# Degrees

RANK = {"degree": 1, "bachelor": 1, "master": 2, "phd": 3}
NAME = {"degree": "a university degree", "bachelor": "a Bachelor's", "master": "a Master's", "phd": "a PhD"}
SHORT = {"bachelor": "BSc", "master": "MSc", "phd": "PhD", "degree": "Degree"}
LEVELS = [
    ("phd", r"\bph\.?\s?d\b|doctorate|doctoral"),
    ("master", r"\bmaster(?:['’]?s)?(?=\s+(?:degree|of\b|in\b|student|level|or\b|thesis|diploma|program|studies)|\s*[/,)])|\bmasters\b|master['’]s|"
               r"\bm\.?\s?sc\b|bac\s?\+\s?5|\bmba\b|graduate degree|dipl[oô]me d['’]ing[ée]nieur|[ée]cole d['’]ing[ée]nieur|"
               r"\bmaster\b(?=\s+(?:ou|en|2|\())"),
    ("bachelor", r"\bbachelor(?:['’]?s)?\b|\bb\.?\s?sc\b|bac\s?\+\s?3|undergraduate degree|\blicence\b"),
    ("degree", r"university degree|degree in\b|higher education|academic degree|college degree|studies in\b|diploma in\b|"
               r"abgeschlossenes studium|hochschulabschluss|formation sup[ée]rieure|dipl[oô]m[ée]|\bdipl[oô]me\b|\bdegree\b"),
]
_LEVELS = [(k, re.compile(p, re.I)) for k, p in LEVELS]
FIELDS = {
    "Computer science": r"computer science|informatics|informatik|informatique|computing",
    "Data science": r"data science|data analytics|science des donn[ée]es|\bdata\b",
    "AI": r"artificial intelligence|\bai\b|machine learning",
    "Statistics": r"statisti",
    "Mathematics": r"math[eé]mati|\bmaths?\b",
    "Engineering": r"engineering|ing[ée]nieur",
    "Physics": r"physics",
    "Economics": r"[eé]conom",
    "Business": r"business|management|finance|marketing",
    "Quantitative field": r"quantitative|\bstem\b|technical field|scientific|technical discipline",
}
_FIELDS = {k: re.compile(p, re.I) for k, p in FIELDS.items()}
QUANT = {"Computer science", "Data science", "AI", "Statistics", "Mathematics", "Engineering", "Physics", "Quantitative field"}
_OPTIONAL = re.compile(r"\bplus\b|asset|advantage|nice to have|bonus|beneficial|desirable|preferred|would be great|atout|von vorteil", re.I)
_RELATED = re.compile(r"related|similar|similaire|equivalent|comparable|or other|ähnlich|[ée]quivalent|vergleichbar", re.I)
_ENROLLED = re.compile(r"currently|pursuing|enrolled|student|studying|in your (?:final|last|penultimate)|eingeschrieben|[ée]tudiant", re.I)


def _sentences(text):
    return [s.strip() for s in re.split(r"[\n;]|\s/\s|(?<=[.!?])\s+(?=[A-Z])", text or "") if s.strip()]


def degree_asked(text):
    """The degree a posting asks for: {"level", "fields", "related", "student", "quote"}, or None when it names none."""
    for s in _sentences(text):
        if len(s) > 400:
            continue
        hits = []
        for level, p in _LEVELS:
            for m in p.finditer(s):
                clause = s[max(0, m.start() - 10):m.end() + 40]
                if level != "degree" and _OPTIONAL.search(clause) and len(hits) > 0:
                    continue  # "a PhD is a plus" after the real requirement
                hits.append(level)
        named = [h for h in hits if h != "degree"]
        if not hits or (not named and not re.search(r"degree|studium|dipl|education|studies|formation", s, re.I)):
            continue
        if _OPTIONAL.search(s) and len(set(named)) <= 1 and not re.search(r"requir|must|minimum|at least", s, re.I):
            continue  # the whole sentence is a wish, not a requirement
        level = min(named, key=RANK.get) if named else "degree"
        fields = [name for name, p in _FIELDS.items() if p.search(s)]
        return {"level": level, "fields": fields, "related": bool(_RELATED.search(s)), "student": bool(_ENROLLED.search(s)),
                "quote": " ".join(s.split())[:220]}
    return None


def degrees(cv, today=None):
    """The degrees on a CV, highest first: [{"level", "field", "done", "year"}]."""
    year_now = (today or date.today()).year
    out = []
    for line in (cv or "").splitlines():
        # A degree line names a year or a school. "MSc student looking for..." in a summary is not one.
        if len(line) > 300 or not re.search(r"\b(?:19|20)\d{2}\b|universit|hochschule|school|college|institut|[ée]cole", line, re.I):
            continue
        for level, p in _LEVELS[:3]:
            m = p.search(line)
            if not m:
                continue
            rest = re.sub(r"^[\s.:,]*(?:degree\s+)?(?:of science\s+)?(?:in\s+)?", "", line[m.end():], flags=re.I)
            field = re.split(r"\s*[|(\n]|\s+[–—-]\s+|,\s*\d|\s+\d{4}", rest)[0].strip(" .,:")
            years = [int(y) for y in re.findall(r"\b(20\d{2}|19\d{2})\b", line)]
            end = max(years) if years else None
            expected = bool(re.search(r"expected|ongoing|present|current|in progress|laufend|en cours", line, re.I)) or (end or 0) > year_now
            out.append({"level": level, "field": field[:70], "done": not expected, "year": end})
            break
    out.sort(key=lambda d: (-RANK[d["level"]], not d["done"]))
    return out


def degree_label(d):
    return f"{SHORT[d['level']]} {d['field']}".strip() if d else ""


def _a(label):
    return f"an {label}" if label[:1] in "MAEIO" else f"a {label}"


def degree_fit(asked, mine):
    """{"tone": good | ok | bad, "note"} for a posting's degree against your own, or None when it asks for none."""
    if not asked:
        return None
    want = RANK[asked["level"]]
    ask = f"Asks for {NAME[asked['level']]}"
    if asked["fields"]:
        named = [f for f in asked["fields"] if f != "Quantitative field"] or asked["fields"]
        ask += " in " + ", ".join(f if f == "AI" else f.lower() for f in named[:3])
        ask += " or similar" if asked["related"] else ""
    if not mine:
        return {"tone": "ok", "note": f"{ask}. Your CV names no degree."}
    done = [d for d in mine if d["done"] and RANK[d["level"]] >= want]
    coming = [d for d in mine if not d["done"] and RANK[d["level"]] >= want]
    my_fields = {name for d in mine for name, p in _FIELDS.items() if p.search(d["field"])}
    asked_fields = set(asked["fields"])
    off_field = bool(asked_fields) and not asked["related"] and not (asked_fields & my_fields) and not (asked_fields & QUANT and my_fields & QUANT)
    if done:
        tone, note = "good", f"{ask}. You have {_a(degree_label(done[0]))}."
    elif coming:
        when = f", expected {coming[0]['year']}" if coming[0]["year"] else ""
        tone = "good" if asked["student"] else "ok"
        note = f"{ask}. Your {degree_label(coming[0])} is not finished yet{when}."
    else:
        best = mine[0]
        tone, note = "bad", f"{ask}. Your highest is {_a(degree_label(best))}{'' if best['done'] else ', not finished yet'}."
    if off_field and tone != "bad":
        tone, note = "ok", note + " The field is not yours."
    return {"tone": tone, "note": note}


def facts(text, r, cv="", profile=None):
    """Everything the job page shows about what the job is. `r` holds the extracted level, years and languages."""
    asked = degree_asked(text)
    mine = profile["degrees"] if profile and "degrees" in profile else degrees(cv)
    yrs = r.get("years_required")
    try:
        yrs = int(yrs) if yrs is not None and yrs == yrs else None
    except (TypeError, ValueError):
        yrs = None
    quote = ""
    if yrs is not None:
        named = re.compile(rf"(?<!\d){yrs}\b.{{0,12}}?(?:years?|yrs|ans|ann[ée]es|jahre)", re.I)
        quote = next((" ".join(s.split())[:220] for s in _sentences(text) if named.search(s)), "")
    return {
        "level": r.get("seniority") or "unknown", "years": yrs, "yearsQuote": quote,
        "myYears": (profile or {}).get("years", 0),
        "degree": asked, "degreeFit": degree_fit(asked, mine),
        "myDegrees": [degree_label(d) + ("" if d["done"] else " (in progress)") for d in mine[:2]],
        "tasks": tasks(text), "mix": mix(text), "languages": list(r.get("languages_required") or []), "domain": r.get("domain") or "other",
    }
