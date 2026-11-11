import imaplib
import json
import mimetypes
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import NAME, brief, cvparse, cvreview, db, discover, geo, github, ingest, letters, llm, mail, portfolio
from .extract import hours_text, rule_extract
from .push import Pusher
from .score import SPOKEN
from .scoring import score_job
from .skills import GROUPS as SKILL_GROUPS

WEB = Path(__file__).resolve().parent.parent / "web"
CAMEL = {"work_setup": "workSetup", "next_step": "nextStep", "added_by": "addedBy", "applied_on": "appliedOn",
         "follow_up": "followUp", "created_at": "createdAt", "updated_at": "updatedAt", "uploaded_at": "uploadedAt",
         "job_id": "jobId", "posting_text": "postingText", "company_about": "companyAbout", "cv_sent": "cvSent",
         "replied_on": "repliedOn", "contact_count": "contactCount", "letter_count": "letterCount", "last_contact": "lastContact",
         "distance_km": "distanceKm", "sent_by_user": "sentByUser", "sender_name": "senderName"}
SNAKE = {v: k for k, v in CAMEL.items()}
STATUSES = ["To apply", "Applied", "Waiting", "Interview", "Accepted", "Rejected", "Not interested"]
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
HELPER_PAGE = os.environ.get("SHORTLIST_HELPER_PAGE", "https://yannkleees.github.io/shortlist/")
COOKIE = "shortlist_session"
# The kinds of notification a person can switch off: answers from companies, jobs somebody sent, jobs the search found,
# the morning summary, and (for the people who help) the steps of the search.
PUSH_KINDS = ("reply", "job", "find", "daily", "status")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self'; font-src 'self'; "
                               "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
}
LOOKING_FOR = "Junior data science roles, internships or working student jobs, ideally hybrid."

# What a helper (someone who sends you jobs) may do. Everything else under /api is for the owner.
PUBLIC = [("GET", r"/api/health"), ("GET", r"/api/auth/state"), ("POST", r"/api/auth/(?:login|setup|join)"),
          ("GET", r"/api/auth/invite/[^/]+"), ("POST", r"/api/share")]
HELPER = [("GET", r"/api/status"), ("GET", r"/api/calendar"),
          ("GET", r"/api/jobs"), ("GET", r"/api/jobs/[^/]+"), ("GET", r"/api/map"), ("GET", r"/api/jobs/[^/]+/travel"),
          ("POST", r"/api/jobs/add"),
          ("POST", r"/api/jobs/import-link"), ("POST", r"/api/jobs/[^/]+/notes"), ("GET|PUT", r"/api/me"),
          ("POST|DELETE", r"/api/push/subscribe"), ("POST", r"/api/push/test"), ("POST", r"/api/auth/logout")]


def _match(rules, method, path):
    return any(re.fullmatch(m, method) and re.fullmatch(p, path) for m, p in rules)


def _json(v, empty):
    try:
        return json.loads(v) if isinstance(v, str) and v else (v or empty)
    except ValueError:
        return empty


def to_api(d):
    out = {CAMEL.get(k, k): v for k, v in d.items() if k not in ("posting_text", "content", "skills", "needs")}
    if "reasons" in out:
        out["reasons"] = _json(out["reasons"], [])
    if "skills" in d:
        out["have"], out["need"] = _json(d["skills"], []), _json(d.get("needs"), [])
    if "posting_text" in d:
        out["hasText"] = bool(d["posting_text"])
    if "facts" in out:
        out["facts"] = _json(out["facts"], None)
    return out


LEVELS = ["intern", "junior", "mid", "senior"]


def clean_profile(p):
    """What you are looking for, as saved: job titles, levels, work setup, places to search, years of experience."""
    p = p if isinstance(p, dict) else {}
    words = lambda v: [w.strip()[:60] for w in (v.split(",") if isinstance(v, str) else v or []) if str(w).strip()][:8]
    try:
        years = max(0, min(40, int(float(p.get("years") or 0))))
    except (TypeError, ValueError):
        years = 0
    return {"roles": words(p.get("roles")), "levels": [lv for lv in LEVELS if lv in (p.get("levels") or [])],
            "setup": p.get("setup") if p.get("setup") in ("Hybrid", "Remote", "On site") else "",
            "where": words(p.get("where"))[:3], "years": years}


def user_api(u):
    return {"id": u["id"], "name": u["name"], "role": u["role"], "hasPassword": bool(u.get("password")), "lastSeen": u.get("last_seen", "")}


def _clean_line(s):
    # "1. **Data Analyst – Contoso** (Luxembourg)" -> "Data Analyst – Contoso - Luxembourg"
    s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s+", "", s)
    s = re.sub(r"\s*\(([^)]*)\)", r" - \1", s)
    return re.sub(r"[*_#>`\[\]]+", " ", s).strip(" -–•:|.\t")


from_api = lambda d: {SNAKE.get(k, k): v for k, v in d.items()}
FOLLOW_UP_DAYS = 10
NUDGE_DAYS = 7
NUDGES = ("Email sent", "Message sent", "Call")
OPEN = ("To apply", "Applied", "Waiting", "Interview")


