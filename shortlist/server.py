import imaplib
import json
import mimetypes
import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path

import requests
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cvparse, db, geo, ingest, letters, mail
from .score import SPOKEN
from .scoring import score_job

WEB = Path(__file__).resolve().parent.parent / "web"
CAMEL = {"work_setup": "workSetup", "next_step": "nextStep", "added_by": "addedBy", "applied_on": "appliedOn",
         "follow_up": "followUp", "created_at": "createdAt", "updated_at": "updatedAt", "uploaded_at": "uploadedAt",
         "job_id": "jobId", "posting_text": "postingText", "company_about": "companyAbout", "cv_sent": "cvSent",
         "replied_on": "repliedOn", "contact_count": "contactCount", "letter_count": "letterCount", "last_contact": "lastContact",
         "distance_km": "distanceKm"}
SNAKE = {v: k for k, v in CAMEL.items()}
STATUSES = ["To apply", "Applied", "Waiting", "Interview", "Accepted", "Rejected", "Not interested"]
mimetypes.add_type("application/manifest+json", ".webmanifest")
HELPER_PAGE = os.environ.get("SHORTLIST_HELPER_PAGE", "https://yannkleees.github.io/shortlist/")


def _reasons(v):
    try:
        return json.loads(v) if isinstance(v, str) and v else (v or [])
    except ValueError:
        return []


def to_api(d):
    out = {CAMEL.get(k, k): v for k, v in d.items() if k not in ("posting_text", "content")}
    if "reasons" in out:
        out["reasons"] = _reasons(out["reasons"])
    if "posting_text" in d:
        out["hasText"] = bool(d["posting_text"])
    return out


from_api = lambda d: {SNAKE.get(k, k): v for k, v in d.items()}
NO_LLM = "The local LLM did not answer. Start Ollama and run: ollama pull {}"
FOLLOW_UP_DAYS = 10
NUDGE_DAYS = 7
NUDGES = ("Email sent", "Message sent", "Call")
OPEN = ("To apply", "Applied", "Waiting", "Interview")


