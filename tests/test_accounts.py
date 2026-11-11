import json
from types import SimpleNamespace

from conftest import signed_in
from fastapi.testclient import TestClient

from shortlist import cvreview, db
from shortlist.server import create_app

POSTING = ("Junior Data Scientist at Northwind. You build forecasting models in Python and SQL, and pipelines with Spark and Airflow. "
           "Hybrid, two days at home. We are a 200 person logistics software company in Luxembourg. ") * 2


def blocked(url):
    raise RuntimeError("403")


def app(tmp_path, **kw):
    sent = []
    a = create_app(tmp_path / "a.db", fetch=kw.pop("fetch", blocked), wiki_get=None, geo_get=None,
                   push_send=lambda info, **k: sent.append((info["endpoint"], json.loads(k["data"]))), env={}, **kw)
    a.state.sent = sent
    return a


def join(a, owner, name="Mama"):
    token = owner.post("/api/people/invite", json={"name": name}).json()["token"]
    c = TestClient(a)
    info = c.get(f"/api/auth/invite/{token}").json()
    assert info["name"] == name and info["for"] == "Yann"
    assert c.post("/api/auth/join", json={"token": token}).status_code == 200
    assert c.post("/api/auth/join", json={"token": token}).status_code == 404, "an invite works once"
    return c


