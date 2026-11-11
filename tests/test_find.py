import json
from datetime import date

from conftest import signed_in

from shortlist import brief, discover, ingest
from shortlist.extract import rule_extract, years_required
from shortlist.score import explain, total
from shortlist.server import create_app

POSTING = """About us
Northwind is a logistics software company in Luxembourg with 200 people.
What you'll do
• Build forecasting models in Python and track them with experiments.
• Design dashboards and reports in Power BI for the planning team.
• Present results to clients (e.g. in monthly workshops) and gather requirements.
Your profile
• Master's degree in Computer Science, Statistics or a related field. A PhD is a plus.
• At least 2 years of experience with machine learning in production.
• Fluent in English.
What we offer
• Hybrid work, two days at home.
"""
CV = """Yann Example
Data science MSc student looking for junior roles.
EDUCATION
Utrecht University | M.Sc. Applied Data Science | Sep 2026 - Aug 2027 (expected)
Maastricht University | B.Sc. Data Science and Artificial Intelligence | Sep 2023 - Jun 2026
SKILLS
Python, SQL, pandas, scikit-learn, PyTorch
"""


def card(num, title, company, place="Luxembourg, Luxembourg", day="2026-11-05"):
    return f"""<li><div class="base-card" data-entity-urn="urn:li:jobPosting:{num}">
      <a class="base-card__full-link" href="https://lu.linkedin.com/jobs/view/{title.lower().replace(' ', '-')}-at-x-{num}?position=1"></a>
      <h3 class="base-search-card__title">{title}</h3><h4 class="base-search-card__subtitle"><a>{company}</a></h4>
      <span class="job-search-card__location">{place}</span><time datetime="{day}">5 days ago</time></div></li>"""


def test_tasks_come_from_the_section_that_says_what_you_do():
    t = brief.tasks(POSTING)
    assert t[0] == "Build forecasting models in Python and track them with experiments"
    assert len(t) == 3 and "e.g. in monthly workshops" in t[2], "the dot in e.g. does not end the sentence"
    assert not any("Hybrid" in x or "Master" in x for x in t)


def test_tasks_from_a_list_on_one_line_and_from_plain_sentences():
    one_line = ("Your Tasks:\nResponsible for data analysis services to support the business / Working closely with the investment team "
                "to produce accurate input data / Supporting client enquiries by analysing data from investment databases / "
                "Maintaining the databases of third-party providers\nYour Profile:\nBachelor's degree")
    assert len(brief.tasks(one_line)) == 4
    flat = "We are a bank. You will build the credit risk models of the group and explain them to the regulator. You will also mentor interns."
    assert brief.tasks(flat)[0].startswith("You will build the credit risk models")
    assert brief.tasks("Call us.") == []


def test_mix_says_what_kind_of_work_fills_the_day():
    parts = brief.mix(POSTING)
    assert sum(p["share"] for p in parts) == 100 and parts[0]["share"] >= parts[-1]["share"]
    assert {"modelling", "analysis", "people"} <= {p["key"] for p in parts}
    assert brief.mix("A nice job.") == []


def test_degree_asked_takes_the_lowest_level_that_is_enough():
    d = brief.degree_asked(POSTING)
    assert d["level"] == "master" and d["related"] and "Computer science" in d["fields"], "the PhD is only a plus"
    assert brief.degree_asked("Bachelor's or Master's in economics")["level"] == "bachelor"
    assert brief.degree_asked("Diplôme Master (Bac+5) ou École d'Ingénieur en informatique")["level"] == "master"
    assert brief.degree_asked("You master data pipelines. Join our scrum master.") is None
    assert brief.degree_asked("You are currently pursuing a Master's degree in data science.")["student"]


def test_degrees_are_read_from_the_education_lines_of_a_cv():
    mine = brief.degrees(CV, today=date(2026, 11, 10))
    assert [(d["level"], d["done"]) for d in mine] == [("master", False), ("bachelor", True)], "the summary line is not a degree"
    assert mine[0]["field"] == "Applied Data Science" and mine[0]["year"] == 2027
    assert brief.degree_label(mine[1]) == "BSc Data Science and Artificial Intelligence"


