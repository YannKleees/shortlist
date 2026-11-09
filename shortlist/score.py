import numpy as np
import pandas as pd

DOMAIN_PTS = {"data_science": 35, "ml_engineering": 32, "analytics": 18, "data_engineering": 15, "other": 5}
LEVEL_PTS = {"intern": 30, "junior": 27, "mid": 10, "senior": 0, "unknown": 15}
SETUP_PTS = {"Hybrid": 15, "Remote": 10, "Unknown": 8, "On site": 5}
LU = r"luxembourg|esch|belval|kirchberg|leudelange|munsbach|bertrange|strassen|junglinster|mamer|bissen|bettembourg"
NL = r"utrecht|amsterdam|netherlands|rotterdam|hilversum|eindhoven|den haag|the hague|naarden"


def prior_score(df):
    yrs = df["years_required"].astype(float).fillna(-1)
    level = df["seniority"].map(LEVEL_PTS).fillna(15)
    level = np.where(yrs >= 3, 0, np.where(yrs >= 2, np.minimum(level, 10), level))

    loc = df["location"].fillna("").str.lower()
    loc_pts = np.select([loc.str.contains(LU), loc.str.contains(NL) | loc.str.contains("remote")], [10, 8], 3)

    dutch = df["languages_required"].map(lambda langs: "Dutch" in (langs or []))
    skill_pts = 10 * np.clip(df["sim"].astype(float) / 0.5, 0, 1)

    s = (df["domain"].map(DOMAIN_PTS).fillna(5) + level + df["work_setup"].map(SETUP_PTS).fillna(8)
         + loc_pts + skill_pts - 15 * dutch)
    too_senior = (df["seniority"] == "senior") | (yrs >= 3)
    s = np.where(too_senior, np.minimum(s, 35), s)
    return pd.Series(np.clip(np.round(s), 0, 100), index=df.index).astype(int)


def fit_label(score):
    return pd.Series(np.select([score >= 80, score >= 60, score >= 45], ["Top pick", "Good", "Maybe"], "Stretch"), index=score.index)


def pros_cons(r):
    pros, cons = [], []
    if r["seniority"] == "intern":
        pros.append("Internship, no experience needed.")
    elif r["seniority"] == "junior":
        pros.append("Junior level.")
    if r["domain"] in ("data_science", "ml_engineering"):
        pros.append("Real data science or ML work.")
    if r["work_setup"] == "Hybrid":
        pros.append("Hybrid work setup.")
    elif r["work_setup"] == "Remote":
        pros.append("Remote work possible.")

    if r["seniority"] == "senior":
        cons.append("Senior level.")
    y = r.get("years_required")
    if y is not None and not pd.isna(y) and y >= 2:
        cons.append(f"Asks for {int(y)} years of experience.")
    if "Dutch" in (r.get("languages_required") or []):
        cons.append("Requires Dutch.")
    if r["work_setup"] == "On site":
        cons.append("On site, no hybrid option stated.")
    elif r["work_setup"] == "Unknown":
        cons.append("Work setup not stated.")
    if r["domain"] == "analytics":
        cons.append("Mostly analytics, little modelling.")
    return " ".join(pros[:3]), " ".join(cons[:2])
