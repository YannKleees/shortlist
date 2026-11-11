"""Why a job fits: every part of the score as a plain sentence, so the total is never a mystery."""

import re

import numpy as np
import pandas as pd

DOMAIN_PTS = {"data_science": 35, "ml_engineering": 32, "analytics": 18, "data_engineering": 15, "other": 5}
LEVEL_PTS = {"intern": 30, "junior": 27, "mid": 10, "senior": 0, "unknown": 15}
SETUP_PTS = {"Hybrid": 15, "Remote": 10, "Unknown": 8, "On site": 5}
LU = r"luxembourg|esch|belval|kirchberg|leudelange|munsbach|bertrange|strassen|junglinster|mamer|bissen|bettembourg"
NL = r"utrecht|amsterdam|netherlands|rotterdam|hilversum|eindhoven|den haag|the hague|naarden"
SPOKEN = ["English", "French", "German", "Luxembourgish"]
LANGUAGE_PENALTY = 15
DEGREE_PENALTY = 10
SENIOR_CAP = 35

DOMAIN_NOTE = {
    "data_science": "Real data science or ML work.", "ml_engineering": "Machine learning engineering.",
    "analytics": "Mostly analytics, little modelling.", "data_engineering": "Data engineering more than data science.",
    "other": "Not clearly a data job.",
}
SETUP_NOTE = {"Hybrid": "Hybrid work setup.", "Remote": "Remote work possible.", "Unknown": "Work setup not stated.",
              "On site": "On site, no hybrid option stated."}


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def _tone(points, top):
    return "good" if points >= 0.75 * top else "bad" if points <= 0.35 * top else "ok"


def wanted(profile):
    """What a profile asks for, ready for scoring: the fields of the job titles, their words, the levels, the setup."""
    from .extract import DOMAIN_RULES, _first
    roles = [str(x).strip().lower() for x in (profile or {}).get("roles") or [] if str(x).strip()]
    filler = {"junior", "intern", "internship", "graduate", "senior", "m", "f", "d"}
    return {"domains": {d for d in (_first(DOMAIN_RULES, x) for x in roles) if d},
            "titles": [set(re.findall(r"[a-zà-ÿ]+", x)) - filler for x in roles],
            "levels": set((profile or {}).get("levels") or []), "setup": (profile or {}).get("setup") or "",
            "years": _num((profile or {}).get("years")) or 0}