def create_app(db_path="shortlist.db", fetch=ingest.fetch, llm_post=requests.post, llm_get=requests.get, wiki_get=requests.get,
               geo_get=requests.get, imap_factory=imaplib.IMAP4_SSL):
    con = db.connect(db_path)
    app = FastAPI(title="Shortlist")
    places = geo.Geocoder(con, get=geo_get)
    setting = lambda k, default="": db.get_setting(con, k, default) or default
    llm_url = lambda: db.get_setting(con, "llm_url", os.environ.get("OLLAMA_URL", letters.DEFAULT_URL))
    llm_model = lambda: db.get_setting(con, "llm_model", os.environ.get("OLLAMA_MODEL", letters.DEFAULT_MODEL))
    cv_text = lambda: (db.get_cv(con) or {}).get("text", "")
    spoken = lambda: [s.strip() for s in setting("languages", ", ".join(SPOKEN)).split(",") if s.strip()]

    def job_or_404(jid):
        j = db.get_job(con, jid)
        if not j:
            raise HTTPException(404, "Job not found.")
        return j

    def scored(job, cv=None):
        home, place = setting("home"), job.get("location") or ""
        km = places.distance_km(home, place) if home and place and job.get("work_setup") != "Remote" else None
        return score_job(job, cv_text() if cv is None else cv, distance_km=km, spoken=spoken())

    def save_scored(job):
        return db.get_job(con, db.upsert_job(con, {**job, **scored(job)}))

    def rescore_one(j, cv=None):
        s = scored(j, cv)
        return db.update_job(con, j["id"], {k: s.get(k) for k in ("score", "fit", "reasons", "distance_km")})

    def rescore_all():
        # A new CV, home or language list changes every score. Pros, cons and other edits stay as they are.
        cv = cv_text()
        jobs = db.list_jobs(con)
        for j in jobs:
            rescore_one(j, cv)
        return len(jobs)

    def overview(company, text, about=""):
        about = about or (ingest.wikipedia_about(company, get=wiki_get) if wiki_get and company else "")
        return {"summary": ingest.summarize(text) if text else "", "company_about": about}

    def detail(jid):
        j = to_api(job_or_404(jid))
        j["contacts"] = [to_api(c) for c in db.list_contacts(con, jid)]
        j["events"] = [to_api(e) for e in db.list_events(con, jid)]
        j["letters"] = [{"id": lt["id"], "language": lt["language"], "updatedAt": lt["updated_at"]} for lt in db.list_letters(con, jid)]
        return j

    # Status and settings

    @app.get("/api/status")
    def status():
        cv = db.get_cv(con)
        return {
            "cv": {"filename": cv["filename"], "uploadedAt": cv["uploaded_at"], "chars": len(cv["text"])} if cv else None,
            "llm": {**letters.status(llm_url(), get=llm_get), "model": llm_model(), "url": llm_url()},
            "home": setting("home"),
            "firstName": setting("first_name"),
            "languages": ", ".join(spoken()),
            "mail": {"address": setting("mail_address"), "ready": bool(setting("mail_address") and setting("mail_password")),
                     "lastCheck": setting("mail_last_check"), "last": _reasons(setting("mail_last_result", "{}")) or {}},
            "helperPage": HELPER_PAGE,
        }

    @app.put("/api/settings")
    def settings(payload: dict = Body(...)):
        for k in ("llm_model", "llm_url", "mail_address", "mail_host", "first_name"):
            if payload.get(k):
                db.set_setting(con, k, str(payload[k]).strip())
        if payload.get("mail_password"):
            db.set_setting(con, "mail_password", re.sub(r"\s+", "", str(payload["mail_password"])))  # Google shows it in groups of four
        changed = False
        for k in ("home", "languages"):
            if k in payload and str(payload[k] or "").strip() != setting(k):
                db.set_setting(con, k, str(payload[k] or "").strip())
                changed = True
        if changed:
            rescore_all()
        return status()

    # CV

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
        return {"filename": file.filename, "chars": len(text), "rescored": rescore_all()}

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

    def add_from_link(url, text="", company="", role="", location="", added_by="you", note="", day="", posting=False):
        """Save a job from a link. Never fails on a page that cannot be read: the job is saved with what the
        shared text says, and the posting text can be pasted later. Returns (job, is_new)."""
        link = ingest.canonical_link(url)
        existing = db.find_job(con, "", "", link)
        if existing:
            return db.get_job(con, existing), False
        shared = ingest.parse_shared(text, url)
        company, role, location = company or shared["company"], role or shared["role"], location or shared["location"]
        is_posting = len(text) > 300 or (posting and len(text) > 80)  # a pasted job description, not a one line share
        p = None
        if is_posting:
            p = {"company": company, "role": role, "location": location, "text": text, "about": ingest.about_section(text, company)}
        else:
            try:
                p = ingest.read_posting(link, fetch=fetch)
                p = {**p, "company": p["company"] or company, "role": p["role"] or role, "location": p["location"] or location}
            except Exception:
                p = None
        if not p or not p.get("text"):
            p = {"company": company, "role": role, "location": location, "text": "", "about": ""}
        job = save_scored({
            "company": p["company"], "role": p["role"], "location": p["location"], "link": link, "posting_text": p["text"],
            "source": ingest.detect_source(link), "status": "To apply", "added_by": added_by or "you",
            **overview(p["company"], p["text"], p["about"]),
        })
        if note:
            db.add_event(con, job["id"], {"kind": "Note", "text": f"{added_by}: {note}" if added_by != "you" else note, "date": day})
        return job, True

    @app.post("/api/jobs/import-link")
    def import_link(payload: dict = Body(...)):
        get = lambda k: str(payload.get(k, "")).strip()
        url = (ingest.find_links(get("url")) or [""])[0]  # also accepts "Check out this job ... https://..."
        if not url:
            raise HTTPException(422, "Paste the full link, starting with https://")
        shared = get("url").replace(url, " ").strip()
        job, _ = add_from_link(url, text=get("text") or shared, company=get("company"), role=get("role"), location=get("location"),
                               added_by=get("addedBy") or "you", note=get("note"), posting=bool(get("text")))
        return to_api(job)

    @app.post("/api/jobs/{jid}/text")
    def add_text(jid: str, payload: dict = Body(...)):
        # For pages that cannot be read, such as Indeed: paste the job description by hand.
        job = job_or_404(jid)
        text = str(payload.get("text", "")).strip()
        if len(text) < 80:
            raise HTTPException(422, "Paste the whole job description.")
        fields = {k: str(payload.get(k) or "").strip() or job[k] for k in ("company", "role", "location")}
        if not fields["company"]:
            raise HTTPException(422, "Enter the company name.")
        updated = {**job, **fields, "posting_text": text[:20000], "pros": "", "cons": "", "salary": job["salary"]}
        updated.update(overview(fields["company"], text, ingest.about_section(text, fields["company"]) or job["company_about"]))
        s = scored(updated)
        updated.update({k: v for k, v in s.items() if v is not None or k == "distance_km"})
        return to_api(db.update_job(con, jid, updated))

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
            db.add_event(con, jid, {"kind": kind, "text": "CV sent" if kind == "Applied" else f"Status changed to {new_status}"})
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
        if fields:
            db.update_job(con, j["id"], fields)
        db.add_event(con, j["id"], {"kind": kind, "text": text, "date": d})
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
                    _, new = add_from_link(item["link"], text=item["title"], added_by=item["by"], note=item["note"], day=item["date"])
                    result["added"] += new
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

    app.state.check_mail = check_mail
    app.state.mail_ready = lambda: bool(setting("mail_address") and setting("mail_password"))

    @app.post("/api/mail/check")
    def mail_check():
        return check_mail()

    # People

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
        cv = cv_text()
        if not cv:
            raise HTTPException(400, "Add your CV first, so the letter can use your real experience.")
        lang = payload.get("language") or "English"
        try:
            text = letters.generate(cv, job, lang, payload.get("notes", ""), model=llm_model(), url=llm_url(), post=llm_post)
        except Exception:
            raise HTTPException(503, NO_LLM.format(llm_model())) from None
        return to_api(db.get_letter(con, db.add_letter(con, jid, lang, text, llm_model())))

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
        try:
            new = letters.chat(letters.revise_messages(str(payload.get("text") or lt["text"]), instruction, cv_text(), job, lt["language"]),
                               model=llm_model(), url=llm_url(), post=llm_post)
        except Exception:
            raise HTTPException(503, NO_LLM.format(llm_model())) from None
        return to_api(db.get_letter(con, db.add_letter(con, lt["job_id"], lt["language"], new, llm_model())))

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
            j = from_api(r)
            if isinstance(j.get("reasons"), list):
                j["reasons"] = json.dumps(j["reasons"])
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

    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app
