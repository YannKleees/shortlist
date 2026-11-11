"""Your public GitHub projects: proof of skills the CV may not list, and projects worth naming for a job."""

import re

import requests

from .skills import find_skills

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


def username(value):
    # Accepts a name, @name or a profile link.
    v = (value or "").strip().rstrip("/")
    m = re.search(r"github\.com/([A-Za-z0-9-]+)", v)
    v = m.group(1) if m else v.lstrip("@")
    return v if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", v) else ""


def readme_text(md, limit=1500):
    # The readable start of a README: no badges, images, HTML, code blocks or link targets.
    t = re.sub(r"```.*?```", " ", md or "", flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[#>*_`|]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:limit]


def fetch(user, get=requests.get, readmes=30):
    """Public repositories, most recently worked on first. Raises ValueError with a readable message."""
    try:
        r = get(f"{API}/users/{user}/repos", params={"per_page": 100, "sort": "pushed"},
                headers={"Accept": "application/vnd.github+json"}, timeout=15)
    except requests.RequestException:
        raise ValueError("GitHub is not reachable right now. Try again later.") from None
    if r.status_code == 404:
        raise ValueError(f"There is no GitHub account called {user}.")
    if r.status_code != 200:
        raise ValueError("GitHub did not answer. Try again in an hour.")
    out = []
    for repo in r.json():
        if repo.get("name", "").lower() == user.lower() or repo.get("archived"):
            continue  # the profile README repository is not a project
        topics = repo.get("topics") or []
        readme = ""
        if len(out) < readmes:
            try:
                rr = get(f"{RAW}/{user}/{repo['name']}/{repo.get('default_branch') or 'main'}/README.md", timeout=10)
                readme = readme_text(rr.text) if rr.status_code == 200 else ""
            except requests.RequestException:
                pass
        words = " ".join([repo["name"], repo.get("description") or "", repo.get("language") or "", " ".join(t.replace("-", " ") for t in topics)])
        out.append({
            "name": repo["name"], "url": repo.get("html_url") or f"https://github.com/{user}/{repo['name']}",
            "description": (repo.get("description") or "").strip(), "language": repo.get("language") or "",
            "topics": topics, "updated": (repo.get("pushed_at") or "")[:10], "readme": readme,
            "skills": find_skills(f"{words} {readme}"),
        })
    return out


def as_text(projects):
    # Appended to the CV for scoring and letters, so projects count as evidence.
    if not projects:
        return ""
    lines = [f"- {p['name']} ({p['language'] or 'code'}): {p['description']} Topics: {', '.join(p['topics'])}. "
             f"Skills: {', '.join(p['skills'])}." for p in projects]
    return "Projects on GitHub:\n" + "\n".join(lines)


def for_job(projects, posting, limit=3):
    """The projects that best show what this posting asks for, with the reasons.

    A skill most of your projects share (say Python) says little about one project, so it counts less
    than a skill only a few projects show (say NLP or computer vision)."""
    projects = projects or []
    asked = set(find_skills(posting))
    text = (posting or "").lower()
    seen = {}
    for p in projects:
        for s in p.get("skills", []):
            seen[s] = seen.get(s, 0) + 1
    weight = lambda s: 1.0 if seen.get(s, 0) <= max(2, len(projects) / 3) else 0.25
    ranked = []
    for p in projects:
        skills = sorted((s for s in p.get("skills", []) if s in asked), key=lambda s: -weight(s))
        have = {s.lower() for s in skills}
        topics = [t.replace("-", " ") for t in p.get("topics", [])]
        topics = [t for t in topics if len(t) > 2 and t not in have and re.search(rf"\b{re.escape(t)}\b", text)]
        points = sum(weight(s) for s in skills) + 0.5 * len(topics)
        if points >= 1:
            ranked.append((points, {"name": p["name"], "url": p["url"], "description": p["description"],
                                    "matched": (skills + topics)[:5]}))
    ranked.sort(key=lambda x: -x[0])
    return [p for _, p in ranked[:limit]]
