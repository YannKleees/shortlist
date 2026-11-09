import re
import sqlite3
from email.message import EmailMessage

from fastapi.testclient import TestClient

from shortlist import geo, mail
from shortlist.score import explain
from shortlist.server import create_app

ME = "jobs@example.com"
POINTS = {"luxembourg": [{"lat": "49.6116", "lon": "6.1319"}], "esch-sur-alzette": [{"lat": "49.4958", "lon": "5.9806"}]}


def fake_geo(calls=None):
    def get(url, params=None, headers=None, timeout=None):
        if calls is not None:
            calls.append(params["q"])
        return type("R", (), {"json": lambda self: POINTS.get(params["q"], [])})()
    return get


def raw(uid, sender, to, subject, body, day="Mon, 03 Nov 2026 10:00:00 +0100"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"], m["Message-ID"] = sender, to, subject, day, f"<m{uid}@test>"
    m.set_content(body)
    return m.as_bytes()


class FakeImap:
    """Just enough of imaplib.IMAP4_SSL for Gmail: INBOX, All Mail with X-GM-RAW search, read only."""

    def __init__(self, messages, password="right"):
        self.messages, self.password, self.folder = messages, password, None  # (uid, sent, bytes)
        self.capabilities = ("IMAP4REV1", "X-GM-EXT-1")

    def __call__(self, host, port):
        return self

    def login(self, user, pw):
        if pw != self.password:
            raise mail.imaplib.IMAP4.error("bad login")

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                      b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

    def select(self, folder, readonly=False):
        assert readonly, "the app must never change the mailbox"
        self.folder = folder.strip('"')
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "FETCH":
            uid = args[0].decode() if isinstance(args[0], bytes) else args[0]
            assert args[1] == "(BODY.PEEK[])"
            return "OK", [(b"1 (BODY[] {n}", next(b for u, _, b in self.messages if str(u) == uid))]
        if args[0] == "UID":
            low = int(args[1].split(":")[0])
            hits = [u for u, sent, _ in self.messages if not sent and u >= low]
        else:
            q = args[1][1:-1].replace('\\"', '"')
            sent = not q.startswith("-")
            words = re.search(r'"(.+)"', q).group(1).lower()
            hits = [u for u, s, b in self.messages if s == sent and words in b.decode().lower()]
        return "OK", [" ".join(map(str, hits)).encode()]

    def logout(self):
        pass


def test_haversine_and_cached_geocoding(tmp_path):
    assert round(geo.haversine_km((49.6116, 6.1319), (49.4958, 5.9806))) == 17  # Luxembourg City to Esch-sur-Alzette
    calls = []
    g = geo.Geocoder(sqlite3.connect(tmp_path / "g.db"), get=fake_geo(calls), pause=0)
    assert g.distance_km("Luxembourg", "Esch-sur-Alzette") == 17
    assert g.distance_km("Luxembourg", "Esch-sur-Alzette") == 17 and len(calls) == 2, "answers are cached"
    assert g.locate("Nowhere at all") is None and g.locate("Nowhere at all") is None and len(calls) == 4, "misses too"
    assert g.locate("Remote, Europe") is None and len(calls) == 4


def test_explain_says_why():
    r = {"seniority": "intern", "domain": "data_science", "work_setup": "Hybrid", "distance_km": 12, "sim": 0.4,
         "languages_required": ["English", "Dutch"], "location": "Luxembourg"}
    parts = {p["key"]: p for p in explain(r)}
    assert parts["distance"]["note"] == "12 km from home." and parts["distance"]["tone"] == "good"
    assert parts["languages"]["points"] == -15 and "Dutch" in parts["languages"]["note"]
    assert explain({**r, "languages_required": ["Dutch"]}, spoken=["English", "Dutch"])[-1]["tone"] == "good"


def test_shared_jobs_and_evidence():
    msgs = [mail.parse_message(1, raw(1, "Maria <mama@example.com>", ME, "[Shortlist] Mama: Data Analyst at Contoso",
                                      "https://lu.indeed.com/viewjob?jk=abc\n\nThis one is close to home\n\nSent with Shortlist")),
            mail.parse_message(2, raw(2, "news@example.com", ME, "Weekly news", "Read more https://example.com/blog/post")),
            mail.parse_message(3, raw(3, "Tom <tom@example.com>", ME, "Fwd: job", "Look https://careers.fabrikam.example/jobs/42"))]
    items = mail.shared_jobs(msgs, ME)
    assert [(i["link"], i["by"]) for i in items] == [("https://lu.indeed.com/viewjob?jk=abc", "Mama"),
                                                      ("https://careers.fabrikam.example/jobs/42", "Tom")]
    assert items[0]["note"] == "This one is close to home" and items[0]["title"] == "Data Analyst at Contoso"

    sent = [mail.parse_message(5, raw(5, ME, "hr@contoso.example", "Application Data Analyst", "Dear Contoso team, please find my CV."))]
    got = [mail.parse_message(6, raw(6, "hr@contoso.example", ME, "Re: Application", "We would like to invite you to an interview.")),
           mail.parse_message(7, raw(7, "jobs-noreply@linkedin.com", ME, "Jobs at Contoso", "New jobs at Contoso")),
           mail.parse_message(8, raw(8, "noreply@myworkday.example", ME, "Contoso", "Unfortunately your application was not selected."))]
    assert [e["kind"] for e in mail.evidence(sent, got, ME)] == ["sent", "interview", "rejection"]


def test_check_mail_adds_shared_jobs_and_marks_applications(tmp_path):
    def fetch(url):
        raise RuntimeError("blocked")
    box = FakeImap([
        (1, False, raw(1, "Maria <mama@example.com>", ME, "[Shortlist] Mama: Data Analyst - Contoso Bank - Luxembourg",
                       "https://lu.indeed.com/viewjob?jk=abc\n\nFor you!")),
        (2, True, raw(2, ME, "hr@contoso.example", "My application: Data Analyst", "Dear Contoso Bank team, attached my CV.",
                      day="Tue, 04 Nov 2026 09:00:00 +0100")),
        (3, False, raw(3, "hr@contoso.example", ME, "Your application at Contoso Bank",
                       "Thank you. Unfortunately we decided to move forward with other candidates.", day="Fri, 07 Nov 2026 09:00:00 +0100")),
    ])
    c = TestClient(create_app(tmp_path / "m.db", fetch=fetch, wiki_get=None, geo_get=None, imap_factory=box))
    assert c.post("/api/mail/check").json()["ok"] is False, "not set up yet"
    c.put("/api/settings", json={"mail_address": ME, "mail_password": "rig ht"})
    assert c.post("/api/mail/check").json() == {"ok": True, "added": 1, "applied": 1, "replies": 1, "message": ""}
    j = c.get("/api/jobs").json()[0]
    assert (j["company"], j["addedBy"], j["status"], j["appliedOn"], j["repliedOn"]) == ("Contoso Bank", "Mama", "Rejected", "2026-11-04", "2026-11-07")
    kinds = [e["kind"] for e in c.get(f"/api/jobs/{j['id']}").json()["events"]]
    assert kinds.count("Rejection") == 1 and "Email sent" in kinds and "Note" in kinds

    again = c.post("/api/mail/check").json()
    assert (again["added"], again["applied"], again["replies"]) == (0, 0, 0), "nothing twice"
    assert c.get("/api/status").json()["mail"]["ready"] is True

    c.put("/api/settings", json={"mail_password": "wrong"})
    assert "refused" in c.post("/api/mail/check").json()["message"]


def test_settings_home_and_languages_rescore(tmp_path):
    c = TestClient(create_app(tmp_path / "s.db", wiki_get=None, geo_get=fake_geo()))
    jid = c.post("/api/jobs", json={"company": "Acme", "role": "Data Science Intern", "location": "Esch-sur-Alzette"}).json()["id"]
    st = c.put("/api/settings", json={"home": "Luxembourg", "languages": "English, Dutch"}).json()
    assert st["home"] == "Luxembourg" and st["languages"] == "English, Dutch"
    j = c.get(f"/api/jobs/{jid}").json()
    assert j["distanceKm"] == 17 and any(p["note"] == "17 km from home." for p in j["reasons"])
