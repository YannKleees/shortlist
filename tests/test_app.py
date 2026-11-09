import io
import json
import sqlite3

import docx
import pytest
from fastapi.testclient import TestClient

from shortlist import cvparse, db, ingest, letters
from shortlist.server import create_app

LINKEDIN_HTML = """<html><head>
<meta property="og:title" content="Northwind Analytics hiring Data Science Intern in Luxembourg, Luxembourg | LinkedIn">
</head><body><div class="description">Northwind Analytics builds forecasting software for logistics companies across Europe.
In this internship you will build NLP models that classify shipping documents. You will work with Python, pandas and scikit-learn.
Hybrid, two days home office per week. About us: Northwind Analytics is a 200 person software company founded in 2012 in Luxembourg.
</div></body></html>"""

INDEED_LD = """<html><head><script type="application/ld+json">{"@context": "https://schema.org", "@type": "JobPosting",
"title": "Junior Data Scientist", "hiringOrganization": {"@type": "Organization", "name": "Contoso Bank",
"description": "Contoso Bank is a private bank serving clients in Luxembourg and Belgium."},
"jobLocation": {"@type": "Place", "address": {"addressLocality": "Kirchberg", "addressCountry": "LU"}},
"description": "<p>You will build credit risk models in <b>Python</b>. Hybrid.</p>"}</script></head><body></body></html>"""


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


# Database


def test_db_jobs_roundtrip_and_dedupe(tmp_path):
    con = db.connect(tmp_path / "t.db")
    jid = db.upsert_job(con, {"company": "Acme", "role": "Data Intern", "status": "To apply"})
    assert db.get_job(con, jid)["company"] == "Acme"
    assert db.upsert_job(con, {"company": "acme ", "role": "data intern", "summary": "x"}) == jid
    assert len(db.list_jobs(con)) == 1 and db.get_job(con, jid)["summary"] == "x"
    db.delete_job(con, jid)
    assert db.list_jobs(con) == []


def test_db_contacts_and_events_belong_to_a_job(tmp_path):
    con = db.connect(tmp_path / "t.db")
    jid = db.upsert_job(con, {"company": "Acme"})
    cid = db.add_contact(con, jid, {"name": "Marie Weber", "relation": "Recruiter", "email": "marie@acme.example"})
    db.update_contact(con, cid, {"notes": "Met at Unicareers"})
    assert db.list_contacts(con, jid)[0]["notes"] == "Met at Unicareers"
    db.add_event(con, jid, {"kind": "Email sent", "text": "Asked about hybrid work", "date": "2026-11-05"})
    db.add_event(con, jid, {"kind": "Reply", "text": "They answered", "date": "2026-11-07"})
    assert [e["kind"] for e in db.list_events(con, jid)] == ["Reply", "Email sent"], "newest first"
    db.delete_job(con, jid)
    assert db.list_contacts(con, jid) == [] and db.list_events(con, jid) == []


def test_db_migrates_an_older_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, company TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    old.execute("INSERT INTO jobs VALUES ('a', 'Acme', '2026-01-01', '2026-01-01')")
    old.commit()
    old.close()
    con = db.connect(path)
    j = db.get_job(con, "a")
    assert j["company"] == "Acme" and j["cv_sent"] == 0 and j["summary"] == ""


def test_db_cv_and_letters(tmp_path):
    con = db.connect(tmp_path / "t.db")
    db.set_cv(con, "cv.txt", "Python and NLP", b"raw")
    assert db.get_cv(con)["text"] == "Python and NLP"
    jid = db.upsert_job(con, {"company": "Acme"})
    lid = db.add_letter(con, jid, "English", "Dear team", "llama3.1:8b")
    db.update_letter(con, lid, "Dear hiring team")
    assert db.list_letters(con, jid)[0]["text"] == "Dear hiring team"


# CV parsing


def test_cv_text_and_docx():
    assert cvparse.extract_text("cv.md", b"# Yann\nPython") == "# Yann\nPython"
    d = docx.Document()
    d.add_paragraph("Skills: Python, SQL")
    buf = io.BytesIO()
    d.save(buf)
    assert "Python, SQL" in cvparse.extract_text("cv.docx", buf.getvalue())
    with pytest.raises(ValueError):
        cvparse.extract_text("cv.png", b"x")


# Reading postings


def test_detect_and_canonicalize_links():
    assert ingest.detect_source("https://www.linkedin.com/jobs/view/4012345678/?trk=x") == "LinkedIn"
    assert ingest.canonical_link("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678") == "https://www.linkedin.com/jobs/view/4012345678/"
    assert ingest.canonical_link("https://lu.indeed.com/viewjob?jk=abc123def&from=serp") == "https://lu.indeed.com/viewjob?jk=abc123def"
    assert ingest.detect_source("https://careers.example.com/job/1") == "Company site"


