import json
import os

import pandas as pd

from . import brief
from .extract import DEFAULT_MODEL, llm_extract, rule_extract, salary_text
from .score import SPOKEN, explain, fit_label, prior_score, pros_cons, total
from .similarity import cv_similarity
from .skills import gaps

APP_SETUP = {"Hybrid": "Hybrid", "Remote": "Remote", "On site": "On site", "Unknown": "Unknown"}


def job_text(j):
    return j.get("posting_text") or " ".join(str(j.get(k) or "") for k in ("role", "location", "pros", "cons", "notes"))


def extract(text, cv, title, use_llm):
    if use_llm:
        try:
            return llm_extract(text, cv, model=os.environ.get("SHORTLIST_CLAUDE_MODEL", DEFAULT_MODEL))
        except Exception:  # no network or no credit: the rules still give a fair score
            pass
    return rule_extract(text, title)


def frame(jobs, cv, use_llm=False, spoken=None, profile=None):
    texts = [job_text(j) for j in jobs]
    ext = [extract(t, cv, j.get("role", ""), use_llm) for t, j in zip(texts, jobs, strict=True)]
    df = pd.concat([pd.DataFrame(jobs).reset_index(drop=True), pd.DataFrame(ext)], axis=1)
    df = df.loc[:, ~df.columns.duplicated(keep="last")]
    df["location"] = df.get("location", pd.Series([""] * len(df))).fillna("")
    # The work setup the user chose wins over the one read from the posting.
    chosen = [j.get("work_setup") if j.get("work_setup") in APP_SETUP and j.get("work_setup") != "Unknown" else None for j in jobs]
    df["work_setup"] = [c or w for c, w in zip(chosen, df["work_setup"], strict=True)]
    df["sim"] = cv_similarity(texts, cv or "data science python", method="tfidf") if len(texts) else []
    df["has_cv"] = bool(cv)
    df["prior"] = prior_score(df, spoken, profile) if len(df) else []
    return df


def score_job(job, cv, distance_km=None, spoken=None, profile=None):
    """Score, reasons and the facts about one job. `profile` is what you want (job titles, levels, setup, your years
    of experience) and your degrees; without it the old fixed weights apply."""
    use_llm = bool(os.environ.get("ANTHROPIC_API_KEY")) and bool(job.get("posting_text"))
    df = frame([{**job, "distance_km": distance_km}], cv, use_llm=use_llm, spoken=spoken, profile=profile)
    r = df.iloc[0].to_dict()
    facts = brief.facts(job.get("posting_text") or "", r, cv, profile)
    r["degree_fit"] = facts["degreeFit"]
    have, need = gaps(job_text(job), cv, r.get("languages_required") or [], spoken or SPOKEN)
    if job.get("posting_text"):
        r["have"], r["need"] = have, [n for n in need if n not in (r.get("languages_required") or [])]
    parts = explain(r, spoken, profile)
    score = pd.Series([total(parts, r, profile)])
    rule_pros, rule_cons = pros_cons(r, spoken, profile)
    out = {
        "score": int(score.iloc[0]),
        "fit": fit_label(score).iloc[0],
        "pros": job.get("pros") or r.get("pros") or rule_pros,
        "cons": job.get("cons") or r.get("cons") or rule_cons,
        "reasons": json.dumps(parts),
        "facts": json.dumps(facts),
        "distance_km": distance_km,
    }
    out["skills"], out["needs"] = json.dumps(have), json.dumps(need)
    if not job.get("work_setup") or job.get("work_setup") == "Unknown":
        out["work_setup"] = APP_SETUP[r["work_setup"]]
    if not job.get("type"):
        out["type"] = r["job_type"]
    if not job.get("deadline") and r.get("deadline"):
        out["deadline"] = r["deadline"]
    if not job.get("salary") and job.get("posting_text"):
        out["salary"] = salary_text(job["posting_text"])
    return out
