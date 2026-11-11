"""Your skills in one place: what the CV, GitHub and LinkedIn each show, what your jobs ask for, and what to fix.

Everything here is plain rules on text you gave the app. LinkedIn is never read by the app itself: you paste your profile
or upload the PDF that LinkedIn makes of it."""

import re
import unicodedata

from .skills import FIELDS, GROUP_OF, GROUPS, find_skills

# Skills


def skill_map(cv, projects, linkedin="", postings=()):
    """One row per skill that you show somewhere or that a job asks for.

    {"name", "group", "cv", "repos": [names], "linkedin": True/False/None, "asked": how many postings name it}.
    `linkedin` is None while there is no profile text, so the screen can leave the column out."""
    in_cv = set(find_skills(cv))
    in_li = set(find_skills(linkedin)) if linkedin else None
    repos = {}
    for p in projects or []:
        for s in p.get("skills", []):
            repos.setdefault(s, []).append(p["name"])
    asked = {}
    for text in postings:
        for s in find_skills(text):
            asked[s] = asked.get(s, 0) + 1
    names = in_cv | set(repos) | set(asked) | (in_li or set())
    order = [s for g in GROUPS.values() for s in g]
    rows = [{"name": s, "group": GROUP_OF.get(s, "Other"), "cv": s in in_cv, "repos": repos.get(s, []),
             "linkedin": None if in_li is None else s in in_li, "asked": asked.get(s, 0)} for s in names]
    return sorted(rows, key=lambda r: order.index(r["name"]) if r["name"] in order else len(order))


def shown(row):
    return bool(row["cv"] or row["repos"])


def fields(rows, limit=3):
    # The fields of work you can prove, the best proven first.
    mine = [r for r in rows if r["name"] in FIELDS and shown(r)]
    return [r["name"] for r in sorted(mine, key=lambda r: -(len(r["repos"]) + 2 * r["cv"]))[:limit]]


# GitHub

REPO_CHECKS = [
    ("description", "a one line description", lambda p: len(p.get("description") or "") >= 20),
    ("topics", "three or more topics", lambda p: len(p.get("topics") or []) >= 3),
    ("readme", "a README that explains it", lambda p: p.get("readme_words", 0) >= 120),
    ("run", "how to run it", lambda p: bool(p.get("has_run"))),
    ("picture", "a picture or a result to look at", lambda p: bool(p.get("has_picture"))),
    ("license", "a licence", lambda p: bool(p.get("license"))),
]


def repo_review(p):
    """What a recruiter who opens this repository finds, and what is missing. `checked` is False for a project that was
    read before these checks existed."""
    base = {"name": p["name"], "url": p["url"], "language": p.get("language") or "", "updated": p.get("updated") or "",
            "description": p.get("description") or "", "skills": p.get("skills") or [], "demo": p.get("homepage") or ""}
    if "readme_words" not in p:
        return {**base, "checked": False, "done": 0, "total": len(REPO_CHECKS), "missing": []}
    missing = [label for _, label, ok in REPO_CHECKS if not ok(p)]
    return {**base, "checked": True, "done": len(REPO_CHECKS) - len(missing), "total": len(REPO_CHECKS), "missing": missing}


# LinkedIn

HEADINGS = {
    "about": r"about|summary|info|zusammenfassung|r[ée]sum[ée]|infos",
    "experience": r"experience|erfahrung|berufserfahrung|exp[ée]rience",
    "education": r"education|ausbildung|formation",
    "skills": r"(?:top[- ])?skills|(?:top-)?kenntnisse|comp[ée]tences(?: principales)?",
    "languages": r"languages|sprachen|langues",
    "projects": r"projects|projekte|projets|featured|im fokus",
    "certificates": r"(?:licenses & )?certifications|bescheinigungen|certifications et licences",
    "awards": r"honou?rs(?: (?:&|and) awards)?|auszeichnungen|distinctions",
}
LANGUAGE_WORDS = {"english": r"engl|angl", "french": r"french|franz|fran[cç]ais", "german": r"german|deutsch|allemand",
                  "luxembourgish": r"luxemb(?:o?urg)?(?:ish|isch|eois)|l[ëe]tzebuerg", "dutch": r"dutch|niederl|n[ée]erland",
                  "spanish": r"spanish|spanisch|espagnol|espa[ñn]ol", "italian": r"ital", "portuguese": r"portug"}
RESULT = r"(?<![\d/.])(?!(?:19|20)\d\d\b)\d[\d.,]*\s?(?:%|ms\b|k\b|x\b|\+|/\s?\d+|million|users|people|participants|students|hours|images|€)"


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def sections(text):
    """The profile cut at its headings: {"head": the lines before the first heading, "about": ..., "experience": ...}."""
    out, here = {"head": []}, "head"
    for line in (text or "").splitlines():
        s = line.strip()
        key = next((k for k, pattern in HEADINGS.items() if re.fullmatch(pattern, s.lower())), None)
        if key:
            here = key
            out.setdefault(here, [])
        elif s:
            out[here].append(s)
    return {k: "\n".join(v) for k, v in out.items()}