def test_parse_linkedin_posting():
    p = ingest.parse_posting(LINKEDIN_HTML, "https://www.linkedin.com/jobs/view/1/")
    assert (p["company"], p["role"], p["location"]) == ("Northwind Analytics", "Data Science Intern", "Luxembourg, Luxembourg")
    assert "Hybrid" in p["text"]


def test_parse_json_ld_posting_with_company_description():
    p = ingest.parse_posting(INDEED_LD, "https://lu.indeed.com/viewjob?jk=1")
    assert (p["company"], p["role"], p["location"]) == ("Contoso Bank", "Junior Data Scientist", "Kirchberg, LU")
    assert p["about"].startswith("Contoso Bank is a private bank")
    assert "<b>" not in p["text"]


def test_summary_takes_the_first_sentences_about_the_role():
    p = ingest.parse_posting(LINKEDIN_HTML, "https://www.linkedin.com/jobs/view/1/")
    s = ingest.summarize(p["text"])
    assert s.startswith("Northwind Analytics builds") and len(s) < 400


def test_about_section_is_found_in_the_posting():
    text = ingest.parse_posting(LINKEDIN_HTML, "x")["text"]
    assert ingest.about_section(text, "Northwind Analytics").startswith("Northwind Analytics is a 200 person software company")


def test_wikipedia_about_only_accepts_organisations():
    def get(url, params=None, timeout=None, headers=None):
        if "opensearch" in str(params):
            return FakeResp(["ArcelorMittal", ["ArcelorMittal"], [], []])
        return FakeResp({"type": "standard", "description": "Luxembourg-based steel manufacturing corporation",
                         "extract": "ArcelorMittal is a multinational steel manufacturing corporation."})
    assert ingest.wikipedia_about("ArcelorMittal", get=get).startswith("ArcelorMittal is a multinational")

    def get_person(url, params=None, timeout=None, headers=None):
        if "opensearch" in str(params):
            return FakeResp(["Rotate", ["Rotate"], [], []])
        return FakeResp({"type": "standard", "description": "Mathematical operation", "extract": "Rotation is a motion."})
    assert ingest.wikipedia_about("Rotate", get=get_person) == ""


# Letters


def test_letter_prompt_and_generation():
    msgs = letters.build_messages("CV: Python, NLP", {"company": "Acme", "role": "DS Intern", "posting_text": "NLP"}, "French", "Mention my thesis")
    assert "French" in json.dumps(msgs) and "invent" in msgs[0]["content"].lower()

    def post(url, json=None, timeout=None):
        return FakeResp({"message": {"content": "  Dear Acme team  "}})
    assert letters.generate("cv", {"company": "Acme"}, post=post, url="http://o:1") == "Dear Acme team"


def test_letter_docx_export():
    d = docx.Document(io.BytesIO(letters.to_docx("Dear team,\n\nParagraph two.")))
    assert [p.text for p in d.paragraphs if p.text] == ["Dear team,", "Paragraph two."]


# API


@pytest.fixture
def client(tmp_path):
    def fetch(url):
        return LINKEDIN_HTML

    def post(url, json=None, timeout=None):
        return FakeResp({"message": {"content": "Dear Northwind Analytics team,\nLetter body."}})

    def get(url, params=None, timeout=None, headers=None):
        return FakeResp({"models": [{"name": "llama3.1:8b"}]})

    return TestClient(create_app(tmp_path / "api.db", fetch=fetch, llm_post=post, llm_get=get, wiki_get=None))


def test_api_import_link_fills_overview(client):
    r = client.post("/api/jobs/import-link", json={"url": "https://www.linkedin.com/jobs/view/4012345678/?trk=abc"})
    job = r.json()
    assert r.status_code == 200 and job["company"] == "Northwind Analytics" and job["source"] == "LinkedIn"
    assert job["summary"].startswith("Northwind Analytics builds")
    assert job["companyAbout"].startswith("Northwind Analytics is a 200 person")
    assert job["workSetup"] == "Hybrid" and job["pros"]
    again = client.post("/api/jobs/import-link", json={"url": "https://www.linkedin.com/jobs/view/4012345678/"})
    assert again.json()["id"] == job["id"]


def test_api_pasted_text_needs_no_fetch(tmp_path):
    def fetch(url):
        raise RuntimeError("login wall")
    c = TestClient(create_app(tmp_path / "p.db", fetch=fetch, wiki_get=None))
    url = "https://www.linkedin.com/jobs/view/4055555555/"
    r = c.post("/api/jobs/import-link", json={"url": url, "company": "Acme", "role": "NLP Intern", "text": "NLP internship, hybrid, Python. " * 12})
    assert r.status_code == 200 and r.json()["summary"].startswith("NLP internship") and r.json()["hasText"]


