import hashlib
import re
import secrets
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
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
    "skills": "TEXT DEFAULT ''", "needs": "TEXT DEFAULT ''", "sent_by_user": "INTEGER", "facts": "TEXT DEFAULT ''",
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
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, password TEXT DEFAULT '', role TEXT NOT NULL DEFAULT 'helper',
    share_key TEXT DEFAULT '', created_at TEXT NOT NULL, last_seen TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS users_name ON users (lower(trim(name)));
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'helper', user_id INTEGER REFERENCES users (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE, msgid TEXT NOT NULL,
    date TEXT DEFAULT '', kind TEXT NOT NULL, sender TEXT DEFAULT '', sender_name TEXT DEFAULT '', subject TEXT DEFAULT '',
    body TEXT DEFAULT '', seen INTEGER DEFAULT 0, created_at TEXT NOT NULL, UNIQUE (job_id, msgid)
);
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_at TEXT NOT NULL
);
""".replace("{cols}", ", ".join(f"{k} {v}" for k, v in JOB_COLUMNS.items()))

now = lambda: datetime.now(UTC).isoformat(timespec="seconds")
today = lambda: datetime.now().date().isoformat()


class _Rows:
    # A finished query: rows are read while the lock is held, so threads never share a half read statement.
    def __init__(self, cur):
        self.rows, self.lastrowid = cur.fetchall(), cur.lastrowid

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class Connection:
    """One SQLite connection shared by the web server, the mail watcher and the notification sender, one call at a time."""

    def __init__(self, raw):
        self.raw, self.lock = raw, threading.RLock()

    def execute(self, sql, args=()):
        with self.lock:
            return _Rows(self.raw.execute(sql, args))

    def executescript(self, sql):
        with self.lock:
            return self.raw.executescript(sql)

    def commit(self):
        with self.lock:
            self.raw.commit()

    def close(self):
        with self.lock:
            self.raw.close()


def connect(path):
    con = Connection(sqlite3.connect(path, check_same_thread=False))
    con.raw.row_factory = sqlite3.Row
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


# Accounts. Tokens are random and only their SHA-256 is stored, so a copy of the database cannot be used to sign in.

ROLES = ("owner", "helper")
SESSION_DAYS = 365
INVITE_DAYS = 14
_digest = lambda token: hashlib.sha256(token.encode()).hexdigest()


def hash_password(pw):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${key.hex()}"


def check_password(pw, stored):
    try:
        _, salt, key = stored.split("$")
        return secrets.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex(), key)
    except (ValueError, AttributeError):
        return False


def count_users(con):
    return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def add_user(con, name, role="helper", password=""):
    cur = con.execute("INSERT INTO users (name, password, role, share_key, created_at) VALUES (?, ?, ?, ?, ?)",
                      (name.strip(), hash_password(password) if password else "", role, secrets.token_urlsafe(18), now()))
    con.commit()
    return cur.lastrowid


def get_user(con, uid):
    r = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(r) if r else None


def user_by_name(con, name):
    r = con.execute("SELECT * FROM users WHERE lower(trim(name)) = lower(trim(?))", (name or "",)).fetchone()
    return dict(r) if r else None


def user_by_share_key(con, key):
    r = con.execute("SELECT * FROM users WHERE share_key = ? AND share_key != ''", (key or "",)).fetchone()
    return dict(r) if r else None


def list_users(con):
    return [dict(r) for r in con.execute("SELECT * FROM users ORDER BY role = 'helper', id")]


def update_user(con, uid, name=None, password=None):
    if name:
        con.execute("UPDATE users SET name = ? WHERE id = ?", (name.strip(), uid))
    if password:
        con.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), uid))
    con.commit()
    return get_user(con, uid)


def delete_user(con, uid):
    con.execute("DELETE FROM users WHERE id = ?", (uid,))
    con.commit()


def new_session(con, uid):
    token = secrets.token_urlsafe(32)
    t = datetime.now(UTC)
    con.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_digest(token), uid, t.isoformat(timespec="seconds"), (t + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")))
    con.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now(), uid))
    con.commit()
    return token


def session_user(con, token):
    if not token:
        return None
    r = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires_at > ?",
                    (_digest(token), now())).fetchone()
    return dict(r) if r else None


def end_session(con, token):
    con.execute("DELETE FROM sessions WHERE token = ?", (_digest(token or ""),))
    con.commit()


def new_invite(con, name, role="helper", user_id=None, minutes=None):
    # A link that creates an account, or with user_id signs an existing person in on a new phone.
    token = secrets.token_urlsafe(18)
    t = datetime.now(UTC)
    con.execute("DELETE FROM invites WHERE expires_at <= ?", (now(),))
    life = timedelta(minutes=minutes) if minutes else timedelta(days=INVITE_DAYS)
    con.execute("INSERT INTO invites (token, name, role, user_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_digest(token), name.strip(), role, user_id, t.isoformat(timespec="seconds"),
                 (t + life).isoformat(timespec="seconds")))
    con.commit()
    return token


def get_invite(con, token):
    r = con.execute("SELECT * FROM invites WHERE token = ? AND expires_at > ?", (_digest(token or ""), now())).fetchone()
    return dict(r) if r else None


def use_invite(con, token):
    con.execute("DELETE FROM invites WHERE token = ?", (_digest(token or ""),))
    con.commit()


def save_push(con, uid, endpoint, p256dh, auth):
    con.execute("INSERT INTO push_subs (endpoint, user_id, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth",
                (endpoint, uid, p256dh, auth, now()))
    con.commit()


def push_targets(con, user_ids=None, role=None):
    q, args = "SELECT p.* FROM push_subs p JOIN users u ON u.id = p.user_id WHERE 1 = 1", []
    if user_ids is not None:
        ids = [int(i) for i in user_ids if i] or [-1]
        q += f" AND u.id IN ({','.join('?' * len(ids))})"
        args += ids
    if role:
        q += " AND u.role = ?"
        args.append(role)
    return [dict(r) for r in con.execute(q, args)]


def has_push(con, uid):
    return con.execute("SELECT 1 FROM push_subs WHERE user_id = ?", (uid,)).fetchone() is not None


def drop_push(con, endpoint):
    con.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
    con.commit()


# Mails to and from companies, shown in the inbox and on each job

MAIL_FIELDS = ("id", "job_id", "msgid", "date", "kind", "sender", "sender_name", "subject", "body", "seen", "created_at")


def add_mail(con, job_id, e):
    seen = 1 if e["kind"] == "sent" else 0
    con.execute("INSERT OR IGNORE INTO mails (job_id, msgid, date, kind, sender, sender_name, subject, body, seen, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, e["msgid"], e.get("date") or "", e["kind"], e.get("from") or "", e.get("name") or "", e.get("subject") or "",
                 e.get("body") or "", seen, now()))
    con.commit()


def list_mails(con, job_id=None, received_only=False, limit=200):
    q = ("SELECT m.*, j.company AS company, j.role AS role FROM mails m JOIN jobs j ON j.id = m.job_id WHERE 1 = 1")
    args = []
    if job_id:
        q += " AND m.job_id = ?"
        args.append(job_id)
    if received_only:
        q += " AND m.kind != 'sent'"
    q += " ORDER BY m.date DESC, m.id DESC LIMIT ?"
    return [dict(r) for r in con.execute(q, [*args, limit])]


def unseen_mails(con):
    return con.execute("SELECT COUNT(*) FROM mails WHERE seen = 0").fetchone()[0]


def mark_mails_seen(con, job_id=None, ids=None):
    if job_id:
        con.execute("UPDATE mails SET seen = 1 WHERE job_id = ?", (job_id,))
    for i in ids or []:
        con.execute("UPDATE mails SET seen = 1 WHERE id = ?", (int(i),))
    con.commit()
