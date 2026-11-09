import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

JOB_COLUMNS = {
    "company": "TEXT NOT NULL", "role": "TEXT DEFAULT ''", "location": "TEXT DEFAULT ''", "link": "TEXT DEFAULT ''",
    "work_setup": "TEXT DEFAULT 'Unknown'", "type": "TEXT DEFAULT ''", "status": "TEXT DEFAULT 'To apply'",
    "score": "INTEGER", "fit": "TEXT DEFAULT ''", "pros": "TEXT DEFAULT ''", "cons": "TEXT DEFAULT ''",
    "summary": "TEXT DEFAULT ''", "company_about": "TEXT DEFAULT ''",
    "next_step": "TEXT DEFAULT ''", "notes": "TEXT DEFAULT ''", "source": "TEXT DEFAULT ''", "added_by": "TEXT DEFAULT 'you'",
    "deadline": "TEXT DEFAULT ''", "cv_sent": "INTEGER DEFAULT 0", "applied_on": "TEXT DEFAULT ''",
    "follow_up": "TEXT DEFAULT ''", "replied_on": "TEXT DEFAULT ''", "posting_text": "TEXT DEFAULT ''",
    "salary": "TEXT DEFAULT ''", "distance_km": "REAL", "reasons": "TEXT DEFAULT ''",
    "created_at": "TEXT NOT NULL", "updated_at": "TEXT NOT NULL",
}
JOB_FIELDS = list(JOB_COLUMNS)
CONTACT_FIELDS = ["name", "role", "relation", "email", "linkedin", "phone", "last_contact", "notes"]
EVENT_KINDS = ["Note", "Applied", "Email sent", "Message sent", "Reply", "Call", "Interview", "Offer", "Rejection", "Status"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, {cols});
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    name TEXT NOT NULL, role TEXT DEFAULT '', relation TEXT DEFAULT '', email TEXT DEFAULT '', linkedin TEXT DEFAULT '',
    phone TEXT DEFAULT '', last_contact TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    date TEXT NOT NULL, kind TEXT NOT NULL, text TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cv (
    id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, text TEXT NOT NULL, content BLOB, uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    language TEXT NOT NULL, text TEXT NOT NULL, model TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS mail_seen (msgid TEXT NOT NULL, job_id TEXT NOT NULL, PRIMARY KEY (msgid, job_id));
""".replace("{cols}", ", ".join(f"{k} {v}" for k, v in JOB_COLUMNS.items()))

now = lambda: datetime.now(UTC).isoformat(timespec="seconds")
today = lambda: datetime.now().date().isoformat()


def connect(path):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
    for col, decl in JOB_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl.replace('NOT NULL', '')}")
            if decl.endswith("DEFAULT ''") or "DEFAULT 0" in decl:
                con.execute(f"UPDATE jobs SET {col} = {'0' if 'DEFAULT 0' in decl else chr(39) * 2} WHERE {col} IS NULL")
    con.execute("CREATE INDEX IF NOT EXISTS jobs_key ON jobs (lower(trim(company)), lower(trim(role)))")
    con.commit()
    return con


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "job"


# Jobs


def list_jobs(con):
    return [dict(r) for r in con.execute(
        "SELECT j.*, (SELECT COUNT(*) FROM contacts c WHERE c.job_id = j.id) AS contact_count,"
        " (SELECT COUNT(*) FROM letters l WHERE l.job_id = j.id) AS letter_count FROM jobs j ORDER BY created_at")]


def get_job(con, jid):
    r = con.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    return dict(r) if r else None


def find_job(con, company, role, link=""):
    r = con.execute(
        "SELECT id FROM jobs WHERE (trim(?) != '' AND lower(trim(company)) = lower(trim(?)) AND lower(trim(role)) = lower(trim(?)))"
        " OR (? != '' AND link = ?)", (company or "", company or "", role or "", link, link)).fetchone()
    return r["id"] if r else None


def upsert_job(con, job):
    # Insert a new job, or update the one with the same id, link, or company and role.
    job = {k: v for k, v in job.items() if k in JOB_FIELDS or k == "id"}
    known = job.get("id") and get_job(con, job["id"])
    jid = job["id"] if known else find_job(con, job.get("company", ""), job.get("role", ""), job.get("link", ""))
    if jid:
        update_job(con, jid, {k: v for k, v in job.items() if v not in (None, "") and k != "id"})
        return jid
    jid = job.get("id") or f"{_slug(job['company'] + ' ' + job.get('role', ''))}-{datetime.now().strftime('%y%m%d%H%M%S%f')[-10:]}"
    t = now()
    job = {**job, "id": jid, "created_at": job.get("created_at") or t, "updated_at": t}
    cols = list(job)
    con.execute(f"INSERT INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [job[c] for c in cols])
    con.commit()
    return jid


def update_job(con, jid, fields):
    fields = {k: v for k, v in fields.items() if k in JOB_FIELDS and k != "created_at"}
    if fields:
        fields["updated_at"] = now()
        con.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", [*fields.values(), jid])
        con.commit()
    return get_job(con, jid)


def delete_job(con, jid):
    con.execute("DELETE FROM jobs WHERE id = ?", (jid,))
    con.commit()


# People


def add_contact(con, job_id, c):
    c = {k: str(v).strip() for k, v in c.items() if k in CONTACT_FIELDS and v is not None}
    cols = ["job_id", *c, "created_at"]
    cur = con.execute(f"INSERT INTO contacts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [job_id, *c.values(), now()])
    con.commit()
    return cur.lastrowid


def get_contact(con, cid):
    r = con.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
    return dict(r) if r else None


def list_contacts(con, job_id):
    return [dict(r) for r in con.execute("SELECT * FROM contacts WHERE job_id = ? ORDER BY id", (job_id,))]


def update_contact(con, cid, fields):
    fields = {k: str(v).strip() for k, v in fields.items() if k in CONTACT_FIELDS and v is not None}
    if fields:
        con.execute(f"UPDATE contacts SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", [*fields.values(), cid])
        con.commit()
    return get_contact(con, cid)


def delete_contact(con, cid):
    con.execute("DELETE FROM contacts WHERE id = ?", (cid,))
    con.commit()


# Timeline


def add_event(con, job_id, e):
    cur = con.execute("INSERT INTO events (job_id, date, kind, text, created_at) VALUES (?, ?, ?, ?, ?)",
                      (job_id, e.get("date") or today(), e["kind"], str(e.get("text") or "").strip(), now()))
    con.commit()
    return cur.lastrowid


def list_events(con, job_id):
    return [dict(r) for r in con.execute("SELECT * FROM events WHERE job_id = ? ORDER BY date DESC, id DESC", (job_id,))]


def delete_event(con, eid):
    con.execute("DELETE FROM events WHERE id = ?", (eid,))
    con.commit()


# CV and letters


def set_cv(con, filename, text, content):
    con.execute("INSERT INTO cv (filename, text, content, uploaded_at) VALUES (?, ?, ?, ?)", (filename, text, content, now()))
    con.commit()


def get_cv(con):
    r = con.execute("SELECT id, filename, text, uploaded_at FROM cv ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def add_letter(con, job_id, language, text, model):
    t = now()
    cur = con.execute("INSERT INTO letters (job_id, language, text, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                      (job_id, language, text, model, t, t))
    con.commit()
    return cur.lastrowid


def get_letter(con, lid):
    r = con.execute("SELECT * FROM letters WHERE id = ?", (lid,)).fetchone()
    return dict(r) if r else None


def list_letters(con, job_id):
    return [dict(r) for r in con.execute("SELECT * FROM letters WHERE job_id = ? ORDER BY id DESC", (job_id,))]


def update_letter(con, lid, text):
    con.execute("UPDATE letters SET text = ?, updated_at = ? WHERE id = ?", (text, now(), lid))
    con.commit()
    return get_letter(con, lid)


def get_setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
    con.commit()


# Backups


def backup(path, folder=None, keep=14):
    # Copy the database once a day into a backups folder next to it, keeping the newest `keep` copies.
    src = Path(path)
    if not src.exists() or src.stat().st_size == 0:
        return None
    out = Path(folder) if folder else src.parent / "backups"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{src.stem}-{datetime.now().date().isoformat()}.db"
    if not dest.exists():
        a, b = sqlite3.connect(src), sqlite3.connect(dest)
        try:
            a.backup(b)
            b.execute("PRAGMA journal_mode = DELETE")  # a plain single file copy
        finally:
            b.close()
            a.close()
    for old in sorted(out.glob(f"{src.stem}-????-??-??.db"))[:-keep]:
        old.unlink()
    return dest


# Mail that was already turned into a timeline entry


def mail_seen(con, msgid, job_id):
    return con.execute("SELECT 1 FROM mail_seen WHERE msgid = ? AND job_id = ?", (msgid, job_id)).fetchone() is not None


def mark_mail_seen(con, msgid, job_id):
    con.execute("INSERT OR IGNORE INTO mail_seen (msgid, job_id) VALUES (?, ?)", (msgid, job_id))
    con.commit()