def test_api_unreadable_link_is_saved_and_text_can_follow(tmp_path):
    def fetch(url):
        raise RuntimeError("403 blocked")
    c = TestClient(create_app(tmp_path / "p.db", fetch=fetch, wiki_get=None, geo_get=None))
    shared = "Data Analyst - Contoso Bank - Luxembourg\nhttps://lu.indeed.com/m/viewjob?jk=abc123&from=share"
    j = c.post("/api/jobs/import-link", json={"url": shared, "addedBy": "Mama", "note": "Looks good"}).json()
    assert (j["company"], j["role"], j["location"], j["addedBy"], j["hasText"]) == ("Contoso Bank", "Data Analyst", "Luxembourg", "Mama", False)
    assert j["link"] == "https://lu.indeed.com/viewjob?jk=abc123"
    assert c.get(f"/api/jobs/{j['id']}").json()["events"][0]["text"] == "Mama: Looks good"
    assert c.post("/api/jobs/import-link", json={"url": "https://lu.indeed.com/viewjob?jk=abc123"}).json()["id"] == j["id"]

    assert c.post(f"/api/jobs/{j['id']}/text", json={"text": "too short"}).status_code == 422
    text = "Junior Data Analyst. You build Power BI reports and SQL models. Hybrid, two days at home. Salary: EUR 3,200 per month. " * 2
    j = c.post(f"/api/jobs/{j['id']}/text", json={"text": text}).json()
    assert j["hasText"] and j["workSetup"] == "Hybrid" and j["salary"] == "EUR 3,200 per month" and j["reasons"]


def test_api_application_tracking(client):
    jid = client.post("/api/jobs", json={"company": "Acme", "role": "DS Intern"}).json()["id"]
    j = client.patch(f"/api/jobs/{jid}", json={"status": "Applied"}).json()
    assert j["cvSent"] == 1 and j["appliedOn"] and j["followUp"]
    events = client.get(f"/api/jobs/{jid}").json()["events"]
    assert events[0]["kind"] == "Applied"

    r = client.post(f"/api/jobs/{jid}/events", json={"kind": "Reply", "text": "Invited to a call", "date": "2026-11-12"})
    assert r.status_code == 200
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["repliedOn"] == "2026-11-12" and j["status"] == "Applied"

    r = client.post(f"/api/jobs/{jid}/events", json={"kind": "Nonsense", "text": "x"})
    assert r.status_code == 422


