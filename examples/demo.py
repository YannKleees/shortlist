"""Build a database with made up data, to look at the app without your own jobs in it (and for screenshots).

    python examples/demo.py demo.db
    python -m shortlist --db demo.db --port 8011 --no-backup --no-find --mail-every 0

Sign in as Alex with the password "demo demo". Nothing in it is real."""
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from shortlist import db, discover  # noqa: E402
from shortlist.server import create_app  # noqa: E402

CV = """Alex Example
Luxembourg | alex@example.com | +352 600 000 000 | linkedin.com/in/alexexample | github.com/alexexample

SUMMARY
MSc Applied Data Science student looking for a junior data scientist or data analyst role in Luxembourg.

EXPERIENCE
Research Intern, Computer Vision | Jun 2025 - Aug 2025 | Northwind Labs | Luxembourg
- Built an object detection pipeline in PyTorch that cut manual labelling time by 60%
- Analysed 12,000 images and presented the results to 30 people
Data Analyst, Student Job | Sep 2024 - May 2025 | Contoso Mobility | Luxembourg
- Automated a weekly report in Python and SQL, saving 5 hours every week

EDUCATION
MSc Applied Data Science | University of Luxembourg | 2025 - 2027
BSc Data Science and Artificial Intelligence | Maastricht University | 2022 - 2025

SKILLS
Python, SQL, R, pandas, NumPy, scikit-learn, PyTorch, statistics, machine learning, NLP, computer vision, data visualisation, Git
Languages: English, French, German
"""

POSTINGS = [
    ("Junior Data Scientist at Northwind Labs, Luxembourg. Hybrid, two days at home. You build and evaluate machine learning models in "
     "Python with pandas, scikit-learn and PyTorch, work with SQL data, and explain results to the product team. You have a master in data "
     "science or statistics, 0 to 2 years of experience, and speak English and French. We are a 120 person software company. ") * 2,
    ("Data Analyst at Contoso Bank, Luxembourg City. On site. You write SQL, build Power BI dashboards and Excel reports for the risk "
     "department, and automate reporting in Python. Bachelor degree, 1 to 3 years of experience, English and French required, German is a "
     "plus. Contoso Bank is a private bank with 900 employees. ") * 2,
    ("Machine Learning Engineer at Fabrikam, Esch-sur-Alzette, Luxembourg. Hybrid. You bring models to production with Docker, Kubernetes "
     "and AWS, build data pipelines with Spark and Airflow, and own MLOps for the forecasting team. 3 years of experience, Python, English. ") * 2,
    ("Data Science Intern at Tailspin Logistics, Luxembourg. Internship of six months, hybrid. You explore delivery data with Python and "
     "pandas, build time series forecasts, and present visualisations to the operations team. For master students; English, French a plus. ") * 2,
    ("NLP Research Intern at Adventure Works, Belval, Luxembourg. Internship. You fine tune language models with Hugging Face and PyTorch for "
     "named entity recognition in French and German documents and evaluate them. Master student in data science or AI, English. ") * 2,
]
FOUND = [
    ("Junior Data Scientist", "Wingtip Toys", "LinkedIn", 0, "Junior Data Scientist, full-time, hybrid. Python, pandas and scikit-learn. Master in data "
     "science, 0 to 2 years of experience. Salary: €52,000 - 58,000 per year. English and French. " * 2),
    ("Data Analyst", "Litware", "jobs.lu", 2, "Data Analyst, on site in Luxembourg City, full time. SQL, Excel and Power BI. "
     "Bachelor degree, 1 year of experience. English. " * 2),
    ("Data Science Intern", "Proseware", "EURES", 5, "Internship of six months, remote. You explore data with Python and pandas and build forecasts. "
     "For master students. €1,500 per month. English. " * 2),
    ("Working Student Data Analytics", "Woodgrove Bank", "LinkedIn", 9, "Working student, part-time, hybrid. Reporting in SQL and Python "
     "for the risk team. English, French. " * 2),
    ("Machine Learning Engineer", "Trey Research", "ICTjob.lu", 20, "Machine Learning Engineer, hybrid, full-time. Docker, Kubernetes, AWS and MLOps. "
     "3 years of experience. English. " * 2),
    ("Data Analyst (m/f)", "Lucerne Publishing", "jobs.lu", 1, ""),
]
REPOS = [
    {"name": "parcel-forecast", "description": "Delivery time forecasts with gradient boosting and a small API", "language": "Python",
     "topics": ["time-series", "forecasting", "fastapi", "docker"], "license": {"key": "mit"}, "pushed_at": "2026-10-20T00:00:00Z"},
    {"name": "ner-letters", "description": "Named entity recognition for French and German letters", "language": "Python",
     "topics": ["nlp", "hugging-face", "pytorch"], "pushed_at": "2026-09-02T00:00:00Z"},
    {"name": "course-notes", "description": "", "language": "Jupyter Notebook", "topics": [], "pushed_at": "2025-12-11T00:00:00Z"},
]
README = "# {name}\n![result](docs/result.png)\n" + "What it does, how well it works, and what I learned from it. " * 25 + "\n## Usage\n`make run`\n"
LINKEDIN = """Alex Example
MSc student in Applied Data Science | Python and SQL

About
Data science student who likes turning messy data into something people can use.

Experience
Research Intern, Computer Vision
Northwind Labs
Built an object detection pipeline in PyTorch.

Education
University of Luxembourg
Maastricht University

Skills
Python
SQL
Machine learning
"""