def create_app(db_path="shortlist.db", fetch=ingest.fetch, llm_post=requests.post, llm_get=requests.get, wiki_get=requests.get,
               geo_get=requests.get, imap_factory=imaplib.IMAP4_SSL, claude=None, push_send=None, env=None, github_get=requests.get,
               post=None):
    env = os.environ if env is None else env
    if post is None:  # a test that brings its own fetch must not reach the real job sites through the other door

        def offline(url, body):
            raise RuntimeError("no network here")
        post = ingest.post_json if fetch is ingest.fetch else offline
    con = db.connect(db_path)
    app = FastAPI(title=NAME)
    places = geo.Geocoder(con, get=geo_get)
    roads = geo.Router(con, get=geo_get)
    setting = lambda k, default="": db.get_setting(con, k, default) or default
    cv_text = lambda: (db.get_cv(con) or {}).get("text", "")
    projects = lambda: _json(setting("github_projects"), [])
    # What you can show: the CV plus your GitHub projects. Scores, have and need, and letters use both.
    evidence = lambda: "\n\n".join(x for x in (cv_text(), github.as_text(projects())) if x)
    spoken = lambda: [s.strip() for s in setting("languages", ", ".join(SPOKEN)).split(",") if s.strip()]
    finds = discover.Finds(con)

    def profile():
        # What you want, plus the degrees on your CV. Without saved wishes the general weights apply.
        return {**clean_profile(_json(setting("profile"), {})), "degrees": brief.degrees(cv_text())}

    pusher = Pusher(con, subject=lambda: f"mailto:{setting('mail_address')}" if setting("mail_address") else "", send=push_send)
    public_url = lambda: env.get("SHORTLIST_PUBLIC_URL", "").rstrip("/")
    failed_logins = {}
    llm_seen = {}  # whether the model answered, for 30 seconds, so pages do not wait on a stopped Ollama

    def model():
        key = setting("anthropic_key") or env.get("ANTHROPIC_API_KEY", "")
        provider = setting("llm_provider") or ("claude" if key or claude else "ollama")
        if provider == "claude":
            return llm.LLM("claude", setting("claude_model") or env.get("SHORTLIST_LETTER_MODEL", llm.CLAUDE_MODEL), api_key=key, claude=claude)
        return llm.LLM("ollama", setting("llm_model") or env.get("OLLAMA_MODEL", letters.DEFAULT_MODEL),
                       url=setting("llm_url") or env.get("OLLAMA_URL", letters.DEFAULT_URL), post=llm_post, get=llm_get)

    def job_or_404(jid):
        j = db.get_job(con, jid)
        if not j:
            raise HTTPException(404, "Job not found.")
        return j

    def scored(job, cv=None):
        home, place = setting("home"), job.get("location") or ""
        km = places.distance_km(home, place) if home and place and job.get("work_setup") != "Remote" else None
        return score_job(job, evidence() if cv is None else cv, distance_km=km, spoken=spoken(), profile=profile())

    def save_scored(job):
        return db.get_job(con, db.upsert_job(con, {**job, **scored(job)}))

    def rescore_one(j, cv=None):
        s = scored(j, cv)
        return db.update_job(con, j["id"], {k: s.get(k) for k in ("score", "fit", "reasons", "distance_km", "skills", "needs", "facts")})

    def rescore_all():
        # A new CV, home or language list changes every score. Pros, cons and other edits stay as they are.
        cv = evidence()
        jobs = db.list_jobs(con)
        for j in jobs:
            rescore_one(j, cv)
        for f in finds.new():  # what was found but not saved yet follows the new wishes too
            finds.update(f["id"], score_find(f, f["text"] or ""))
        return len(jobs)

    def overview(company, text, about=""):
        about = about or (ingest.wikipedia_about(company, get=wiki_get) if wiki_get and company else "")
        return {"summary": ingest.summarize(text) if text else "", "company_about": about}

    def detail(jid):
        j = to_api(job_or_404(jid))
        j["contacts"] = [to_api(c) for c in db.list_contacts(con, jid)]
        j["events"] = [to_api(e) for e in db.list_events(con, jid)]
        j["letters"] = [{"id": lt["id"], "language": lt["language"], "updatedAt": lt["updated_at"]} for lt in db.list_letters(con, jid)]
        j["mails"] = [mail_api(m) for m in db.list_mails(con, job_id=jid)]
        raw = db.get_job(con, jid)
        j["projects"] = github.for_job(projects(), " ".join([raw.get("role") or "", raw.get("posting_text") or ""]))
        return j

    def mail_api(m):
        d = to_api(m)
        addr = setting("mail_address")
        msgid = m["msgid"].strip("<>")
        d["gmail"] = f"https://mail.google.com/mail/u/{addr or 0}/#search/rfc822msgid%3A{msgid}" if "@" in msgid else ""
        return d

    def owners_notify(title, body, url="/", tag=None, kind=None):
        pusher.notify(title, body, url=url, role="owner", tag=tag, kind=kind)

    def helpers_notify(title, body, url="/", tag=None, skip=()):
        # The people who help hear about the steps that matter: applied, an interview, an answer.
        pusher.notify(title, body, url=url, role="helper", tag=tag, kind="status", skip=skip)

    def job_title(j):
        return f"{j.get('role') or 'A job'} at {j.get('company') or 'a company'}"

    # Accounts

    def secure(request):
        return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

    def sign_in(request, response, uid):
        response.set_cookie(COOKIE, db.new_session(con, uid), max_age=db.SESSION_DAYS * 86400, httponly=True,
                            samesite="lax", secure=secure(request), path="/")

    def caller(request):
        """Who is asking. Behind Tailscale Funnel or another proxy on this computer every request arrives from the
        computer itself, and the proxy names the real sender in a header."""
        ip = request.client.host if request.client else "?"
        sent_for = request.headers.get("x-forwarded-for", "")
        return sent_for.split(",")[0].strip() if ip in ("127.0.0.1", "::1") and sent_for else ip

    @app.middleware("http")
    async def harden(request: Request, call_next):
        # The app can be on the open internet: no other site may frame it or load things into it, and no search
        # engine should list it.
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if secure(request):
            response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
        return response

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path, method = request.url.path, request.method
        if not path.startswith("/api/") or method == "OPTIONS":
            return await call_next(request)
        if method not in ("GET", "HEAD") and not path.startswith("/api/share"):
            # A page on another site must not be able to act with your cookie.
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                return JSONResponse({"detail": "This request came from another site."}, status_code=403)
        request.state.user = db.session_user(con, request.cookies.get(COOKIE))
        if _match(PUBLIC, method, path):
            return await call_next(request)
        user = request.state.user
        if not user:
            return JSONResponse({"detail": "Please sign in."}, status_code=401)
        if user["role"] != "owner" and not _match(HELPER, method, path):
            return JSONResponse({"detail": "Only the account owner can do this."}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/auth/state")
    def auth_state(request: Request):
        u = request.state.user
        return {"needsSetup": db.count_users(con) == 0, "user": user_api(u) if u else None}

    @app.post("/api/auth/setup")
    def setup(request: Request, response: Response, payload: dict = Body(...)):
        if db.count_users(con):
            raise HTTPException(409, f"{NAME} is already set up. Sign in instead.")
        name, pw = str(payload.get("name", "")).strip(), str(payload.get("password", ""))
        if not name:
            raise HTTPException(422, "Enter your name.")
        if len(pw) < 8:
            raise HTTPException(422, "Use a password of at least 8 characters.")
        uid = db.add_user(con, name, "owner", pw)
        if not setting("first_name"):
            db.set_setting(con, "first_name", name.split()[0])
        sign_in(request, response, uid)
        return {"user": user_api(db.get_user(con, uid))}

    @app.post("/api/auth/login")
    def login(request: Request, response: Response, payload: dict = Body(...)):
        ip = caller(request)
        recent = [t for t in failed_logins.get(ip, []) if t > time.time() - 600]
        if len(recent) >= 10:
            raise HTTPException(429, "Too many tries. Wait ten minutes.")
        u = db.user_by_name(con, str(payload.get("name", "")))
        if not u or not db.check_password(str(payload.get("password", "")), u["password"]):
            failed_logins[ip] = [*recent, time.time()]
            raise HTTPException(401, "That name and password do not match.")
        sign_in(request, response, u["id"])
        return {"user": user_api(u)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        db.end_session(con, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/invite/{token}")
    def invite_info(token: str):
        inv = db.get_invite(con, token)
        if not inv:
            raise HTTPException(404, "This link has expired. Ask for a new one.")
        owner = next((u for u in db.list_users(con) if u["role"] == "owner"), None)
        return {"name": inv["name"], "role": inv["role"], "existing": bool(inv["user_id"]), "for": owner["name"] if owner else ""}

    @app.post("/api/auth/join")
    def join(request: Request, response: Response, payload: dict = Body(...)):
        inv = db.get_invite(con, str(payload.get("token", "")))
        if not inv:
            raise HTTPException(404, "This link has expired. Ask for a new one.")
        if inv["user_id"]:
            uid = inv["user_id"]
        else:
            name = str(payload.get("name") or inv["name"]).strip()
            if not name:
                raise HTTPException(422, "Enter your name.")
            if db.user_by_name(con, name):
                raise HTTPException(409, "Someone already uses this name. Add a letter, for example Mama B.")
            uid = db.add_user(con, name, inv["role"])
        db.use_invite(con, payload.get("token"))
        sign_in(request, response, uid)
        return {"user": user_api(db.get_user(con, uid))}

    @app.get("/api/me")
    def me(request: Request):
        u = request.state.user
        return {**user_api(u), "push": db.has_push(con, u["id"]), "pushOff": sorted(pusher.off(u["id"])),
                "shareUrl": f"{public_url()}/api/share?key={u['share_key']}" if public_url() else f"/api/share?key={u['share_key']}"}

    @app.put("/api/me")
    def edit_me(request: Request, payload: dict = Body(...)):
        u = request.state.user
        name, pw = str(payload.get("name") or "").strip(), str(payload.get("password") or "")
        if name and name.lower() != u["name"].lower() and db.user_by_name(con, name):
            raise HTTPException(409, "Someone already uses this name.")
        if pw and len(pw) < 8:
            raise HTTPException(422, "Use a password of at least 8 characters.")
        if isinstance(payload.get("pushOff"), list):
            db.set_setting(con, f"push_off_{u['id']}", json.dumps(sorted({str(k) for k in payload["pushOff"] if k in PUSH_KINDS})))
        return user_api(db.update_user(con, u["id"], name=name or None, password=pw or None))

    @app.get("/api/people")
    def people():
        return [user_api(u) for u in db.list_users(con)]

    @app.post("/api/people/invite")
    def invite(payload: dict = Body(...)):
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(422, "Enter their name.")
        if db.user_by_name(con, name):
            raise HTTPException(409, f"{name} already has an account. Send them a sign in link instead.")
        role = payload.get("role") if payload.get("role") in db.ROLES else "helper"
        return {"token": db.new_invite(con, name, role), "days": db.INVITE_DAYS}

    @app.post("/api/people/{uid}/link")
    def sign_in_link(uid: int):
        u = db.get_user(con, uid)
        if not u:
            raise HTTPException(404, "Person not found.")
        return {"token": db.new_invite(con, u["name"], u["role"], user_id=uid), "days": db.INVITE_DAYS}

    @app.delete("/api/people/{uid}")
    def remove_person(request: Request, uid: int):
        if uid == request.state.user["id"]:
            raise HTTPException(422, "You cannot remove your own account.")
        db.delete_user(con, uid)
        return {"deleted": uid}

    # Notifications

    @app.post("/api/push/subscribe")
    def push_subscribe(request: Request, payload: dict = Body(...)):
        keys = payload.get("keys") or {}
        if not (payload.get("endpoint") and keys.get("p256dh") and keys.get("auth")):
            raise HTTPException(422, "The browser sent an incomplete subscription.")
        db.save_push(con, request.state.user["id"], payload["endpoint"], keys["p256dh"], keys["auth"])
        return {"ok": True}

    @app.delete("/api/push/subscribe")
    def push_unsubscribe(payload: dict = Body(default={})):
        if payload.get("endpoint"):
            db.drop_push(con, payload["endpoint"])
        return {"ok": True}

    @app.post("/api/push/test")
    def push_test(request: Request):
        n = pusher.notify("Notifications are on", f"This is how {NAME} tells you about replies and new jobs.",
                          user_ids=[request.state.user["id"]], tag="test")
        if not n:
            raise HTTPException(409, "Turn on notifications first.")
        return {"sent": n}

    # Status and settings

    @app.get("/api/status")
    def status(request: Request = None):
        u = getattr(request.state, "user", None) if request else None
        base = {"publicUrl": public_url(), "vapidKey": pusher.public_key, "firstName": setting("first_name"),
                "cv": None, "jobs": len(db.list_jobs(con))}
        cv = db.get_cv(con)
        if cv:
            base["cv"] = {"filename": cv["filename"], "uploadedAt": cv["uploaded_at"], "chars": len(cv["text"])}
        if u and u["role"] != "owner":
            return base
        m = model()
        key = setting("anthropic_key") or env.get("ANTHROPIC_API_KEY", "")
        cache_key = (m.provider, m.model, m.url, bool(key))
        if llm_seen.get("key") != cache_key or time.time() - llm_seen.get("at", 0) > 30:
            llm_seen.update(key=cache_key, at=time.time(), value=m.status())
        return {
            **base,
            "llm": {**llm_seen["value"], "model": m.model, "label": m.label, "url": m.url, "provider": m.provider,
                    "claudeKey": "set" if key else "", "claudeModel": setting("claude_model") or llm.CLAUDE_MODEL,
                    "ollamaModel": setting("llm_model") or env.get("OLLAMA_MODEL", letters.DEFAULT_MODEL),
                    "ollamaUrl": setting("llm_url") or env.get("OLLAMA_URL", letters.DEFAULT_URL)},
            "home": setting("home"),
            "unseenMail": db.unseen_mails(con),
            "languages": ", ".join(spoken()),
            "lookingFor": setting("looking_for", LOOKING_FOR),
            "profile": {**profile(), "degrees": [brief.degree_label(d) + ("" if d["done"] else " (in progress)") for d in brief.degrees(cv_text())]},
            "finds": {"new": len(finds.new()), "at": setting("finds_at")},
            "review": _json(setting("cv_review"), None),
            "mail": {"address": setting("mail_address"), "ready": bool(setting("mail_address") and setting("mail_password")),
                     "lastCheck": setting("mail_last_check"), "last": _json(setting("mail_last_result", "{}"), {})},
            "helperPage": HELPER_PAGE,
            "github": github_api(),
        }

    def github_api():
        return {"user": setting("github"), "at": setting("github_at"),
                "projects": [{k: p.get(k) for k in ("name", "url", "description", "language", "skills", "updated")} for p in projects()]}

    def load_github(user):
        try:
            found = github.fetch(user, get=github_get)
        except ValueError as e:
            raise HTTPException(502, str(e)) from None
        db.set_setting(con, "github", user)
        db.set_setting(con, "github_projects", json.dumps(found))
        db.set_setting(con, "github_at", db.now())
        return {**github_api(), "rescored": rescore_all()}

    @app.put("/api/github")
    def set_github(payload: dict = Body(...)):
        raw = str(payload.get("user") or "").strip()
        if not raw:
            for k in ("github", "github_projects", "github_at"):
                db.set_setting(con, k, "")
            return {**github_api(), "rescored": rescore_all()}
        user = github.username(raw)
        if not user:
            raise HTTPException(422, "Enter your GitHub name or the link to your profile.")
        return load_github(user)

    @app.post("/api/github/refresh")
    def refresh_github():
        if not setting("github"):
            raise HTTPException(400, "Add your GitHub name first.")
        return load_github(setting("github"))

    # Portfolio: your skills across the CV, GitHub and LinkedIn, and what each of them still lacks.

    def linkedin_api():
        text = setting("linkedin_text")
        review = portfolio.linkedin_review(text, link=setting("linkedin"), cv=cv_text(), projects=projects(), profile=profile(),
                                           spoken=spoken()) if text else None
        return {"link": setting("linkedin"), "at": setting("linkedin_at"), "has": bool(text), "review": review}

    @app.get("/api/portfolio")
    def get_portfolio():
        open_jobs = [j for j in db.list_jobs(con) if j["status"] not in ("Rejected", "Withdrawn")]
        postings = [f"{j.get('role') or ''} {j.get('posting_text') or ''}" for j in open_jobs if j.get("posting_text")]
        postings += [f"{f['title']} {f['text']}" for f in finds.new() if f["text"]]
        rows = portfolio.skill_map(cv_text(), projects(), setting("linkedin_text"), postings)
        return {"skills": rows, "groups": [*SKILL_GROUPS, "Other"], "postings": len(postings), "fields": portfolio.fields(rows),
                "hasCv": bool(cv_text()),
                "github": {"user": setting("github"), "at": setting("github_at"), "repos": [portfolio.repo_review(p) for p in projects()]},
                "linkedin": linkedin_api()}

    @app.post("/api/portfolio/refresh")
    def refresh_portfolio():
        """Read GitHub again and run every check again. LinkedIn turns automatic readers away, so its text is only as
        new as your last paste or PDF; the date of that comes back with the rest."""
        if setting("github"):
            load_github(setting("github"))
        return get_portfolio()

    def save_linkedin(text):
        db.set_setting(con, "linkedin_text", text[:40000])
        db.set_setting(con, "linkedin_at", db.now() if text else "")

    @app.put("/api/linkedin")
    def set_linkedin(payload: dict = Body(...)):
        """The profile as text you pasted. The app never signs in to LinkedIn or reads it by itself."""
        if "link" in payload:
            link = str(payload["link"] or "").strip()
            if link and not re.search(r"linkedin\.com/in/[^/\s]+", link):
                raise HTTPException(422, "Enter the link to your profile, like linkedin.com/in/yourname.")
            db.set_setting(con, "linkedin", link)
        if "text" in payload:
            save_linkedin(str(payload["text"] or "").strip())
        return linkedin_api()

    @app.post("/api/linkedin/file")
    async def upload_linkedin(file: UploadFile = File(...)):
        # LinkedIn makes a PDF of a profile under More, Save to PDF.
        try:
            text = cvparse.extract_text(file.filename, await file.read())
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if len(text) < 20:
            raise HTTPException(400, "The file has almost no readable text.")
        save_linkedin(text)
        return linkedin_api()

    @app.put("/api/settings")
    def settings(request: Request, payload: dict = Body(...)):
        for k in ("llm_model", "llm_url", "mail_address", "mail_host", "first_name", "claude_model"):
            if payload.get(k):
                db.set_setting(con, k, str(payload[k]).strip())
        if "llm_provider" in payload and payload["llm_provider"] in ("", "claude", "ollama"):
            db.set_setting(con, "llm_provider", payload["llm_provider"])
        if "anthropic_key" in payload:
            db.set_setting(con, "anthropic_key", str(payload["anthropic_key"] or "").strip())
        if "looking_for" in payload:
            db.set_setting(con, "looking_for", str(payload["looking_for"] or "").strip())
        if payload.get("mail_password"):
            db.set_setting(con, "mail_password", re.sub(r"\s+", "", str(payload["mail_password"])))  # Google shows it in groups of four
        changed = False
        if isinstance(payload.get("profile"), dict):
            new = json.dumps(clean_profile(payload["profile"]))
            changed = new != setting("profile")
            db.set_setting(con, "profile", new)
        for k in ("home", "languages"):
            if k in payload and str(payload[k] or "").strip() != setting(k):
                db.set_setting(con, k, str(payload[k] or "").strip())
                changed = True
        if changed:
            rescore_all()
        return status(request)

    # CV

    def run_review(deep=False):
        cv = db.get_cv(con)
        if not cv:
            raise HTTPException(400, "Upload your CV first.")
        try:
            r = cvreview.review(cv["text"], llm=model() if deep else None, looking_for=setting("looking_for", LOOKING_FOR))
        except llm.LLMError as e:
            raise HTTPException(503, str(e)) from None
        r["cvId"], r["at"] = cv["id"], db.now()
        db.set_setting(con, "cv_review", json.dumps(r))
        return r

    @app.post("/api/cv")
    async def upload_cv(file: UploadFile = File(...)):
        data = await file.read()
        try:
            text = cvparse.extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if len(text) < 20:
            raise HTTPException(400, "The CV has almost no readable text. If it is a scanned PDF, upload a DOCX or TXT version.")
        db.set_cv(con, file.filename, text, data)
        return {"filename": file.filename, "chars": len(text), "rescored": rescore_all(), "review": run_review()}

    @app.post("/api/cv/review")
    def review_cv(payload: dict = Body(default={})):
        return run_review(deep=payload.get("deep", True))

    # Where the jobs are, and how long it takes to get there

    def point(place):
        p = places.locate(place)
        return {"lat": p[0], "lon": p[1]} if p else None

    def remote(j):
        return j.get("work_setup") == "Remote"

    @app.get("/api/map")
    def job_map():
        home = places.locate(setting("home"))
        out = []
        for j in db.list_jobs(con):
            spot = None if remote(j) else places.locate(j.get("location") or "", near=places.locate(setting("home")))
            if not spot:
                continue
            car = roads.route(home, spot, "car") if home else None
            out.append({"id": j["id"], "company": j["company"], "role": j["role"], "score": j["score"], "fit": j["fit"],
                        "status": j["status"], "lat": spot[0], "lon": spot[1], "minutes": car and car["minutes"]})
        return {"home": {"lat": home[0], "lon": home[1]} if home else None, "jobs": out}

    @app.get("/api/jobs/{jid}/travel")
    def travel(jid: str):
        j = job_or_404(jid)
        home, spot = places.locate(setting("home")), None if remote(j) else places.locate(j.get("location") or "", near=places.locate(setting("home")))
        modes = {m: roads.route(home, spot, m) for m in geo.MODES} if home and spot else {}
        return {"home": point(setting("home")), "place": {"lat": spot[0], "lon": spot[1]} if spot else None,
                "placeName": j.get("location") or "", "homeName": setting("home"), "remote": remote(j),
                "modes": {m: r for m, r in modes.items() if r}}

    # Jobs

    @app.get("/api/jobs")
    def jobs():
        return [to_api(j) for j in db.list_jobs(con)]

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str):
        return detail(jid)

    @app.post("/api/jobs")
    def create_job(payload: dict = Body(...)):
        job = from_api(payload)
        if not str(job.get("company", "")).strip():
            raise HTTPException(422, "Enter the company name.")
        if job.get("status") not in STATUSES:
            job["status"] = "To apply"
        return to_api(save_scored(job) if job.get("score") in (None, "") else db.get_job(con, db.upsert_job(con, job)))

    def apply_text(job, text, fields=None):
        """Read a pasted job description into an existing job: summary, fit, salary, everything updates."""
        fields = {k: str((fields or {}).get(k) or "").strip() or job[k] for k in ("company", "role", "location")}
        updated = {**job, **fields, "posting_text": text[:20000], "pros": "", "cons": ""}
        updated.update(overview(fields["company"], text, ingest.about_section(text, fields["company"]) or job["company_about"]))
        s = scored(updated)
        updated.update({k: v for k, v in s.items() if v is not None or k == "distance_km"})
        return db.update_job(con, job["id"], updated)

    def add_from_link(url, text="", company="", role="", location="", added_by="you", note="", day="", posting=False, by_user=None):
        """Save a job from a link. Never fails on a page that cannot be read: the job is saved with what the
        shared text says, and the posting text can be pasted later. Returns (job, outcome) where outcome is
        "added", "exists" or "improved" (it was there, and this time we learnt more about it)."""
        link = ingest.canonical_link(url)
        shared = ingest.parse_shared(text, url) if url else ingest.guess_from_text(text)
        company, role, location = company or shared["company"], role or shared["role"], location or shared["location"]
        is_posting = len(text) > 300 or (posting and len(text) > 80)  # a pasted job description, not a one line share
        existing = db.find_job(con, "", "", link) or (company and role and db.find_job(con, company, role))
        if existing:
            job = db.get_job(con, existing)
            outcome = "exists"
            if is_posting and not job["posting_text"]:
                job, outcome = apply_text(job, text, {"company": company, "role": role, "location": location}), "improved"
            elif not job["posting_text"]:
                try:  # the page may be readable now
                    p = ingest.read_posting(link, fetch=fetch) if link else None
                    if p and p.get("text"):
                        job, outcome = apply_text(job, p["text"], p), "improved"
                except Exception:
                    pass
            if note:
                db.add_event(con, job["id"], {"kind": "Note", "text": f"{added_by}: {note}" if added_by != "you" else note, "date": day})
            return job, outcome
        p = None
        if is_posting:
            p = {"company": company, "role": role, "location": location, "text": text, "about": ingest.about_section(text, company)}
        elif link:
            try:
                p = ingest.read_posting(link, fetch=fetch)
                p = {**p, "company": p["company"] or company, "role": p["role"] or role, "location": p["location"] or location}
            except Exception:
                p = None
        if not p or not p.get("text"):
            p = {"company": company, "role": role, "location": location, "text": "", "about": ""}
        job = save_scored({
            "company": p["company"], "role": p["role"], "location": p["location"], "link": link, "posting_text": p["text"],
            "source": ingest.detect_source(link) if link else "Pasted text", "status": "To apply", "added_by": added_by or "you",
            "sent_by_user": by_user, **overview(p["company"], p["text"], p["about"]),
        })
        if note:
            db.add_event(con, job["id"], {"kind": "Note", "text": f"{added_by}: {note}" if added_by != "you" else note, "date": day})
        return job, "added"

    def link_context(text, url):
        # The words next to a link in a list, for example the line Claude or a friend wrote above it.
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if url in ln:
                rest = _clean_line(ln.replace(url, " "))
                if len(rest) < 8 and i:
                    rest = _clean_line(lines[i - 1])
                return " ".join(rest.split())
        return ""

    def add_any(text, user, note=""):
        """Anything someone pastes or shares: one link, a list of links (for example an answer from Claude), or a job description."""
        text = str(text or "").strip()
        by = user["name"] if user and user["role"] != "owner" else "you"
        by_user = user["id"] if user and user["role"] != "owner" else None
        links = ingest.find_links(text)
        jobs_links = [u for u in links if ingest.looks_like_job(u)] or links
        out = []
        if len(jobs_links) > 1:
            for u in jobs_links[:20]:
                job, outcome = add_from_link(u, text=link_context(text, u), added_by=by, note=note, by_user=by_user)
                out.append((job, outcome))
        elif jobs_links:
            u = jobs_links[0]
            rest = text.replace(u, " ").strip()
            job, outcome = add_from_link(u, text=rest, added_by=by, note=note, posting=len(rest) > 300, by_user=by_user)
            out.append((job, outcome))
        elif len(text) >= 200:
            out.append(add_from_link("", text=text, added_by=by, note=note, posting=True, by_user=by_user))
        else:
            raise HTTPException(422, "Paste the link to the job, or the whole job description.")
        new = [j for j, o in out if o == "added"]
        if new and by != "you":
            j = new[0]
            more = f" and {len(new) - 1} more" if len(new) > 1 else ""
            fit = f" · fit {j['score']}" if j.get("score") is not None else ""
            owners_notify(f"{by} sent you a job", f"{job_title(j)}{more}{fit}", url=f"/#/job/{j['id']}", tag=f"job-{j['id']}", kind="job")
        return out

    @app.post("/api/jobs/add")
    def add(request: Request, payload: dict = Body(...)):
        out = add_any(payload.get("text", ""), request.state.user, str(payload.get("note") or "").strip())
        return {"results": [{"job": to_api(j), "outcome": o} for j, o in out]}

    @app.post("/api/share")
    async def share(request: Request, key: str = ""):
        # For the iPhone share sheet (a Shortcut) and other apps: a personal key instead of a sign in.
        raw = (await request.body()).decode("utf-8", "replace")
        text = raw
        if "json" in request.headers.get("content-type", ""):
            data = _json(raw, {})
            text = str(data.get("text") or data.get("url") or "") if isinstance(data, dict) else ""
            key = key or (str(data.get("key") or "") if isinstance(data, dict) else "")
        user = db.user_by_share_key(con, key or request.headers.get("x-shortlist-key", ""))
        if not user:
            return PlainTextResponse(f"This share link is not valid any more. Open {NAME} and set up sharing again.", status_code=401)
        try:
            out = add_any(text, user)
        except HTTPException as e:
            return PlainTextResponse(e.detail, status_code=e.status_code)
        words = {"added": "Added", "exists": "Already saved", "improved": "Updated"}
        lines = [f"{words[o]}: {job_title(j)}" + (f" (fit {j['score']})" if j.get("score") is not None else "") for j, o in out]
        return PlainTextResponse("\n".join(lines))

    @app.post("/api/jobs/import-link")
    def import_link(request: Request, payload: dict = Body(...)):
        get = lambda k: str(payload.get(k, "")).strip()
        url = (ingest.find_links(get("url")) or [""])[0]  # also accepts "Check out this job ... https://..."
        if not url:
            raise HTTPException(422, "Paste the full link, starting with https://")
        shared = get("url").replace(url, " ").strip()
        u = request.state.user
        by = get("addedBy") or (u["name"] if u and u["role"] != "owner" else "you")
        job, _ = add_from_link(url, text=get("text") or shared, company=get("company"), role=get("role"), location=get("location"),
                               added_by=by, note=get("note"), posting=bool(get("text")))
        return to_api(job)

    @app.post("/api/jobs/{jid}/text")
    def add_text(jid: str, payload: dict = Body(...)):
        # For pages that cannot be read, such as Indeed: paste the job description by hand.
        job = job_or_404(jid)
        text = str(payload.get("text", "")).strip()
        if len(text) < 80:
            raise HTTPException(422, "Paste the whole job description.")
        if not (str(payload.get("company") or "").strip() or job["company"]):
            raise HTTPException(422, "Enter the company name.")
        return to_api(apply_text(job, text, payload))

    @app.post("/api/jobs/{jid}/notes")
    def add_note(request: Request, jid: str, payload: dict = Body(...)):
        job = job_or_404(jid)
        text, u = str(payload.get("text", "")).strip(), request.state.user
        if not text:
            raise HTTPException(422, "Write a note first.")
        who = u["name"] if u["role"] != "owner" else ""
        eid = db.add_event(con, jid, {"kind": "Note", "text": f"{who}: {text}" if who else text})
        if who:
            owners_notify(f"{who} wrote about {job['company'] or 'a job'}", text[:140], url=f"/#/job/{jid}", tag=f"note-{jid}")
        return {"id": eid}

    @app.patch("/api/jobs/{jid}")
    def patch_job(jid: str, payload: dict = Body(...)):
        job = job_or_404(jid)
        fields = from_api(payload)
        new_status = fields.get("status")
        if new_status and new_status not in STATUSES:
            raise HTTPException(422, "Unknown status.")
        if new_status == "Applied":
            fields["cv_sent"] = 1
            fields["applied_on"] = fields.get("applied_on") or job["applied_on"] or date.today().isoformat()
            default_follow_up = (date.fromisoformat(fields["applied_on"]) + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
            fields["follow_up"] = fields.get("follow_up") or job["follow_up"] or default_follow_up
        updated = db.update_job(con, jid, fields)
        if any(k in fields and fields[k] != job[k] for k in ("location", "work_setup", "role", "company")):
            updated = rescore_one(updated)  # a new place or setup changes distance and fit
        if new_status and new_status != job["status"]:
            kind = "Applied" if new_status == "Applied" else "Status"
            db.add_event(con, jid, {"kind": kind, "text": "CV sent" if kind == "Applied" else f"Status changed to {new_status}",
                                    **({"date": fields["applied_on"]} if kind == "Applied" else {})})
            if new_status in ("Applied", "Interview", "Accepted", "Rejected"):
                me = setting("first_name") or "They"
                verb = {"Applied": "applied to", "Interview": "has an interview for", "Accepted": "got", "Rejected": "got a no for"}[new_status]
                sender = job.get("sent_by_user")
                if sender:
                    pusher.notify(f"{me} {verb} the job you sent", job_title(job), url=f"/#/job/{jid}", user_ids=[sender],
                                  tag=f"job-{jid}", kind="status")
                helpers_notify(f"{me} {verb} {job['company'] or 'a job'}", job_title(job), url=f"/#/job/{jid}", tag=f"job-{jid}",
                               skip=[sender] if sender else ())
        return to_api(updated)

    @app.delete("/api/jobs/{jid}")
    def delete_job(jid: str):
        job_or_404(jid)
        db.delete_job(con, jid)
        return {"deleted": jid}

    @app.post("/api/jobs/{jid}/rescore")
    def rescore(jid: str):
        job = job_or_404(jid)
        return to_api(db.update_job(con, jid, scored({**job, "pros": "", "cons": ""})))

    # Finding jobs: search for what the profile asks for, look at each one, save or skip

    find_lock = threading.Lock()

    def find_api(f):
        d = {k: f[k] for k in ("id", "title", "company", "location", "link", "source", "posted", "score", "fit")}
        facts = _json(f["facts"], None)
        d.update(read=bool(f["read"]), facts=facts, reasons=_json(f["reasons"], []), workSetup=f["work_setup"] or "",
                 distanceKm=f["distance_km"], **{k: (facts or {}).get(k) or "" for k in ("type", "hours", "salary")})
        return d

    def finds_api(**extra):
        p = profile()
        return {"items": [find_api(f) for f in finds.new()], "at": setting("finds_at"), "ready": bool(p["roles"]),
                "roles": p["roles"], "where": p["where"], "sources": _json(setting("finds_sources"), {}), **extra}

    def score_find(f, text=""):
        s = scored({"company": f["company"], "role": f["title"], "location": f["location"], "posting_text": text})
        # What the filter on Find needs comes from the text too: the kind of job, the hours and the pay.
        facts = {**json.loads(s["facts"]), "type": (s.get("type") or "") if text else "", "hours": hours_text(text), "salary": s.get("salary") or ""}
        return {"score": s["score"], "fit": s["fit"], "facts": json.dumps(facts), "reasons": s["reasons"],
                "work_setup": s.get("work_setup") or "", "distance_km": s.get("distance_km")}

    def find_or_404(fid):
        f = finds.get(fid)
        if not f:
            raise HTTPException(404, "This job is no longer in the list.")
        return f

    @app.get("/api/finds")
    def list_finds():
        return finds_api()

    @app.post("/api/finds/search")
    def search_finds():
        p = profile()
        if not p["roles"]:
            raise HTTPException(422, "Say which jobs you want first, under You.")
        if not find_lock.acquire(blocking=False):
            raise HTTPException(409, "A search is already running.")
        try:
            try:
                added, found = run_search(p)
            except RuntimeError as e:
                raise HTTPException(503, str(e)) from None
            return finds_api(added=len(added), found=found)
        finally:
            find_lock.release()

    def run_search(p):
        """Ask the job sites and keep what is new. Returns the ids that were added and how many listings came back."""
        report = {}
        found = discover.search(p, fetch=fetch, post=post, report=report)
        added, seen = [], finds.seen()
        no_senior = bool(p["levels"]) and "senior" not in p["levels"]
        for f in found:
            if no_senior and rule_extract("", f["title"])["seniority"] == "senior":
                continue  # "Senior Data Analyst" when you asked for junior roles
            if (finds.known(f["id"]) or seen.has(f["company"], f["title"])
                    or db.find_job(con, f["company"], f["title"], ingest.canonical_link(f["link"]))):
                continue  # seen before, here or on another site, or already among your jobs
            seen.add(f["company"], f["title"])
            text = (f.get("text") or "")[:20000]
            ready = len(text) >= discover.READY_TEXT  # some sites hand over the whole posting with the result
            finds.add({**f, **score_find(f, text if ready else ""), "text": text if ready else "", "read": int(ready)})
            added.append(f["id"])
        db.set_setting(con, "finds_at", db.now())
        db.set_setting(con, "finds_sources", json.dumps(report))
        return added, len(found)

    def auto_find(every_hours=12, read=6, pause=1.0):
        """Search without being asked, twice a day while the app runs, and tell the owner's phone when something fits.
        Returns the new finds that fit, or None when it was not time yet."""
        p = profile()
        last = setting("finds_at")
        if not p["roles"] or (last and datetime.fromisoformat(last) > datetime.fromisoformat(db.now()) - timedelta(hours=every_hours)):
            return None
        if not find_lock.acquire(blocking=False):
            return None
        try:
            added, _ = run_search(p)
            fresh = [f for f in finds.new() if f["id"] in added]
            for f in [f for f in fresh if not f["read"]][:read]:  # a title is a guess; the best few get their real score first
                try:
                    text = discover.read(f, fetch=fetch)
                    if text:
                        finds.update(f["id"], {**score_find(f, text), "text": text[:20000], "read": 1})
                except Exception:
                    pass
                time.sleep(pause)
            good = [f for f in finds.new() if f["id"] in added and f["read"] and f["fit"] in ("Top pick", "Good")]
            if good:
                names = ", ".join(f"{f['title']}{' at ' + f['company'] if f['company'] else ''} ({f['score']})" for f in good[:3])
                owners_notify(f"{len(good)} new job{'s' if len(good) > 1 else ''} that fit{'' if len(good) > 1 else 's'} you", names[:180],
                              url="/#/find", tag="finds", kind="find")
            return good
        finally:
            find_lock.release()

    app.state.find = auto_find

    @app.post("/api/finds/{fid}/read")
    def read_find(fid: str):
        # Open the posting itself, so the score, the years asked and the degree come from the full text.
        f = find_or_404(fid)
        if not f["read"]:
            try:
                text = discover.read(f, fetch=fetch)
            except Exception:
                raise HTTPException(502, "The posting could not be read right now.") from None
            if not text:
                raise HTTPException(502, "The posting could not be read right now.")
            f = finds.update(fid, {**score_find(f, text), "text": text[:20000], "read": 1})
        return find_api(f)

    @app.post("/api/finds/{fid}/save")
    def save_find(fid: str):
        f = find_or_404(fid)
        job, _ = add_from_link(f["link"], text=f["text"] or "", company=f["company"], role=f["title"], location=f["location"],
                               posting=bool(f["text"]))
        db.update_job(con, job["id"], {"source": f["source"] or job["source"]})
        finds.update(fid, {"state": "saved"})
        return to_api(db.get_job(con, job["id"]))

    @app.post("/api/finds/{fid}/skip")
    def skip_find(fid: str, payload: dict = Body(default={})):
        find_or_404(fid)
        finds.update(fid, {"state": "new" if payload.get("undo") else "skipped"})
        return {"id": fid}

    # Mail: jobs people send you, and what happened with your applications

    mail_lock = threading.Lock()

    def apply_evidence(j, e):
        today = date.today().isoformat()
        d = e["date"] or today
        cur = db.get_job(con, j["id"])
        fields = {}
        if e["kind"] in ("sent", "confirmation"):
            if not cur["cv_sent"]:
                fields.update(cv_sent=1, applied_on=cur["applied_on"] or d)
                fields["follow_up"] = cur["follow_up"] or (date.fromisoformat(fields["applied_on"]) + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
                if cur["status"] == "To apply":
                    fields["status"] = "Applied"
            kind, text = ("Email sent", f"From your mail: {e['subject']}") if e["kind"] == "sent" else ("Applied", f"Confirmation: {e['subject']}")
        else:
            fields["replied_on"] = cur["replied_on"] or d
            kind = {"rejection": "Rejection", "interview": "Interview"}.get(e["kind"], "Reply")
            text = f"From {e.get('from', '')}: {e['subject']}"
            if e["kind"] == "rejection" and cur["status"] in OPEN and e.get("about_application"):
                fields["status"] = "Rejected"
            elif e["kind"] == "interview" and cur["status"] in ("To apply", "Applied", "Waiting"):
                fields["status"] = "Interview"
            title = {"rejection": f"{cur['company']} answered", "interview": f"Interview invitation from {cur['company']}"}.get(
                e["kind"], f"{cur['company']} replied")
            owners_notify(title, e["subject"][:140], url=f"/#/job/{j['id']}", tag=f"mail-{j['id']}", kind="reply")
            if e["kind"] == "interview":
                helpers_notify(f"{setting('first_name') or 'They'} got an interview invitation", job_title(cur), url=f"/#/job/{j['id']}",
                               tag=f"job-{j['id']}")
        if fields:
            db.update_job(con, j["id"], fields)
        db.add_event(con, j["id"], {"kind": kind, "text": text, "date": d})
        db.add_mail(con, j["id"], e)
        return e["kind"]

    def check_mail():
        addr, pw = setting("mail_address"), setting("mail_password")
        if not (addr and pw):
            return {"ok": False, "message": "Add your Gmail address and app password in Settings."}
        if not mail_lock.acquire(blocking=False):
            return {"ok": False, "message": "Already checking your mail."}
        result = {"ok": True, "added": 0, "applied": 0, "replies": 0, "message": ""}
        try:
            with mail.Mailbox(addr, pw, host=setting("mail_host", "imap.gmail.com"), factory=imap_factory) as box:
                msgs = box.new_in_inbox(int(setting("mail_last_uid", "0") or 0))
                for item in mail.shared_jobs(msgs, addr):
                    job, outcome = add_from_link(item["link"], text=item["title"], added_by=item["by"], note=item["note"], day=item["date"])
                    if outcome == "added":
                        result["added"] += 1
                        owners_notify(f"{item['by']} sent you a job", job_title(job), url=f"/#/job/{job['id']}", tag=f"job-{job['id']}", kind="job")
                if msgs:
                    db.set_setting(con, "mail_last_uid", str(max(int(m.uid) for m in msgs)))
                for j in db.list_jobs(con):
                    if j["status"] not in OPEN or not j["company"].strip():
                        continue
                    for e in mail.evidence(box.find(j["company"], sent=True), box.find(j["company"], sent=False), addr):
                        if db.mail_seen(con, e["msgid"], j["id"]):
                            continue
                        kind = apply_evidence(j, e)
                        db.mark_mail_seen(con, e["msgid"], j["id"])
                        result["applied" if kind in ("sent", "confirmation") else "replies"] += 1
        except imaplib.IMAP4.error:
            result = {"ok": False, "message": "Gmail refused the login. Check the address and the app password (not your normal password)."}
        except OSError:
            result = {"ok": False, "message": "Could not reach the mail server. Are you online?"}
        finally:
            mail_lock.release()
        db.set_setting(con, "mail_last_check", db.now())
        db.set_setting(con, "mail_last_result", json.dumps(result))
        return result

    def daily_nudges(today=None):
        # Once a day: follow ups that are due and deadlines that are close, as one notification.
        today = today or date.today().isoformat()
        if setting("nudge_day") == today:
            return None
        soon = (date.fromisoformat(today) + timedelta(days=2)).isoformat()
        jobs = db.list_jobs(con)
        due = [j for j in jobs if j["status"] in ("Applied", "Waiting") and not j["replied_on"] and j["follow_up"] and j["follow_up"] <= today]
        close = [j for j in jobs if j["status"] == "To apply" and j["deadline"] and today <= j["deadline"] <= soon]
        db.set_setting(con, "nudge_day", today)
        parts = []
        tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        for e in calendar_entries(True):
            if e["kind"] == "interview" and e["date"] in (today, tomorrow):
                when = "today" if e["date"] == today else "tomorrow"
                parts.append(f"Interview at {e['company'] or 'a company'} {when}{' at ' + e['time'] if e['time'] else ''}")
        if due:
            parts.append(f"{len(due)} follow up{'s' if len(due) > 1 else ''} due ({', '.join(j['company'] for j in due[:3])})")
        if close:
            parts.append(f"{len(close)} deadline{'s' if len(close) > 1 else ''} in two days ({', '.join(j['company'] for j in close[:3])})")
        if parts:
            owners_notify("Today in your job search", ". ".join(parts) + ".", url="/#/calendar", tag="daily", kind="daily")
        return parts

    # The calendar: everything that happened or is planned, one entry per job, day and kind.

    EVENT_KIND = {"Applied": "applied", "Email sent": "sent", "Message sent": "sent", "Reply": "reply", "Call": "call",
                  "Interview": "interview", "Offer": "offer", "Rejection": "rejection"}
    MAIL_KIND = {"sent": "sent", "confirmation": "applied", "interview": "invite", "rejection": "rejection"}
    FROM_MAIL = ("From your mail:", "Confirmation:", "From ")

    def calendar_entries(full):
        """`full` adds what a mail said; a helper sees that something happened, not the words."""
        jobs, out, seen, mailed = db.list_jobs(con), [], set(), set()

        def add(day, kind, j, text="", time="", sender="", mail_id=None, event_id=None):
            day = str(day or "")[:10]
            if len(day) != 10 or (j["id"], day, kind) in seen:
                return
            seen.add((j["id"], day, kind))
            out.append({"date": day, "time": time, "kind": kind, "jobId": j["id"], "company": j["company"], "role": j["role"],
                        "text": text if full else "", "from": sender if full else "", "mailId": mail_id, "eventId": event_id})
        by_id = {j["id"]: j for j in jobs}
        for m in db.list_mails(con, limit=1000):
            if j := by_id.get(m["job_id"]):
                mailed.add((j["id"], str(m["date"])[:10]))
                add(m["date"], MAIL_KIND.get(m["kind"], "reply"), j, m["subject"], sender=m["sender_name"] or m["sender"], mail_id=m["id"])
        for j in jobs:
            for e in db.list_events(con, j["id"]):
                kind = EVENT_KIND.get(e["kind"])
                if not kind or ((j["id"], e["date"][:10]) in mailed and e["text"].startswith(FROM_MAIL)):
                    continue  # the mail itself is in the calendar already
                clock = re.match(r"\s*(\d{1,2})[:h.](\d{2})\b\s*[·,-]?\s*", e["text"] or "")
                add(e["date"], kind, j, e["text"][clock.end():] if clock else e["text"],
                    time=f"{int(clock[1]):02d}:{clock[2]}" if clock else "", event_id=e["id"])
            if j["applied_on"] and not any(k[0] == j["id"] and k[2] in ("applied", "sent") for k in seen):
                add(j["applied_on"], "applied", j)
            if j["status"] in ("Applied", "Waiting") and not j["replied_on"]:
                add(j["follow_up"], "followup", j)
            if j["status"] == "To apply":
                add(j["deadline"], "deadline", j)
        return sorted(out, key=lambda e: (e["date"], e["time"] or "99"))

    @app.get("/api/calendar")
    def calendar(request: Request):
        return {"today": date.today().isoformat(), "entries": calendar_entries(request.state.user["role"] == "owner")}

    @app.get("/api/letters")
    def all_letters():
        # Every letter written so far, newest first, with the job it is for.
        jobs = {j["id"]: j for j in db.list_jobs(con)}
        rows = [lt for j in jobs.values() for lt in db.list_letters(con, j["id"])]
        return [{"id": lt["id"], "jobId": lt["job_id"], "company": jobs[lt["job_id"]]["company"], "role": jobs[lt["job_id"]]["role"],
                 "language": lt["language"], "updatedAt": lt["updated_at"], "start": " ".join(lt["text"].split())[:160],
                 "words": len(lt["text"].split())} for lt in sorted(rows, key=lambda x: x["updated_at"], reverse=True)]

    app.state.check_mail = check_mail
    app.state.daily = daily_nudges
    app.state.pusher = pusher
    app.state.mail_ready = lambda: bool(setting("mail_address") and setting("mail_password"))

    @app.post("/api/mail/check")
    def mail_check():
        return check_mail()

    @app.get("/api/mails")
    def mails(all: bool = False):
        # Replies, interview invitations and rejections; with all=true also the mails you sent.
        return {"unseen": db.unseen_mails(con), "mails": [mail_api(m) for m in db.list_mails(con, received_only=not all)]}

    @app.post("/api/mails/seen")
    def mails_seen(payload: dict = Body(default={})):
        db.mark_mails_seen(con, job_id=payload.get("jobId"), ids=payload.get("ids"))
        return {"unseen": db.unseen_mails(con)}

    # People at the company

    @app.post("/api/jobs/{jid}/contacts")
    def add_contact(jid: str, payload: dict = Body(...)):
        job_or_404(jid)
        c = from_api(payload)
        if not str(c.get("name", "")).strip():
            raise HTTPException(422, "Enter the person's name.")
        return to_api(db.get_contact(con, db.add_contact(con, jid, c)))

    @app.patch("/api/contacts/{cid}")
    def edit_contact(cid: int, payload: dict = Body(...)):
        if not db.get_contact(con, cid):
            raise HTTPException(404, "Contact not found.")
        return to_api(db.update_contact(con, cid, from_api(payload)))

    @app.delete("/api/contacts/{cid}")
    def remove_contact(cid: int):
        db.delete_contact(con, cid)
        return {"deleted": cid}

    # Timeline

    @app.post("/api/jobs/{jid}/events")
    def add_event(jid: str, payload: dict = Body(...)):
        job = job_or_404(jid)
        kind = payload.get("kind")
        if kind not in db.EVENT_KINDS:
            raise HTTPException(422, "Choose what happened from the list.")
        d = str(payload.get("date") or date.today().isoformat())
        eid = db.add_event(con, jid, {"kind": kind, "text": payload.get("text", ""), "date": d})
        if kind == "Reply" and not job["replied_on"]:
            db.update_job(con, jid, {"replied_on": d})
        if kind == "Applied" and not job["cv_sent"]:
            db.update_job(con, jid, {"cv_sent": 1, "applied_on": job["applied_on"] or d})
        if kind in NUDGES and job["status"] in ("Applied", "Waiting") and not job["replied_on"]:
            # You followed up, so the next reminder moves a week after this message.
            try:
                nxt = (date.fromisoformat(d) + timedelta(days=NUDGE_DAYS)).isoformat()
            except ValueError:
                nxt = ""
            if nxt > (job["follow_up"] or ""):
                db.update_job(con, jid, {"follow_up": nxt})
        return {"id": eid}

    @app.delete("/api/events/{eid}")
    def remove_event(eid: int):
        db.delete_event(con, eid)
        return {"deleted": eid}

    # Letters

    @app.get("/api/jobs/{jid}/letters")
    def job_letters(jid: str):
        job_or_404(jid)
        return [to_api(lt) for lt in db.list_letters(con, jid)]

    @app.post("/api/jobs/{jid}/letters")
    def new_letter(jid: str, payload: dict = Body(...)):
        job = job_or_404(jid)
        cv = evidence()
        if not cv:
            raise HTTPException(400, "Add your CV first, so the letter can use your real experience.")
        lang = payload.get("language") or "English"
        m = model()
        msgs = letters.build_messages(cv, job, lang, payload.get("notes", ""))
        try:
            text = m.chat(msgs[0]["content"], msgs[1]["content"])
        except llm.LLMError as e:
            raise HTTPException(503, str(e)) from None
        return to_api(db.get_letter(con, db.add_letter(con, jid, lang, text, m.label)))

    @app.put("/api/letters/{lid}")
    def edit_letter(lid: int, payload: dict = Body(...)):
        if not db.get_letter(con, lid):
            raise HTTPException(404, "Letter not found.")
        return to_api(db.update_letter(con, lid, str(payload.get("text", ""))))

    @app.post("/api/letters/{lid}/revise")
    def revise_letter(lid: int, payload: dict = Body(...)):
        lt = db.get_letter(con, lid)
        if not lt:
            raise HTTPException(404, "Letter not found.")
        instruction = str(payload.get("instruction", "")).strip()
        if not instruction:
            raise HTTPException(422, "Say how the letter should change.")
        job = db.get_job(con, lt["job_id"]) or {}
        m = model()
        msgs = letters.revise_messages(str(payload.get("text") or lt["text"]), instruction, evidence(), job, lt["language"])
        try:
            new = m.chat(msgs[0]["content"], msgs[1]["content"])
        except llm.LLMError as e:
            raise HTTPException(503, str(e)) from None
        return to_api(db.get_letter(con, db.add_letter(con, lt["job_id"], lt["language"], new, m.label)))

    @app.get("/api/letters/{lid}/download")
    def download_letter(lid: int, format: str = "docx"):
        lt = db.get_letter(con, lid)
        if not lt:
            raise HTTPException(404, "Letter not found.")
        job = db.get_job(con, lt["job_id"]) or {}
        name = re.sub(r"[^A-Za-z0-9]+", "_", f"Motivation_letter_{job.get('company', '')}").strip("_")
        if format == "txt":
            return Response(lt["text"], media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.txt"'})
        return Response(letters.to_docx(lt["text"]), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})

    # Import and export

    @app.post("/api/import/json")
    async def import_json(file: UploadFile = File(...)):
        try:
            data = json.loads(await file.read())
        except ValueError:
            raise HTTPException(400, "This file is not valid JSON.") from None
        rows = data["jobs"] if isinstance(data, dict) and "jobs" in data else data if isinstance(data, list) else None
        if rows is None:
            raise HTTPException(400, "The file should contain a list of jobs.")
        cv = data.get("cv") if isinstance(data, dict) else None
        if isinstance(cv, dict) and cv.get("text") and not db.get_cv(con):
            db.set_cv(con, str(cv.get("filename") or "cv.txt"), str(cv["text"]), None)
        added = updated = skipped = 0
        for r in rows:
            r = r if isinstance(r, dict) else {}
            j = from_api({k: v for k, v in r.items() if k not in ("have", "need", "hasText")})
            if isinstance(j.get("reasons"), list):
                j["reasons"] = json.dumps(j["reasons"])
            j["facts"] = json.dumps(j["facts"]) if isinstance(j.get("facts"), dict) else ""
            if j.pop("applyLink", None) and not j.get("link"):
                j["link"] = r.get("applyLink")
            if not str(j.get("company", "")).strip():
                skipped += 1
                continue
            known = (j.get("id") and db.get_job(con, j["id"]) and j["id"]) or db.find_job(con, j["company"], j.get("role", ""), j.get("link", ""))
            if j.get("score") in (None, ""):
                j = {**j, **score_job(j, cv_text())}
            jid = db.upsert_job(con, j)
            restore_related(jid, r)
            updated, added = (updated + 1, added) if known else (updated, added + 1)
        return {"added": added, "updated": updated, "skipped": skipped}

    def restore_related(jid, r):
        # Add people, timeline entries and letters from an export, skipping the ones this job already has.
        have = {c["name"].strip().lower() for c in db.list_contacts(con, jid)}
        for c in r.get("contacts") or []:
            if isinstance(c, dict) and str(c.get("name", "")).strip() and str(c["name"]).strip().lower() not in have:
                db.add_contact(con, jid, from_api(c))
                have.add(str(c["name"]).strip().lower())
        seen = {(e["date"], e["kind"], e["text"]) for e in db.list_events(con, jid)}
        for e in r.get("events") or []:
            if not isinstance(e, dict) or e.get("kind") not in db.EVENT_KINDS:
                continue
            key = (str(e.get("date") or ""), e["kind"], str(e.get("text") or "").strip())
            if key[0] and key not in seen:
                db.add_event(con, jid, {"date": key[0], "kind": key[1], "text": key[2]})
                seen.add(key)
        texts = {lt["text"] for lt in db.list_letters(con, jid)}
        for lt in reversed(r.get("letters") or []):
            if isinstance(lt, dict) and str(lt.get("text") or "").strip() and lt["text"] not in texts:
                db.add_letter(con, jid, str(lt.get("language") or "English"), lt["text"], str(lt.get("model") or ""))
                texts.add(lt["text"])

    @app.get("/api/export")
    def export():
        out = []
        for j in db.list_jobs(con):
            d = to_api(j)
            d.pop("contactCount", None), d.pop("letterCount", None)
            d["postingText"] = j["posting_text"]
            d["contacts"] = [to_api(c) for c in db.list_contacts(con, j["id"])]
            d["events"] = [to_api(e) for e in db.list_events(con, j["id"])]
            d["letters"] = [{"language": lt["language"], "text": lt["text"], "model": lt["model"], "createdAt": lt["created_at"]}
                            for lt in db.list_letters(con, j["id"])]
            out.append(d)
        cv = db.get_cv(con)
        body = {"exportedAt": db.now(), "cv": {"filename": cv["filename"], "text": cv["text"]} if cv else None, "jobs": out}
        name = f"shortlist-export-{date.today().isoformat()}.json"
        return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    app.mount("/", NoCacheStatic(directory=WEB, html=True), name="web")
    for f in finds.new():  # finds that were read before the filter existed get their kind, hours and pay now
        if f["read"] and '"hours"' not in (f["facts"] or ""):
            finds.update(f["id"], score_find(f, f["text"] or ""))
    return app


class NoCacheStatic(StaticFiles):
    # The app shell and service worker must never be stale after an update.
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        if path in ("", ".", "index.html", "sw.js") or path.endswith((".js", ".css", ".webmanifest")):
            r.headers["Cache-Control"] = "no-cache"
        return r