def test_api_contacts(client):
    jid = client.post("/api/jobs", json={"company": "Acme"}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/contacts", json={"relation": "Friend"}).status_code == 422
    c = client.post(f"/api/jobs/{jid}/contacts", json={"name": "Tom", "relation": "Friend", "linkedin": "https://www.linkedin.com/in/tom"}).json()
    c = client.patch(f"/api/contacts/{c['id']}", json={"lastContact": "2026-11-08", "notes": "Works in the data team"}).json()
    assert c["lastContact"] == "2026-11-08"
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["contacts"][0]["name"] == "Tom"
    assert client.get("/api/jobs").json()[0]["contactCount"] == 1
    assert client.delete(f"/api/contacts/{c['id']}").status_code == 200


def test_api_letters_need_cv_then_work(client):
    jid = client.post("/api/jobs", json={"company": "Acme"}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/letters", json={}).status_code == 400
    client.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, NLP, scikit-learn.", "text/plain")})
    letter = client.post(f"/api/jobs/{jid}/letters", json={"language": "German"}).json()
    rev = client.post(f"/api/letters/{letter['id']}/revise", json={"instruction": "Shorter"}).json()
    assert rev["id"] != letter["id"] and rev["language"] == "German"
    assert client.get(f"/api/letters/{rev['id']}/download?format=docx").status_code == 200


def test_api_job_search_features_are_gone(client):
    for path in ("/api/import/alerts", "/api/import/imap", "/api/rank"):
        assert client.post(path).status_code in (404, 405)


def test_api_json_import_export_and_static(client):
    data = {"jobs": [{"company": "Gamma", "role": "ML Intern", "status": "To apply"}]}
    r = client.post("/api/import/json", files={"file": ("e.json", json.dumps(data).encode(), "application/json")})
    assert r.json()["added"] == 1
    assert client.get("/api/export").json()["jobs"][0]["company"] == "Gamma"
    assert "Shortlist" in client.get("/").text


def test_env_file_fills_missing_variables(tmp_path, monkeypatch):
    import os

    from shortlist.__main__ import load_env
    (tmp_path / ".env").write_text("SHORTLIST_TEST_A=from_file\nSHORTLIST_TEST_B='quoted'\n")
    monkeypatch.setenv("SHORTLIST_TEST_A", "already_set")
    monkeypatch.delenv("SHORTLIST_TEST_B", raising=False)
    load_env(tmp_path / ".env")
    assert os.environ["SHORTLIST_TEST_A"] == "already_set" and os.environ["SHORTLIST_TEST_B"] == "quoted"


def test_letters_drop_model_thinking():
    assert letters.clean_reply("<think>plan the letter</think>\n\nDear team,") == "Dear team,"
    assert letters.clean_reply("plan without opening tag</think>Dear team,") == "Dear team,"
    assert letters.clean_reply("Dear team,\nBody.") == "Dear team,\nBody."


def test_api_follow_up_moves_after_you_write_again(client):
    jid = client.post("/api/jobs", json={"company": "Acme", "role": "DS Intern"}).json()["id"]
    client.patch(f"/api/jobs/{jid}", json={"status": "Applied", "appliedOn": "2026-10-01", "followUp": "2026-10-11"})
    client.post(f"/api/jobs/{jid}/events", json={"kind": "Email sent", "text": "Follow up", "date": "2026-10-12"})
    assert client.get(f"/api/jobs/{jid}").json()["followUp"] == "2026-10-19"
    client.post(f"/api/jobs/{jid}/events", json={"kind": "Note", "text": "x", "date": "2026-10-20"})
    assert client.get(f"/api/jobs/{jid}").json()["followUp"] == "2026-10-19"


def test_api_new_cv_rescores_jobs_but_keeps_edits(client):
    jid = client.post("/api/jobs", json={"company": "Acme", "role": "NLP Intern", "pros": "My own note."}).json()["id"]
    r = client.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, NLP, scikit-learn.", "text/plain")}).json()
    assert r["rescored"] == 1
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["pros"] == "My own note." and isinstance(j["score"], int) and j["fit"]


def test_api_export_round_trip_keeps_people_timeline_letters_and_cv(client, tmp_path):
    client.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, NLP, scikit-learn.", "text/plain")})
    jid = client.post("/api/jobs", json={"company": "Acme", "role": "DS Intern"}).json()["id"]
    client.post(f"/api/jobs/{jid}/contacts", json={"name": "Marie", "relation": "Recruiter", "lastContact": "2026-11-01"})
    client.post(f"/api/jobs/{jid}/events", json={"kind": "Call", "text": "Intro call", "date": "2026-11-02"})
    client.post(f"/api/jobs/{jid}/letters", json={"language": "French"})
    r = client.get("/api/export")
    assert r.headers["content-disposition"].startswith('attachment; filename="shortlist-export-')
    dump = r.content

    other = TestClient(create_app(tmp_path / "other.db", wiki_get=None))
    for _ in range(2):  # importing twice must not duplicate anything
        assert other.post("/api/import/json", files={"file": ("e.json", dump, "application/json")}).status_code == 200
    j = other.get(f"/api/jobs/{jid}").json()
    assert [c["name"] for c in j["contacts"]] == ["Marie"] and j["contacts"][0]["lastContact"] == "2026-11-01"
    assert [e["kind"] for e in j["events"]] == ["Call"]
    assert len(j["letters"]) == 1 and j["letters"][0]["language"] == "French"
    assert other.get("/api/status").json()["cv"]["filename"] == "cv.txt"


def test_daily_backup_keeps_the_newest_copies(tmp_path):
    con = db.connect(tmp_path / "shortlist.db")
    db.upsert_job(con, {"company": "Acme"})
    con.close()
    folder = tmp_path / "backups"
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        (folder.mkdir(exist_ok=True), (folder / f"shortlist-{day}.db").write_bytes(b"old"))
    saved = db.backup(tmp_path / "shortlist.db", keep=2)
    copy = sqlite3.connect(saved)
    assert copy.execute("SELECT company FROM jobs").fetchone()[0] == "Acme"
    copy.close()
    assert sorted(p.name for p in folder.iterdir()) == ["shortlist-2026-01-03.db", saved.name]
    assert db.backup(tmp_path / "missing.db") is None


def test_shared_text_from_phone_apps():
    li = "Check out this job at Northwind Analytics: Data Science Intern\nhttps://www.linkedin.com/jobs/view/4012345678"
    assert ingest.find_links(li) == ["https://www.linkedin.com/jobs/view/4012345678"]
    assert ingest.parse_shared(li)["company"] == "Northwind Analytics"
    assert ingest.parse_shared("Data Analyst - Contoso Bank - Luxembourg") == {"role": "Data Analyst", "company": "Contoso Bank", "location": "Luxembourg"}
    assert ingest.parse_shared("ML Engineer at Fabrikam")["company"] == "Fabrikam"
    assert ingest.looks_like_job("https://lu.indeed.com/viewjob?jk=1") and not ingest.looks_like_job("https://example.com/blog/post")