def explain(r, spoken=None, profile=None):
    """The score of one job, split into parts. `r` is a row with the extracted facts. With a `profile`
    (the job titles, levels and work setup you want, and your years of experience) the points follow what you asked for."""
    spoken = spoken or SPOKEN
    w = wanted(profile) if profile else None
    parts = []

    dom = r.get("domain") or "other"
    pts, note = DOMAIN_PTS.get(dom, 5), DOMAIN_NOTE.get(dom, "")
    if w and (w["domains"] or w["titles"]):
        title = set(re.findall(r"[a-zà-ÿ]+", str(r.get("role") or "").lower()))
        if any(t and t <= title for t in w["titles"]):
            pts, note = 35, "The job title is one you are looking for."
        elif dom in w["domains"]:
            pts, note = 32, f"{note.rstrip('.')}, a field you are looking for."
        else:
            pts, note = (5, note) if dom == "other" else (15, f"{note.rstrip('.')}, not the field you asked for.")
    parts.append({"key": "field", "label": "Field", "points": pts, "max": 35, "tone": _tone(pts, 35), "note": note})

    sen, yrs = r.get("seniority") or "unknown", _num(r.get("years_required"))
    own = w["years"] if w else 0
    pts = LEVEL_PTS.get(sen, 15)
    note = {"intern": "Internship, no experience needed.", "junior": "Junior level.", "mid": "Mid level role.",
            "senior": "Senior level.", "unknown": "Level not stated."}[sen if sen in LEVEL_PTS else "unknown"]
    if w and w["levels"]:
        if sen in w["levels"]:
            pts, note = 30, f"{note.rstrip('.')}, a level you are looking for."
        elif sen in LEVEL_PTS and sen != "unknown":
            pts = {"intern": 12, "junior": 20, "mid": 10, "senior": 0}[sen]
    gap = None if yrs is None else yrs - own
    if gap is not None and gap >= 3:
        pts = 0
    elif gap is not None and gap >= 2:
        pts = min(pts, 10)
    parts.append({"key": "level", "label": "Level", "points": pts, "max": 30, "tone": _tone(pts, 30), "note": note})
    if yrs is not None and yrs >= 1:
        mine = "under 1 year" if own < 1 else f"{int(own)} year{'' if int(own) == 1 else 's'}"
        parts.append({"key": "experience", "label": "Experience", "points": 0, "max": 0,
                      "tone": "bad" if gap >= 3 else "ok" if gap >= 2 else "good",
                      "note": f"Asks for {int(yrs)} year{'' if int(yrs) == 1 else 's'} of experience. You have {mine}."})

    setup = r.get("work_setup") or "Unknown"
    pts = SETUP_PTS.get(setup, 8)
    if w and w["setup"] in SETUP_PTS and w["setup"] != "Hybrid":
        pts = 15 if setup == w["setup"] else {"Hybrid": 11, "Unknown": 8}.get(setup, 4)
    parts.append({"key": "setup", "label": "Work setup", "points": pts, "max": 15, "tone": _tone(pts, 15), "note": SETUP_NOTE.get(setup, "")})

    km, loc = _num(r.get("distance_km")), str(r.get("location") or "").lower()
    if setup == "Remote":
        pts, note = 10, "Remote, so distance does not matter."
    elif km is not None:
        pts = 10 if km <= 20 else 8 if km <= 40 else 5 if km <= 70 else 2 if km <= 150 else 0
        note = f"{int(km)} km from home." if km < 150 else f"Far from home: {int(km)} km."
    elif re.search(LU, loc):
        pts, note = 10, "In the Luxembourg area."
    elif re.search(NL, loc) or "remote" in loc:
        pts, note = 8, "In the Netherlands."
    else:
        pts, note = 3, "Distance unknown. Add your home address in Settings." if loc else "Location not stated."
    parts.append({"key": "distance", "label": "Distance", "points": pts, "max": 10, "tone": _tone(pts, 10), "note": note})

    sim = _num(r.get("sim"))
    pts = int(round(10 * min(max((sim or 0) / 0.5, 0), 1)))
    note = "Upload your CV to compare." if not r.get("has_cv", True) else (
        "Strong match with your CV." if pts >= 6 else "Some overlap with your CV." if pts >= 3 else "Little overlap with your CV.")
    have, need = r.get("have"), r.get("need")
    if r.get("has_cv", True) and isinstance(have, list) and isinstance(need, list) and len(have) + len(need) >= 3:
        # The skills the posting names say more than how many words it shares with the CV.
        pts = int(round(10 * len(have) / (len(have) + len(need))))
        note = f"Your CV and projects show {len(have)} of the {len(have) + len(need)} skills it names."
    parts.append({"key": "cv", "label": "CV match", "points": pts, "max": 10, "tone": _tone(pts, 10), "note": note})

    langs = list(r.get("languages_required") or [])
    missing = [lg for lg in langs if lg not in spoken]
    if missing:
        parts.append({"key": "languages", "label": "Languages", "points": -LANGUAGE_PENALTY, "max": 0, "tone": "bad",
                      "note": f"Asks for {' and '.join(missing)}, which you do not speak."})
    elif langs:
        parts.append({"key": "languages", "label": "Languages", "points": 0, "max": 0, "tone": "good",
                      "note": f"Asks for {' and '.join(langs)}, which you speak."})

    deg = r.get("degree_fit")
    if isinstance(deg, dict) and deg.get("note"):
        parts.append({"key": "degree", "label": "Degree", "points": -DEGREE_PENALTY if deg["tone"] == "bad" else 0, "max": 0,
                      "tone": deg["tone"], "note": deg["note"]})
    return parts


def total(parts, r, profile=None):
    s = sum(p["points"] for p in parts)
    yrs = _num(r.get("years_required"))
    w = wanted(profile) if profile else {"years": 0, "levels": set()}
    senior = r.get("seniority") == "senior" and "senior" not in w["levels"]
    if senior or (yrs is not None and yrs - w["years"] >= 3):
        s = min(s, SENIOR_CAP)
    return int(np.clip(round(s), 0, 100))


def prior_score(df, spoken=None, profile=None):
    rows = df.to_dict("records")
    return pd.Series([total(explain(r, spoken, profile), r, profile) for r in rows], index=df.index, dtype=int)


def fit_label(score):
    return pd.Series(np.select([score >= 80, score >= 60, score >= 45], ["Top pick", "Good", "Maybe"], "Stretch"), index=score.index)


def pros_cons(r, spoken=None, profile=None):
    parts = [p for p in explain(r, spoken, profile) if p["key"] in ("level", "experience", "field", "setup", "distance", "languages")]
    order = {"experience": 0, "level": 1, "field": 2, "setup": 3, "distance": 4, "languages": 5}
    parts.sort(key=lambda p: order[p["key"]])
    pros = [p["note"] for p in parts if p["tone"] == "good" and p["key"] not in ("languages", "experience")]
    cons = [p["note"] for p in parts if p["tone"] == "bad"]
    return " ".join(pros[:3]), " ".join(cons[:3])