def test_degree_fit_compares_what_is_asked_with_what_you_have():
    mine = brief.degrees(CV, today=date(2026, 11, 10))
    ask = lambda level, **kw: {"level": level, "fields": [], "related": True, "student": False, "quote": "", **kw}
    assert brief.degree_fit(None, mine) is None
    assert brief.degree_fit(ask("bachelor"), mine)["tone"] == "good"
    unfinished = brief.degree_fit(ask("master"), mine)
    assert unfinished["tone"] == "ok" and "expected 2027" in unfinished["note"]
    assert brief.degree_fit(ask("master", student=True), mine)["tone"] == "good", "a student job wants a running degree"
    assert brief.degree_fit(ask("phd"), mine)["tone"] == "bad"
    off = brief.degree_fit(ask("bachelor", fields=["Business"], related=False), mine)
    assert off["tone"] == "ok" and "not yours" in off["note"]
    assert brief.degree_fit(ask("bachelor"), [])["tone"] == "ok"


def test_years_take_the_lower_end_of_a_range():
    assert years_required("entre 2 et 5 ans d'expérience pratique") == 2
    assert years_required("vous disposez de 3 à 8 ans d'expérience en analyse") == 3
    assert rule_extract("", "Data Analyst Sénior h/f")["seniority"] == "senior"


def test_score_follows_what_you_asked_for():
    profile = {"roles": ["Data Analyst"], "levels": ["junior"], "setup": "Remote", "years": 0}
    r = {"role": "Junior Data Analyst (m/f)", "seniority": "junior", "domain": "analytics", "work_setup": "Remote", "distance_km": 10, "sim": 0.2}
    parts = {p["key"]: p for p in explain(r, profile=profile)}
    assert parts["field"]["points"] == 35 and parts["level"]["points"] == 30 and parts["setup"]["points"] == 15
    assert {p["key"]: p for p in explain(r)}["field"]["points"] == 18, "without wishes the general weights apply"
    other = {p["key"]: p for p in explain({**r, "role": "Data Engineer", "domain": "data_engineering"}, profile=profile)}
    assert other["field"]["points"] == 15 and "not the field" in other["field"]["note"]


def test_experience_is_weighed_against_your_own_years():
    r = {"role": "Data Scientist", "seniority": "unknown", "domain": "data_science", "work_setup": "Hybrid", "years_required": 4}
    new = explain(r, profile={"roles": ["Data Scientist"], "years": 0})
    exp = next(p for p in new if p["key"] == "experience")
    assert exp["tone"] == "bad" and exp["note"] == "Asks for 4 years of experience. You have under 1 year."
    assert total(new, r, {"years": 0}) <= 35
    seasoned = {"roles": ["Data Scientist"], "years": 3}
    assert next(p for p in explain(r, profile=seasoned) if p["key"] == "experience")["tone"] == "good"
    assert total(explain(r, profile=seasoned), r, seasoned) > 35


def test_text_lines_keeps_headings_and_bullets_apart():
    html = "<div><strong>What you'll do</strong><br><ul><li>Build <b>models</b></li><li>Ship them</li></ul><p>Apply now.</p></div>"
    assert ingest.text_lines(html).splitlines() == ["What you'll do", "• Build models", "• Ship them", "Apply now."]


def test_search_reads_result_cards_once_each():
    page = card(111, "Data Scientist", "Northwind") + card(222, "Senior Data Analyst", "Contoso") + "<li>an advert</li>"
    found = discover.parse_linkedin_search(page)
    assert [f["id"] for f in found] == ["li-111", "li-222"]
    assert found[0] == {"id": "li-111", "title": "Data Scientist", "company": "Northwind", "location": "Luxembourg, Luxembourg",
                        "link": "https://www.linkedin.com/jobs/view/111/", "posted": "2026-11-05", "source": "LinkedIn"}
    asked = []
    out = discover.search({"roles": ["Data Scientist", "Data Analyst"], "where": ["Luxembourg"], "levels": ["intern", "junior"]},
                          fetch=lambda url: asked.append(url) or page, sleep=lambda s: None, sources=["linkedin"])
    assert len(out) == 2 and len(asked) == 2, "the same job under two job titles counts once"
    assert "keywords=Data+Scientist" in asked[0] and "location=Luxembourg" in asked[0] and "f_E=1%2C2%2C3" in asked[0]


