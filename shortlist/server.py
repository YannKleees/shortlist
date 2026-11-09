import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import requests
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import cvparse, db, ingest, letters
from .scoring import score_job

WEB = Path(__file__).resolve().parent.parent / "web"
CAMEL = {"work_setup": "workSetup", "next_step": "nextStep", "added_by": "addedBy", "applied_on": "appliedOn",
         "follow_up": "followUp", "created_at": "createdAt", "updated_at": "updatedAt", "uploaded_at": "uploadedAt",
         "job_id": "jobId", "posting_text": "postingText", "company_about": "companyAbout", "cv_sent": "cvSent",
         "replied_on": "repliedOn", "contact_count": "contactCount", "letter_count": "letterCount", "last_contact": "lastContact"}
SNAKE = {v: k for k, v in CAMEL.items()}
STATUSES = ["To apply", "Applied", "Waiting", "Interview", "Accepted", "Rejected", "Not interested"]

to_api = lambda d: {CAMEL.get(k, k): v for k, v in d.items() if k not in ("posting_text", "content")}
from_api = lambda d: {SNAKE.get(k, k): v for k, v in d.items()}
NO_LLM = "The local LLM did not answer. Start Ollama and run: ollama pull {}"


def create_app(db_path="shortlist.db", fetch=ingest.fetch, llm_post=requests.post, llm_get=requests.get, wiki_get=requests.get):
    con = db.connect(db_path)
    app = FastAPI(title="Shortlist")
    llm_url = lambda: db.get_setting(con, "llm_url", os.environ.get("OLLAMA_URL", letters.DEFAULT_URL))
    llm_model = lambda: db.get_setting(con, "llm_model", os.environ.get("OLLAMA_MODEL", letters.DEFAULT_MODEL))
    cv_text = lambda: (db.get_cv(con) or {}).get("text", "")

    def job_or_404(jid):
        j = db.get_job(con, jid)
        if not j:
            raise HTTPException(404, "Job not found.")
        return j

    def save_scored(job):
        return db.get_job(con, db.upsert_job(con, {**job, **score_job(job, cv_text())}))

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
        }

    @app.put("/api/settings")
    def settings(payload: dict = Body(...)):
        for k in ("llm_model", "llm_url"):
            if payload.get(k):
                db.set_setting(con, k, str(payload[k]).strip())
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
        return {"filename": file.filename, "chars": len(text)}

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

    @app.post("/api/jobs/import-link")
    def import_link(payload: dict = Body(...)):
        get = lambda k: str(payload.get(k, "")).strip()
        url = get("url")
        if not re.match(r"^https?://", url):
            raise HTTPException(422, "Paste the full link, starting with https://")
        link = ingest.canonical_link(url)
        existing = db.find_job(con, "", "\x00", link)
        if existing:
            return to_api(db.get_job(con, existing))
        if get("text"):
            p = {"company": get("company"), "role": get("role"), "location": get("location"), "text": get("text"),
                 "about": ingest.about_section(get("text"), get("company"))}
        else:
            try:
                p = ingest.parse_posting(fetch(link), link)
            except Exception:
                raise HTTPException(422, "Could not read this posting. LinkedIn often hides jobs behind a login: paste the job text instead.") from None
        if not p["company"]:
            raise HTTPException(422, "Could not find the company name. Add the job by hand.")
        return to_api(save_scored({
            "company": p["company"], "role": p["role"], "location": p["location"], "link": link, "posting_text": p["text"],
            "source": ingest.detect_source(link), "status": "To apply", **overview(p["company"], p["text"], p["about"]),
        }))

    @app.patch("/api/jobs/{jid}")
    def patch_job(jid: str, payload: dict = Body(...)):
        job = job_or_404(jid)
        fields = from_api(payload)
        new_status = fields.get("status")
        if new_status and new_status not in STATUSES:
            raise HTTPException(422, "Unknown status.")
        if new_status == "Applied":
            fields["cv_sent"] = 1
            fields["applied_on"] = job["applied_on"] or date.today().isoformat()
            fields["follow_up"] = job["follow_up"] or (date.fromisoformat(fields["applied_on"]) + timedelta(days=10)).isoformat()
        updated = db.update_job(con, jid, fields)
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
        return to_api(db.update_job(con, jid, score_job({**job, "pros": "", "cons": ""}, cv_text())))

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
        added = updated = skipped = 0
        for r in rows:
            j = from_api(r if isinstance(r, dict) else {})
            if j.pop("applyLink", None) and not j.get("link"):
                j["link"] = r.get("applyLink")
            if not str(j.get("company", "")).strip():
                skipped += 1
                continue
            known = db.find_job(con, j["company"], j.get("role", ""), j.get("link", ""))
            if j.get("score") in (None, ""):
                j = {**j, **score_job(j, cv_text())}
            db.upsert_job(con, j)
            updated, added = (updated + 1, added) if known else (updated, added + 1)
        return {"added": added, "updated": updated, "skipped": skipped}

    @app.get("/api/export")
    def export():
        out = []
        for j in db.list_jobs(con):
            d = to_api(j)
            d["contacts"] = [to_api(c) for c in db.list_contacts(con, j["id"])]
            d["events"] = [to_api(e) for e in db.list_events(con, j["id"])]
            out.append(d)
        return {"exportedAt": db.now(), "jobs": out}

    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app