def github_get(url, **kw):
    if url.endswith("/repos"):
        repos = [{**r, "html_url": f"https://github.com/alexexample/{r['name']}", "default_branch": "main"} for r in REPOS]
        return SimpleNamespace(status_code=200, json=lambda: repos)
    name = url.split("/")[4]
    return SimpleNamespace(status_code=200 if name != "course-notes" else 404, text=README.format(name=name))


def build(path):
    path = Path(path)
    for old in path.parent.glob(path.name + "*"):
        old.unlink()
    app = create_app(path, fetch=lambda url: "", wiki_get=None, geo_get=None, github_get=github_get, env={})
    c = TestClient(app)
    assert c.post("/api/auth/setup", json={"name": "Alex", "password": "demo demo"}).status_code == 200
    c.post("/api/cv", files={"file": ("cv.txt", CV.encode(), "text/plain")})
    c.put("/api/settings", json={"languages": "English, French, German", "home": "Luxembourg",
                                 "profile": {"roles": "Data Scientist, Data Analyst", "levels": ["intern", "junior"], "where": "Luxembourg",
                                             "setup": "Hybrid", "years": 0}})
    c.put("/api/github", json={"user": "alexexample"})
    c.put("/api/linkedin", json={"link": "https://www.linkedin.com/in/alex-example-1a2b3c4d5", "text": LINKEDIN})
    ids = [c.post("/api/jobs/add", json={"text": text}).json()["results"][0]["job"]["id"] for text in POSTINGS]
    day = lambda n: (date.today() + timedelta(days=n)).isoformat()
    con = db.connect(path)

    def mail(job, n, kind, subject, body, name=""):
        db.add_mail(con, job, {"msgid": f"<{job}-{n}-{kind}@demo>", "date": day(n), "kind": kind, "from": "careers@example.com", "name": name,
                               "subject": subject, "body": body})
        db.add_event(con, job, {"kind": {"sent": "Email sent", "confirmation": "Applied", "interview": "Interview", "rejection": "Rejection"}[kind],
                                "text": f"From careers@example.com: {subject}", "date": day(n)})

    northwind, contoso, fabrikam, tailspin, _ = ids
    mail(northwind, -9, "sent", "Application: Junior Data Scientist", "Dear hiring team, please find my CV and letter attached.")
    mail(northwind, -8, "confirmation", "We received your application", "Thank you for applying. We will be in touch.", "Northwind Careers")
    mail(northwind, -2, "interview", "Invitation to a first interview", "We would like to meet you next week for a first conversation.", "Maria Lopez")
    db.update_job(con, northwind, {"status": "Interview", "applied_on": day(-9), "cv_sent": 1, "replied_on": day(-8)})
    c.post(f"/api/jobs/{northwind}/events", json={"kind": "Interview", "date": day(3), "text": "14:30 · video call with the team lead"})
    mail(contoso, -6, "sent", "Application: Data Analyst", "Hello, I am applying for the Data Analyst role.")
    db.update_job(con, contoso, {"status": "Applied", "applied_on": day(-6), "cv_sent": 1, "follow_up": day(4)})
    mail(fabrikam, -12, "sent", "Application: Machine Learning Engineer", "Hello, I am applying for the ML Engineer role.")
    mail(fabrikam, -4, "rejection", "Your application at Fabrikam", "Unfortunately we decided to continue with other candidates.", "Fabrikam HR")
    db.update_job(con, fabrikam, {"status": "Rejected", "applied_on": day(-12), "cv_sent": 1, "replied_on": day(-4)})
    c.patch(f"/api/jobs/{tailspin}", json={"deadline": day(6)})
    # Found, not saved yet. The server scores them when it starts. The search counts as just done, so opening Find
    # does not send a real search to the job sites.
    db.set_setting(con, "finds_at", db.now())
    found = discover.Finds(con)
    for n, (title, company, source, age, text) in enumerate(FOUND):
        found.add({"id": f"demo-{n}", "title": title, "company": company, "location": "Luxembourg", "link": f"https://example.com/jobs/{n}",
                   "source": source, "posted": day(-age), "text": text, "read": 1 if text else 0})
    print(f"{path}: {len(ids)} jobs. Start it with: python -m shortlist --db {path} --port 8011 --no-backup --no-find --mail-every 0")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