def test_first_start_asks_for_an_owner_then_needs_sign_in(tmp_path):
    a = app(tmp_path)
    c = TestClient(a)
    assert c.get("/api/auth/state").json() == {"needsSetup": True, "user": None}
    assert c.get("/api/jobs").status_code == 401
    assert c.post("/api/auth/setup", json={"name": "Yann", "password": "short"}).status_code == 422
    assert c.post("/api/auth/setup", json={"name": "Yann", "password": "correct horse"}).json()["user"]["role"] == "owner"
    assert c.get("/api/jobs").status_code == 200
    assert TestClient(a).post("/api/auth/setup", json={"name": "Eve", "password": "12345678"}).status_code == 409, "only once"

    c.post("/api/auth/logout")
    assert c.get("/api/jobs").status_code == 401
    assert c.post("/api/auth/login", json={"name": "yann", "password": "wrong pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"name": "yann", "password": "correct horse"}).status_code == 200
    assert c.get("/api/jobs").status_code == 200


def test_sessions_and_passwords_are_not_stored_in_clear(tmp_path):
    a = app(tmp_path)
    c = signed_in(a)
    con = db.connect(tmp_path / "a.db")
    row = con.execute("SELECT password FROM users").fetchone()[0]
    assert row.startswith("scrypt$") and "correct horse" not in row
    token = c.cookies.get("shortlist_session")
    assert token and con.execute("SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)).fetchone()[0] == 0


def test_cross_site_requests_are_refused(tmp_path):
    c = signed_in(app(tmp_path))
    r = c.post("/api/jobs", json={"company": "Acme"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/jobs", json={"company": "Acme"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_helper_adds_jobs_sees_fit_but_cannot_change_settings(tmp_path):
    a = app(tmp_path)
    owner = signed_in(a)
    mama = join(a, owner)
    owner.post("/api/push/subscribe", json={"endpoint": "https://push.example/yann", "keys": {"p256dh": "k", "auth": "a"}})

    r = mama.post("/api/jobs/add", json={"text": "Data Analyst - Contoso Bank - Luxembourg\nhttps://lu.indeed.com/m/viewjob?jk=abc1"}).json()
    job, outcome = r["results"][0]["job"], r["results"][0]["outcome"]
    assert outcome == "added" and job["addedBy"] == "Mama" and job["company"] == "Contoso Bank"
    assert mama.get("/api/jobs").json()[0]["id"] == job["id"]
    assert "llm" not in mama.get("/api/status").json(), "helpers do not see your settings"
    for method, path in [("put", "/api/settings"), ("delete", f"/api/jobs/{job['id']}"), ("get", "/api/export"), ("get", "/api/people")]:
        assert getattr(mama, method)(path, **({"json": {}} if method == "put" else {})).status_code == 403

    a.state.pusher.notify("x", "y", role="nobody", wait=True)  # wait for the background sends
    titles = [p["title"] for _, p in a.state.sent]
    assert "Mama sent you a job" in titles

    mama.post("/api/push/subscribe", json={"endpoint": "https://push.example/mama", "keys": {"p256dh": "k", "auth": "a"}})
    owner.patch(f"/api/jobs/{job['id']}", json={"status": "Applied"})
    a.state.pusher.notify("x", "y", role="nobody", wait=True)
    assert any(ep.endswith("/mama") and "applied to the job you sent" in p["title"] for ep, p in a.state.sent)

    assert mama.post(f"/api/jobs/{job['id']}/notes", json={"text": "Call them on Monday"}).status_code == 200
    assert owner.get(f"/api/jobs/{job['id']}").json()["events"][0]["text"] == "Mama: Call them on Monday"


def test_adding_twice_is_ignored_or_improves_the_job(tmp_path):
    c = signed_in(app(tmp_path))
    first = c.post("/api/jobs/add", json={"text": "Junior Data Scientist - Northwind - Luxembourg https://lu.indeed.com/viewjob?jk=n1"}).json()
    j = first["results"][0]["job"]
    assert not j["hasText"]
    again = c.post("/api/jobs/add", json={"text": "https://lu.indeed.com/m/viewjob?jk=n1&from=share"}).json()["results"][0]
    assert again["outcome"] == "exists" and again["job"]["id"] == j["id"]
    better = c.post("/api/jobs/add", json={"text": f"https://lu.indeed.com/viewjob?jk=n1\n{POSTING}"}).json()["results"][0]
    assert better["outcome"] == "improved" and better["job"]["hasText"] and better["job"]["workSetup"] == "Hybrid"
    assert len(c.get("/api/jobs").json()) == 1


def test_a_list_of_links_adds_every_job_and_pasted_text_works_alone(tmp_path):
    c = signed_in(app(tmp_path))
    answer = """Here are three jobs I found:
1. **Data Analyst – Contoso Bank** (Luxembourg)
   https://lu.indeed.com/viewjob?jk=a1
2. Junior Data Scientist - Fabrikam - Esch https://www.linkedin.com/jobs/view/4011111111/
3. ML Intern at Northwind: https://careers.northwind.example/jobs/42"""
    res = c.post("/api/jobs/add", json={"text": answer}).json()["results"]
    assert [r["outcome"] for r in res] == ["added"] * 3
    assert {r["job"]["company"] for r in res} == {"Contoso Bank", "Fabrikam", "Northwind"}

    text = c.post("/api/jobs/add", json={"text": POSTING}).json()["results"][0]
    assert text["job"]["hasText"] and text["job"]["source"] == "Pasted text"
    assert c.post("/api/jobs/add", json={"text": "hello"}).status_code == 422


def test_share_key_for_the_iphone_share_sheet(tmp_path):
    a = app(tmp_path)
    c = signed_in(a)
    url = c.get("/api/me").json()["shareUrl"]
    key = url.split("key=")[1]
    anon = TestClient(a)
    r = anon.post(f"/api/share?key={key}", json={"text": "Check out this job at Fabrikam: Data Intern https://www.linkedin.com/jobs/view/4022222222/"})
    assert r.status_code == 200 and r.text.startswith("Added: Data Intern at Fabrikam")
    assert anon.post(f"/api/share?key={key}", content="https://www.linkedin.com/jobs/view/4022222222/").text.startswith("Already saved")
    assert anon.post("/api/share?key=nope", json={"text": "x"}).status_code == 401


def test_people_can_be_listed_relinked_and_removed(tmp_path):
    a = app(tmp_path)
    owner = signed_in(a)
    join(a, owner)
    people = owner.get("/api/people").json()
    assert [p["name"] for p in people] == ["Yann", "Mama"]
    mama_id = people[1]["id"]
    token = owner.post(f"/api/people/{mama_id}/link").json()["token"]
    phone = TestClient(a)
    assert phone.get(f"/api/auth/invite/{token}").json()["existing"] is True
    assert phone.post("/api/auth/join", json={"token": token}).json()["user"]["name"] == "Mama"
    assert owner.post("/api/people/invite", json={"name": "mama"}).status_code == 409
    assert owner.delete(f"/api/people/{people[0]['id']}").status_code == 422
    assert owner.delete(f"/api/people/{mama_id}").status_code == 200
    assert phone.get("/api/jobs").status_code == 401, "removing a person signs them out everywhere"


def test_daily_reminder_once_a_day(tmp_path):
    a = app(tmp_path)
    c = signed_in(a)
    c.post("/api/push/subscribe", json={"endpoint": "https://push.example/y", "keys": {"p256dh": "k", "auth": "a"}})
    jid = c.post("/api/jobs", json={"company": "Acme", "role": "Intern"}).json()["id"]
    c.patch(f"/api/jobs/{jid}", json={"status": "Applied", "appliedOn": "2026-10-01", "followUp": "2026-10-11"})
    assert a.state.daily("2026-10-12") == ["1 follow up due (Acme)"]
    assert a.state.daily("2026-10-12") is None


def test_cv_review_rules_and_claude(tmp_path):
    good = ("Yann Example · yann@example.com · +352 621 123 456 · linkedin.com/in/yann · github.com/yann\n"
            "Experience\nData Science Intern, Northwind, 2025 to 2026\nBuilt a forecasting model that cut stock outs by 18%.\n"
            "Automated weekly reports for 40 people.\nLed a 3 person student project.\nEducation\nMSc Data Science, 2024 to 2026\n"
            "Skills\nPython, SQL, pandas, scikit-learn, PyTorch, Power BI, Git\n" + "Worked on NLP models for document classification. " * 40)
    r = cvreview.review(good)
    assert r["score"] >= 80 and r["by"] == "rules"
    weak = cvreview.review("I am motivated and like computers.")
    assert weak["score"] < 40 and weak["fixes"]

    calls = []

    def create(**kw):
        calls.append(kw)
        body = {"score": 72, "verdict": "Clear, but light on results.", "strengths": ["Relevant internship"],
                "fixes": [{"issue": "No summary", "fix": "Add two lines on top: who you are and what you look for."}], "missing": ["Docker"]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    c = signed_in(app(tmp_path, claude=fake))
    up = c.post("/api/cv", files={"file": ("cv.txt", good.encode(), "text/plain")}).json()
    assert up["review"]["by"] == "rules" and not calls, "uploading only runs the free checks"
    deep = c.post("/api/cv/review", json={"deep": True}).json()
    assert deep["missing"] == ["Docker"] and deep["by"].startswith("Claude") and 60 < deep["score"] < 90
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert c.get("/api/status").json()["review"]["verdict"] == "Clear, but light on results."


def test_letters_with_claude(tmp_path):
    def create(**kw):
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Dear Northwind team,\n\nBody.")])

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    c = signed_in(app(tmp_path, claude=fake))
    c.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, NLP.", "text/plain")})
    jid = c.post("/api/jobs", json={"company": "Northwind", "role": "DS Intern"}).json()["id"]
    lt = c.post(f"/api/jobs/{jid}/letters", json={"language": "English"}).json()
    assert lt["text"].startswith("Dear Northwind") and lt["model"] == "Claude (claude-opus-5-5)"


def test_jobs_show_what_you_have_and_what_you_need(tmp_path):
    c = signed_in(app(tmp_path))
    c.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, SQL, pandas.", "text/plain")})
    j = c.post("/api/jobs/add", json={"text": POSTING}).json()["results"][0]["job"]
    assert {"Python", "SQL"} <= set(j["have"]) and {"Spark", "Airflow"} <= set(j["need"])


def test_computer_icon_signs_the_owner_in(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from shortlist import db, launch
    path = tmp_path / "icon.db"
    monkeypatch.setenv("SHORTLIST_DB", str(path))
    con = db.connect(str(path))
    assert launch.sign_in_page("http://x") == "http://x/"  # nobody yet: the first start screen
    uid = db.add_user(con, "Yann", "owner", "password1")
    page = launch.sign_in_page("http://x")
    assert page.startswith("http://x/#/join/") and page.endswith("/auto")
    inv = db.get_invite(con, page.split("/#/join/")[1].removesuffix("/auto"))
    assert inv["user_id"] == uid
    assert datetime.fromisoformat(inv["expires_at"]) < datetime.now(UTC) + timedelta(minutes=6)


def test_github_projects_count_as_skills_and_show_on_jobs(tmp_path):
    repos = [
        {"name": "Yann", "description": "Profile README", "topics": []},
        {"name": "flows", "description": "Delivery pipelines", "language": "Python", "topics": ["apache-spark", "airflow"],
         "html_url": "https://github.com/Yann/flows", "pushed_at": "2026-10-01T00:00:00Z", "default_branch": "main"},
        {"name": "game", "description": "A board game", "language": "Java", "topics": ["minimax"], "default_branch": "main"},
    ]
    calls = []

    def get(url, **kw):
        calls.append(url)
        if "/users/nobody/" in url:
            return SimpleNamespace(status_code=404)
        if url.endswith("/repos"):
            return SimpleNamespace(status_code=200, json=lambda: repos)
        if "flows" in url:
            return SimpleNamespace(status_code=200, text="# flows\n![badge](x.svg)\nForecasting with **Spark** and Airflow DAGs.")
        return SimpleNamespace(status_code=404, text="")

    a = app(tmp_path, github_get=get)
    c = signed_in(a)
    c.post("/api/cv", files={"file": ("cv.txt", b"MSc data science. Python, SQL, pandas.", "text/plain")})
    j = c.post("/api/jobs/add", json={"text": POSTING}).json()["results"][0]["job"]
    assert "Spark" in j["need"]

    assert c.put("/api/github", json={"user": "https://github.com/nobody"}).status_code == 502
    assert c.put("/api/github", json={"user": "not a name!"}).status_code == 422
    r = c.put("/api/github", json={"user": "https://github.com/Yann/"}).json()
    assert r["user"] == "Yann" and [p["name"] for p in r["projects"]] == ["flows", "game"], "the profile README is not a project"
    assert {"Spark", "Airflow"} <= set(r["projects"][0]["skills"]) and r["rescored"] == 1

    d = c.get(f"/api/jobs/{j['id']}").json()
    assert {"Spark", "Airflow"} <= set(d["have"]) and "Spark" not in d["need"]
    assert [p["name"] for p in d["projects"]] == ["flows"]
    assert c.get("/api/status").json()["github"]["user"] == "Yann"

    assert c.put("/api/github", json={"user": ""}).json()["projects"] == []
    assert "Spark" in c.get(f"/api/jobs/{j['id']}").json()["need"]


def test_github_names_and_readmes():
    from shortlist import github
    assert github.username("@YannKleees") == "YannKleees"
    assert github.username("https://github.com/YannKleees?tab=repositories") == "YannKleees"
    assert github.username("two words") == ""
    assert github.readme_text("# Title\n[![b](u)](l) Uses [PyTorch](https://pytorch.org).\n```py\nimport x\n```") == "Title Uses PyTorch."


def test_projects_for_a_job_prefer_distinctive_skills():
    from shortlist import github
    mk = lambda name, skills, topics=(): {"name": name, "url": "u", "description": "", "skills": skills, "topics": list(topics)}
    projects = [mk("a", ["Python"]), mk("b", ["Python"]), mk("c", ["Python"]), mk("d", ["Python"]),
                mk("nlp", ["Python", "NLP"]), mk("pii", ["Python"], ["rust"])]
    picked = github.for_job(projects, "We trust you with Python and NLP work.")
    assert [p["name"] for p in picked] == ["nlp"], "Python alone is too common; rust is not in trust"
    assert picked[0]["matched"][0] == "NLP"


def test_cv_from_latex_or_an_overleaf_zip():
    import io
    import zipfile

    from shortlist import cvparse
    tex = (r"\documentclass{article}\newcommand{\resumeItem}[1]{\item #1}\begin{document}"
           "\n" r"\textbf{\Huge Ana Lys} \\ \href{https://linkedin.com/in/ana}{LinkedIn} % private note" "\n"
           r"\section{Experience}\resumeSubheading{Data Intern}{2025 -- 2026}{Caf\'e Lux}{Luxembourg}"
           r"\resumeItem{Cut costs by 20\% with \textbf{Python}}\end{document}")
    text = cvparse.extract_text("cv.tex", tex.encode())
    assert "Ana Lys" in text and "LinkedIn (https://linkedin.com/in/ana)" in text and "private note" not in text
    assert "Data Intern | 2025 \u2013 2026 | Caf\u00e9 Lux | Luxembourg" in text and "- Cut costs by 20% with Python" in text
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.tex", tex)
        z.writestr("res.cls", "x")
    assert cvparse.extract_text("cv.zip", buf.getvalue()) == text
