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


def explain(r, spoken=None):
    """The score of one job, split into parts. `r` is a row with the extracted facts."""
    spoken = spoken or SPOKEN
    parts = []

    dom = r.get("domain") or "other"
    pts = DOMAIN_PTS.get(dom, 5)
    parts.append({"key": "field", "label": "Field", "points": pts, "max": 35, "tone": _tone(pts, 35), "note": DOMAIN_NOTE.get(dom, "")})

    sen, yrs = r.get("seniority") or "unknown", _num(r.get("years_required"))
    pts = LEVEL_PTS.get(sen, 15)
    note = {"intern": "Internship, no experience needed.", "junior": "Junior level.", "mid": "Mid level role.",
            "senior": "Senior level.", "unknown": "Level not stated."}[sen if sen in LEVEL_PTS else "unknown"]
    if yrs is not None and yrs >= 3:
        pts, note = 0, f"Asks for {int(yrs)} years of experience."
    elif yrs is not None and yrs >= 2:
        pts, note = min(pts, 10), f"Asks for {int(yrs)} years of experience."
    parts.append({"key": "level", "label": "Level", "points": pts, "max": 30, "tone": _tone(pts, 30), "note": note})

    setup = r.get("work_setup") or "Unknown"
    pts = SETUP_PTS.get(setup, 8)
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
    parts.append({"key": "cv", "label": "CV match", "points": pts, "max": 10, "tone": _tone(pts, 10), "note": note})

    langs = list(r.get("languages_required") or [])
    missing = [lg for lg in langs if lg not in spoken]
    if missing:
        parts.append({"key": "languages", "label": "Languages", "points": -LANGUAGE_PENALTY, "max": 0, "tone": "bad",
                      "note": f"Asks for {' and '.join(missing)}, which you do not speak."})
    elif langs:
        parts.append({"key": "languages", "label": "Languages", "points": 0, "max": 0, "tone": "good",
                      "note": f"Asks for {' and '.join(langs)}, which you speak."})
    return parts


def total(parts, r):
    s = sum(p["points"] for p in parts)
    yrs = _num(r.get("years_required"))
    if r.get("seniority") == "senior" or (yrs is not None and yrs >= 3):
        s = min(s, SENIOR_CAP)
    return int(np.clip(round(s), 0, 100))


def prior_score(df, spoken=None):
    rows = df.to_dict("records")
    return pd.Series([total(explain(r, spoken), r) for r in rows], index=df.index, dtype=int)


def fit_label(score):
    return pd.Series(np.select([score >= 80, score >= 60, score >= 45], ["Top pick", "Good", "Maybe"], "Stretch"), index=score.index)


def pros_cons(r, spoken=None):
    parts = [p for p in explain(r, spoken) if p["key"] in ("level", "field", "setup", "distance", "languages")]
    order = {"level": 0, "field": 1, "setup": 2, "distance": 3, "languages": 4}
    parts.sort(key=lambda p: order[p["key"]])
    pros = [p["note"] for p in parts if p["tone"] == "good" and p["key"] != "languages"]
    cons = [p["note"] for p in parts if p["tone"] == "bad"]
    return " ".join(pros[:3]), " ".join(cons[:3])
