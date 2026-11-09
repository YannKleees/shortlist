import os

import pandas as pd

from .extract import DEFAULT_MODEL, llm_extract, rule_extract
from .score import fit_label, prior_score, pros_cons
from .similarity import cv_similarity

APP_SETUP = {"Hybrid": "Hybrid", "Remote": "Remote", "On site": "On site", "Unknown": "Unknown"}


def job_text(j):
    return j.get("posting_text") or " ".join(str(j.get(k) or "") for k in ("role", "location", "pros", "cons", "notes"))


def frame(jobs, cv, use_llm=False):
    texts = [job_text(j) for j in jobs]
    ext = [llm_extract(t, cv, model=os.environ.get("SHORTLIST_CLAUDE_MODEL", DEFAULT_MODEL)) if use_llm else rule_extract(t) for t in texts]
    df = pd.concat([pd.DataFrame(jobs).reset_index(drop=True), pd.DataFrame(ext)], axis=1)
    df = df.loc[:, ~df.columns.duplicated(keep="last")]
    df["location"] = df.get("location", pd.Series([""] * len(df))).fillna("")
    df["sim"] = cv_similarity(texts, cv or "data science python", method="tfidf") if len(texts) else []
    df["prior"] = prior_score(df) if len(df) else []
    return df


def score_job(job, cv):
    use_llm = bool(os.environ.get("ANTHROPIC_API_KEY")) and bool(job.get("posting_text"))
    df = frame([job], cv, use_llm=use_llm)
    r = df.iloc[0]
    rule_pros, rule_cons = pros_cons(r)
    out = {
        "score": int(r["prior"]),
        "fit": fit_label(df["prior"]).iloc[0],
        "pros": job.get("pros") or r.get("pros") or rule_pros,
        "cons": job.get("cons") or r.get("cons") or rule_cons,
    }
    if not job.get("work_setup") or job.get("work_setup") == "Unknown":
        out["work_setup"] = APP_SETUP[r["work_setup"]]
    if not job.get("type"):
        out["type"] = r["job_type"]
    if not job.get("deadline") and r.get("deadline"):
        out["deadline"] = r["deadline"]
    return out