def test_search_says_so_when_nothing_answers():
    def down(url):
        raise RuntimeError("offline")
    try:
        discover.search({"roles": ["Data Scientist"], "where": ["Luxembourg"]}, fetch=down, post=lambda url, body: down(url),
                        sleep=lambda s: None)
    except RuntimeError as e:
        assert "did not answer" in str(e)
    else:
        raise AssertionError("expected an error")


JOBS_LU = """<article class="job-list-item" id="job-id-501"><span class="date"> 1 Day Ago </span>
  <h2><a class="job-title" href="https://en.jobs.lu/ApplyForJob.aspx?Id=501">Data Scientist (m/f/d)</a></h2>
  <h3><a class="recruiter-name" href="/northwind/">Northwind S.A. </a></h3><span class="location">Esch-sur-Alzette, Luxembourg</span></article>
  <article class="job-list-item" id="job-id-502"><span class="date">09 Nov</span>
  <h2><a class="job-title" href="https://en.jobs.lu/ApplyForJob.aspx?Id=502">KYC Analyst</a></h2>
  <h3><a class="recruiter-name" href="/c/">Contoso</a></h3><span class="location">Luxembourg</span></article>"""
EURES = {"jvs": [
    {"id": "ODQz/MSA5", "title": "Analyste de données (H/F)", "description": "Vous analysez les données de la banque. " * 20,
     "creationDate": 1794182400000, "employer": {"name": "Non renseigné"}},
    {"id": "abc", "title": "Data Scientist (H/F)", "description": "x", "creationDate": None, "employer": {"name": "NORTHWIND (Luxembourg) SA"}},
    {"id": "def", "title": "Chef de chantier", "description": "", "employer": {"name": "Bati"}}]}


def test_each_site_is_read_its_own_way():
    today = date(2026, 11, 11)
    a, b = discover.parse_jobs_lu(JOBS_LU, today)
    assert a == {"id": "jl-501", "title": "Data Scientist (m/f/d)", "company": "Northwind S.A.", "location": "Esch-sur-Alzette, Luxembourg",
                 "link": "https://en.jobs.lu/ApplyForJob.aspx?Id=501", "posted": "2026-11-10", "source": "jobs.lu", "text": ""}
    assert b["posted"] == "2026-11-09"
    e = discover.parse_eures(EURES, "Luxembourg")
    assert e[0]["id"] == "eu-ODQzMSA5" and e[0]["company"] == "" and "ODQz%2FMSA5" in e[0]["link"] and len(e[0]["text"]) > 400
    efc = discover.parse_efc({"data": [{"jobId": "7", "title": "Data Analyst", "companyName": "Fabrikam", "detailsPageUrl": "/jobs-x.id7",
                                        "jobLocation": {"displayName": "Luxembourg"}, "postedDate": "2026-11-03T04:21:00Z",
                                        "description": "<p>Build reports.</p><ul><li>Clean data</li></ul>"}]})[0]
    assert efc["link"] == "https://www.efinancialcareers.com/jobs-x.id7" and efc["posted"] == "2026-11-03" and "Build reports.\n" in efc["text"]
    amz = discover.parse_amazon({"jobs": [{"id_icims": "9", "title": "Data Scientist", "job_path": "/en/jobs/9/ds", "posted_date": "October 19, 2026",
                                           "normalized_location": "Luxembourg, LUX", "description": "Forecast demand.",
                                           "basic_qualifications": "- Master's degree<br/>- 2+ years of experience"}]})[0]
    assert amz["company"] == "Amazon" and amz["posted"] == "2026-10-19" and "Basic qualifications\n- Master's degree\n" in amz["text"]
    page = """<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"dehydratedState": {"queries": [
        {"state": {"data": {"offers": [{"offer": {"id": "6ae3", "title": {"fr": "Analyste de données (m/f)"}, "visible_online": "2026-11-11T00:00:00"},
                                        "company": {"name": "CSSF"}}]}}},
        {"state": {"data": {"offer": {"job": {"description": {"en": "<h2>Mission</h2><ul><li>Prepare dashboards</li></ul>"}}}}}}]}}}}</script>"""
    assert discover.parse_jobfinder(page)[0]["link"] == "https://www.jobfinder.lu/en/jobs/6ae3"
    assert discover.jobfinder_text(page) == "Mission\n• Prepare dashboards"
    ict = discover.parse_ictjob("""<li class="search-item"><a class="job-title" href="https://www.ictjob.lu/en/job/keyteo-data-analyst/1-21 ">
        <h2>Data Analyst</h2></a><span class="job-company"> Keyteo</span><span class="job-date">23/12</span></li>""", today)[0]
    assert ict["id"] == "ict-1-21" and ict["company"] == "Keyteo" and ict["posted"] == "2025-12-23", "a date still to come was last year"