def headline(head):
    lines = [ln for ln in (head or "").splitlines() if ln.strip()]
    marked = [ln for ln in lines[:4] if "|" in ln or " at " in ln or " @ " in ln]
    return (marked or lines[1:2] or lines[:1] or [""])[0]


def cv_entries(cv):
    """The jobs, studies and projects on the CV: lines with a date, cut at their bars. [(what it is, [its parts])]"""
    out = []
    for line in (cv or "").splitlines():
        parts = [p.strip(" -•*") for p in line.split("|")]
        if len(parts) < 2 or not re.search(r"\b(?:19|20)\d\d\b", line):
            continue
        named = [p for p in parts if p and not re.fullmatch(r"[\W\d]*(?:[A-Za-zéû]{3,9}\.?\s)?(?:19|20)\d\d.*", p)]
        if named:
            out.append((named[0], named))
    return out


def missing_entries(cv, profile_text):
    """What the CV names and the profile does not: an entry counts as missing when its name or the part after it (an
    employer, a project) starts with a word the profile never uses."""
    there = fold(profile_text)
    out = []
    for title, parts in cv_entries(cv):
        for part in parts[:2 if len(parts) > 2 else 1]:  # name | employer | place, or name | what it was
            word = re.match(r"[^\W\d]{4,}", part)
            if word and fold(word[0]) not in there:
                out.append(title if part == title else f"{title} ({part.split(',')[0]})")
                break
    return out


def linkedin_review(text, link="", cv="", projects=(), profile=None, spoken=()):
    """Checks on the pasted profile, each one something you can fix in a few minutes: {"score", "checks": [...]}."""
    profile = profile or {}
    sec = sections(text)
    low = fold(text)
    rows = skill_map(cv, projects, text)
    roles, where = profile.get("roles") or [], profile.get("where") or []
    head = headline(sec["head"])
    top = fields(rows)
    wants = any(fold(r) in fold(head) for r in roles) or bool(re.search(r"seeking|looking for|open to|aspiring|sucht|recherche", fold(head)))
    start = head.split("|")[0].strip() or "What you study or do"
    example = " | ".join(x for x in (start, ", ".join(top), f"Looking for {roles[0]} roles{' in ' + where[0] if where else ''}" if roles else "") if x)
    about_words = len(sec.get("about", "").split())
    gone = missing_entries(cv, text)
    unlisted = [r["name"] for r in rows if shown(r) and not r["linkedin"]]
    silent = [lg for lg in spoken if not re.search(LANGUAGE_WORDS.get(lg.lower(), re.escape(lg.lower())), low)]
    results = len(re.findall(RESULT, low))
    slug = (re.search(r"linkedin\.com/in/([^/?#\s]+)", link or "") or [None, ""])[1]
    random_tail = re.search(r"-(?=[a-z0-9]*\d)[a-z0-9]{6,}$", slug.lower())
    best = [p["name"] for p in sorted(projects or [], key=lambda p: -sum(s in FIELDS for s in p.get("skills", [])))[:3]]
    checks = [
        {"key": "headline", "label": "Headline", "ok": wants and len(head) >= 30,
         "tip": f"Yours: \"{head}\". Name your field and the job you want, for example: \"{example}\"." if head
                else "Start the text with your headline, the line under your name."},
        {"key": "about", "label": "About", "ok": about_words >= 40,
         "tip": f"Your About has {about_words} words. Write three or four sentences: what you study, what you built with one number, "
                "and what you are looking for. The summary on your CV is a good start."},
        {"key": "entries", "label": "Jobs and projects from your CV", "ok": not gone,
         "tip": f"On your CV but not on your profile: {'; '.join(gone[:5])}."},
        {"key": "skills", "label": "Skills", "ok": len(unlisted) <= 2,
         "tip": f"Your CV or GitHub shows these, your profile does not: {', '.join(unlisted[:12])}. Recruiters search by skill."},
        {"key": "languages", "label": "Languages", "ok": bool(spoken) and not silent,
         "tip": f"Add a Languages section with {', '.join(silent or spoken)}." if spoken else "Add the languages you speak under Settings first."},
        {"key": "projects", "label": "Projects", "ok": bool(sec.get("projects")) or "github.com" in low,
         "tip": "Add a Projects section and link GitHub" + (f", for example {', '.join(best)}." if best else ".")},
        {"key": "numbers", "label": "Results in numbers", "ok": results >= 2,
         "tip": "Use the numbers from your CV in the descriptions: how many, how fast, what grade."},
        {"key": "link", "label": "Profile link", "ok": bool(slug) and not random_tail,
         "tip": f"Your link ends in random letters. Change it to linkedin.com/in/{re.sub(r'[^a-z]', '', slug.lower()[:random_tail.start()])} under "
                "Public profile & URL." if random_tail else "Add the link to your profile."},
    ]
    done = sum(c["ok"] for c in checks)
    return {"score": round(100 * done / len(checks)), "done": done, "total": len(checks), "headline": head, "checks": checks}
