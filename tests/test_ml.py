
import pandas as pd

from shortlist.extract import llm_extract, rule_extract, validate
from shortlist.score import fit_label, prior_score, pros_cons
from shortlist.similarity import cv_similarity

CV = "MSc Applied Data Science. Python, pandas, scikit-learn, PyTorch, NLP, SQL. Research intern in computer vision."


def test_rule_extract_reads_level_setup_and_languages():
    t = "Data Science Internship in Luxembourg. Hybrid, 2 days home office. Python and NLP. Fluent Dutch required."
    d = rule_extract(t)
    assert d["seniority"] == "intern"
    assert d["work_setup"] == "Hybrid"
    assert d["domain"] == "data_science"
    assert "Dutch" in d["languages_required"]


def test_rule_extract_reads_years_and_senior():
    d = rule_extract("Senior Data Engineer. At least 5 years of experience with Spark. On-site in Amsterdam.")
    assert d["seniority"] == "senior"
    assert d["years_required"] == 5
    assert d["work_setup"] == "On site"


def test_validate_coerces_unknown_values():
    d = validate({"seniority": "wizard", "work_setup": "sometimes", "years_required": "3", "skills": "python"})
    assert d["seniority"] == "unknown"
    assert d["work_setup"] == "Unknown"
    assert d["years_required"] == 3
    assert d["skills"] == []


class FakeBlock:
    type = "tool_use"
    def __init__(self, data):
        self.input = data


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return type("R", (), {"content": [FakeBlock(self.data)]})()


def test_llm_extract_forces_the_tool_and_validates():
    fake = FakeClient({"seniority": "junior", "domain": "data_science", "work_setup": "Hybrid",
                       "years_required": 1, "languages_required": ["English"], "skills": ["Python"],
                       "job_type": "Job", "pros": "NLP work.", "cons": "French preferred."})
    d = llm_extract("posting text", CV, client=fake, model="m")
    assert d["seniority"] == "junior" and d["pros"] == "NLP work."
    kw = fake.calls[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "record_job"}
    assert kw["model"] == "m"


def test_similarity_prefers_the_matching_posting():
    texts = ["NLP data scientist with Python, pandas and PyTorch", "Truck driver, night shifts, license C"]
    s = cv_similarity(texts, CV, method="tfidf")
    assert s.shape == (2,) and s[0] > s[1]


def test_prior_score_ranks_junior_hybrid_data_science_first():
    df = pd.DataFrame([
        {"seniority": "intern", "years_required": None, "domain": "data_science", "work_setup": "Hybrid",
         "location": "Luxembourg", "languages_required": ["English"], "sim": 0.6},
        {"seniority": "senior", "years_required": 6, "domain": "data_science", "work_setup": "On site",
         "location": "Luxembourg", "languages_required": ["English"], "sim": 0.6},
        {"seniority": "junior", "years_required": 0, "domain": "analytics", "work_setup": "Hybrid",
         "location": "Utrecht", "languages_required": ["Dutch"], "sim": 0.3},
    ])
    s = prior_score(df)
    assert s.between(0, 100).all()
    assert s.iloc[0] > s.iloc[2] > s.iloc[1]
    assert fit_label(s).tolist()[0] == "Top pick"


def test_pros_cons_fallback_is_concrete():
    row = {"seniority": "intern", "domain": "data_science", "work_setup": "On site",
           "languages_required": ["Dutch"], "years_required": None}
    p, c = pros_cons(row)
    assert "Internship" in p and "Dutch" in c and "On site" in c


def test_rule_extract_uses_the_title_for_level_and_domain():
    d = rule_extract("Build NLP models with mentoring from senior data scientists. Our staff of 200 lead the market.", "Data Science Intern")
    assert d["seniority"] == "intern" and d["domain"] == "data_science"
    assert rule_extract("You join a friendly team.", "Lead Data Analyst")["seniority"] == "senior"
    assert rule_extract("Python and SQL.", "Werkstudent Data Science")["job_type"] == "Working student"


def test_rule_extract_ignores_years_that_are_not_experience():
    assert rule_extract("Founded 150 years ago. A 2 year contract.")["years_required"] is None
    assert rule_extract("Founded 150 years ago. You bring 1-2 years of experience in SQL.")["years_required"] == 1
    assert rule_extract("3+ years experience with Python.")["years_required"] == 3


def test_rule_extract_languages_need_to_be_asked_for():
    d = rule_extract("We are a Dutch company. Fluent English required. Dutch is a plus.")
    assert d["languages_required"] == ["English"]
    d = rule_extract("Fluent Dutch required, German is a plus. Languages: French (a plus).")
    assert d["languages_required"] == ["Dutch"]
    assert rule_extract("Sehr gute Deutschkenntnisse.")["languages_required"] == ["German"]


def test_salary_is_read_when_the_posting_states_it():
    from shortlist.extract import salary_text
    assert salary_text("Salary: EUR 1,500 - 2,000 per month gross.") == "EUR 1,500 - 2,000 per month gross"
    assert salary_text("We offer 45k EUR per year.") == "45k EUR per year"
    assert salary_text("A EUR 2 billion company with a EUR 5 lunch voucher.") == ""
    assert salary_text("Python and SQL.") == ""