def test_one_job_on_three_sites_counts_once_and_only_what_was_asked_stays():
    prof = {"roles": ["Data Scientist", "Data Analyst"], "where": ["Luxembourg"], "levels": ["junior"]}
    assert discover.relevant("Analyste de données (H/F)", prof) and discover.relevant("Machine Learning Researcher", prof)
    assert not discover.relevant("KYC Analyst", prof) and not discover.relevant("Database Administrator", prof)
    assert discover.relevant("Infirmier de nuit", {"roles": ["Nurse"]}) and not discover.relevant("Data Analyst", {"roles": ["Nurse"]})
    assert discover.clean_title("Data Scientist (m/f/d)") == "Data Scientist" and discover.clean_title("Analyste (H/F) - CDI") == "Analyste - CDI"
    seen = discover.Seen([("Banque Internationale à Luxembourg BIL", "MIS Data Analyst (m/f)")])
    assert seen.has("Banque Internationale a Luxembourg SA", "MIS Data Analyst") and not seen.has("Contoso", "MIS Data Analyst")
    assert not seen.has("", "MIS Data Analyst"), "without a company name nobody can tell"
    assert discover.country_of("Esch-sur-Alzette") == "lu" and discover.country_of("Trier") == "de" and discover.country_of("Mars") == ""

    def fetch(url):
        if "seeMoreJobPostings" in url:
            return card(111, "Data Scientist", "Northwind")
        if "jobs.lu" in url:
            return JOBS_LU
        raise RuntimeError("down")
    report = {}
    out = discover.search(prof, fetch=fetch, post=lambda url, body: json.dumps(EURES), sleep=lambda s: None, report=report)
    assert [(f["source"], f["title"]) for f in out] == [("LinkedIn", "Data Scientist"), ("EURES", "Analyste de données")]
    assert report["LinkedIn"] == {"found": 1, "ok": True} and report["jobs.lu"] == {"found": 0, "ok": True}, "its one job was on LinkedIn already"
    assert report["ICTjob.lu"] == {"found": 0, "ok": False} and report["EURES"]["found"] == 1

    far = {}
    discover.search({**prof, "where": ["Lisbon"]}, fetch=fetch, post=lambda url, body: "{}", sleep=lambda s: None, report=far)
    assert list(far) == ["LinkedIn"], "the Luxembourg sites are not asked about Lisbon"


def test_find_jobs_look_at_one_save_it_skip_another(tmp_path):
    search_page = card(111, "Data Scientist", "Northwind") + card(222, "Senior Data Analyst", "Contoso") + card(333, "Data Analyst", "Fabrikam")
    job_page = f"""<div class="topcard__org-name-link">Northwind</div><h1 class="top-card-layout__title">Data Scientist</h1>
        <span class="topcard__flavor--bullet">Luxembourg</span><div class="show-more-less-html__markup">{POSTING.replace(chr(10), "<br>")}</div>"""
    fetch = lambda url: search_page if "seeMoreJobPostings" in url else job_page
    eures = {"jvs": [{"id": "e1", "title": "Data Scientist (H/F)", "description": POSTING, "employer": {"name": "Tailspin"}},
                     {"id": "e2", "title": "Data Analyst (m/f)", "description": POSTING, "employer": {"name": "FABRIKAM S.A."}}]}
    a = create_app(tmp_path / "a.db", fetch=fetch, post=lambda url, body: json.dumps(eures), wiki_get=None, geo_get=None, env={})
    c = signed_in(a)
    assert c.post("/api/finds/search").status_code == 422, "it needs to know what to look for"
    c.post("/api/cv", files={"file": ("cv.txt", CV.encode(), "text/plain")})
    st = c.put("/api/settings", json={"profile": {"roles": "Data Scientist, Data Analyst", "levels": ["junior"], "where": "Luxembourg", "years": "0"}}).json()
    assert st["profile"]["roles"] == ["Data Scientist", "Data Analyst"] and st["profile"]["degrees"][0].startswith("MSc Applied Data Science")

    r = c.post("/api/finds/search").json()
    assert r["added"] == 3 and sorted(f["id"] for f in r["items"]) == ["eu-e1", "li-111", "li-333"], "no senior job, Fabrikam once"
    assert r["sources"]["LinkedIn"] == {"found": 3, "ok": True} and r["sources"]["EURES"]["found"] == 1 and not r["sources"]["jobs.lu"]["found"]
    whole = next(f for f in r["items"] if f["id"] == "eu-e1")
    assert whole["read"] and whole["source"] == "EURES" and whole["facts"]["years"] == 2, "EURES sends the posting with the result"
    assert c.post("/api/finds/eu-e1/skip").json() == {"id": "eu-e1"}
    assert c.get("/api/status").json()["finds"]["new"] == 2
    r["items"] = [f for f in r["items"] if f["id"] != "eu-e1"]
    assert c.post("/api/finds/search").json()["added"] == 0, "the same jobs are not found twice"

    guess = r["items"][0]
    assert not guess["read"] and guess["score"] is not None
    full = c.post("/api/finds/li-111/read").json()
    assert full["read"] and full["facts"]["years"] == 2 and full["facts"]["degree"]["level"] == "master"
    assert full["facts"]["tasks"][0].startswith("Build forecasting models")
    assert {p["key"] for p in full["reasons"]} >= {"field", "level", "experience", "degree"}

    job = c.post("/api/finds/li-111/save").json()
    assert job["company"] == "Northwind" and job["hasText"] and job["facts"]["mix"], "the posting comes along, no second download"
    assert c.post("/api/finds/li-333/skip").json() == {"id": "li-333"}
    assert c.get("/api/finds").json()["items"] == []
    assert c.post("/api/finds/search").json()["added"] == 0, "saved and skipped jobs do not come back"
    assert c.post("/api/finds/li-999/read").status_code == 404

    # Twice a day the app searches by itself and tells your phone about the jobs that fit.
    sent = []
    a.state.pusher.notify = lambda title, body, **kw: sent.append((title, body, kw.get("url")))
    assert a.state.find() is None, "it searched a moment ago"
    c.put("/api/settings", json={"profile": {"roles": "Data Scientist", "levels": ["junior"], "where": "Luxembourg", "years": "2"}})
    eures["jvs"].append({"id": "e9", "title": "Data Scientist", "description": POSTING, "employer": {"name": "Wingtip"}})
    good = a.state.find(every_hours=0, pause=0)
    assert [f["id"] for f in good] == ["eu-e9"] and sent[-1][0] == "1 new job that fits you" and sent[-1][2] == "/#/find"
    assert "Data Scientist at Wingtip" in sent[-1][1]
    assert a.state.find(every_hours=0, pause=0) == [] and len(sent) == 1, "nothing new, no notification"


def test_a_job_page_says_what_the_job_is(tmp_path):
    a = create_app(tmp_path / "a.db", fetch=lambda url: "", wiki_get=None, geo_get=None, env={})
    c = signed_in(a)
    c.post("/api/cv", files={"file": ("cv.txt", CV.encode(), "text/plain")})
    job = c.post("/api/jobs/add", json={"text": "Data Scientist at Northwind, Luxembourg\n" + POSTING}).json()["results"][0]["job"]
    f = job["facts"]
    assert f["years"] == 2 and f["yearsQuote"].startswith("• At least 2 years") and len(f["tasks"]) == 3
    assert f["degreeFit"]["tone"] == "ok" and f["myDegrees"][0] == "MSc Applied Data Science (in progress)"
    notes = {p["key"]: p["note"] for p in job["reasons"]}
    assert notes["experience"] == "Asks for 2 years of experience. You have under 1 year."
    assert "skills it names" in notes["cv"]
    helper_view = c.get(f"/api/jobs/{job['id']}").json()
    assert helper_view["facts"]["tasks"] == f["tasks"]
