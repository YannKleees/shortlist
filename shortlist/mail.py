"""Read a mailbox over IMAP: jobs that people send you, and mails that show you applied or got an answer.

Only reads. Messages are fetched with BODY.PEEK, so nothing is marked as read, moved or deleted."""

import email
import imaplib
import re
import unicodedata
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.policy import default
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from .ingest import find_links, looks_like_job

TAG = "[Shortlist]"
JOB_BOARDS = ("linkedin.com", "indeed.", "glassdoor.", "stepstone.", "monster.", "moovijob", "jobs.lu", "xing.com", "google.com")
REJECTION = re.compile(r"unfortunately|regret to|not (?:to )?(?:move|moving) forward|other candidates|not been selected|"
                       r"decided to (?:pursue|proceed with) other|position has been filled|leider|absage|nicht berücksichtigen|"
                       r"malheureusement|pas retenu|ne pas donner suite", re.I)
CONFIRMATION = re.compile(r"thank you for (?:your )?appl|we (?:have )?received your application|application (?:has been )?received|"
                          r"vielen dank für ihre bewerbung|bewerbung (?:ist )?eingegangen|nous avons bien reçu votre candidature|"
                          r"merci pour votre candidature", re.I)
ABOUT_APPLICATION = re.compile(r"your application|ihre bewerbung|deine bewerbung|votre candidature|interview|vorstellungsgespräch|entretien", re.I)
INTERVIEW = re.compile(r"interview|vorstellungsgespräch|entretien|invite you|einladen|kennenlernen|call with", re.I)


@dataclass
class Message:
    uid: str
    msgid: str
    sender: str
    sender_name: str
    to: list
    subject: str
    date: str
    text: str


def _header(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def parse_message(uid, raw):
    msg = email.message_from_bytes(raw, policy=default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            text = body.get_content()
        except Exception:
            text = (body.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if body.get_content_type() == "text/html":
            text = BeautifulSoup(text, "html.parser").get_text("\n")
    name, addr = parseaddr(_header(msg.get("From")))
    try:
        day = parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except Exception:
        day = ""
    return Message(uid=str(uid), msgid=str(msg.get("Message-ID") or f"uid-{uid}").strip(), sender=addr.lower(), sender_name=name,
                   to=[a.lower() for _, a in getaddresses([_header(msg.get("To")), _header(msg.get("Cc"))]) if a],
                   subject=_header(msg.get("Subject")), date=day, text=text[:20000])


class Mailbox:
    """A thin, read only wrapper around imaplib that also understands Gmail search."""

    def __init__(self, address, password, host="imap.gmail.com", port=993, factory=imaplib.IMAP4_SSL):
        self.address, self.password, self.host, self.port, self.factory = address, password, host, port, factory
        self.imap = None

    def __enter__(self):
        self.imap = self.factory(self.host, self.port)
        self.imap.login(self.address, self.password)
        caps = self.imap.capabilities if isinstance(self.imap.capabilities, tuple | list) else ()
        self.gmail = "X-GM-EXT-1" in [c.decode() if isinstance(c, bytes) else c for c in caps]
        self.special = self._special_folders()
        return self

    def __exit__(self, *exc):
        try:
            self.imap.logout()
        except Exception:
            pass

    def _special_folders(self):
        out = {}
        typ, rows = self.imap.list()
        for row in rows or []:
            line = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
            m = re.match(r'\((?P<flags>[^)]*)\) "?[^ "]*"? (?P<name>.+)$', line)
            if not m:
                continue
            name = m["name"].strip().strip('"')
            for flag in ("\\All", "\\Sent"):
                if flag.lower() in m["flags"].lower():
                    out[flag] = name
        return out

    def select(self, folder):
        typ, _ = self.imap.select(f'"{folder}"', readonly=True)
        return typ == "OK"

    def uids(self, *criteria):
        typ, data = self.imap.uid("SEARCH", *criteria)
        return (data[0] or b"").split() if typ == "OK" and data else []

    def fetch(self, uids):
        out = []
        for uid in uids:
            typ, data = self.imap.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((d[1] for d in data or [] if isinstance(d, tuple)), None)
            if typ == "OK" and raw:
                out.append(parse_message(uid.decode() if isinstance(uid, bytes) else uid, raw))
        return out

    def find(self, words, sent):
        """Messages mentioning `words`, either sent by you or received. Newest 15 only."""
        # IMAP search arguments must be ASCII; mail search ignores accents anyway.
        plain = unicodedata.normalize("NFKD", words).encode("ascii", "ignore").decode()
        plain = re.sub(r'["\\]', "", plain).strip()
        if not plain:
            return []
        if self.gmail and self.special.get("\\All") and self.select(self.special["\\All"]):
            q = f'in:sent \\"{plain}\\"' if sent else f'-in:sent \\"{plain}\\"'
            return self.fetch(self.uids("X-GM-RAW", f'"{q}"')[-15:])
        folder = self.special.get("\\Sent") if sent else "INBOX"
        if not folder or not self.select(folder):
            return []
        return self.fetch(self.uids("TEXT", f'"{plain}"')[-15:])

    def new_in_inbox(self, after_uid):
        if not self.select("INBOX"):
            return []
        uids = [u for u in self.uids("UID", f"{int(after_uid) + 1}:*") if int(u) > int(after_uid)]
        return self.fetch(uids[-50:])


# Jobs people send you


def helper_name(msg):
    # The jobs page puts the sender's name in the subject: "[Shortlist] Mama: Data Analyst at Contoso".
    m = re.match(rf"^\s*{re.escape(TAG)}\s*(?P<name>[^:]{{1,40}}):", msg.subject)
    return (m["name"].strip() if m else "") or msg.sender_name or msg.sender.split("@")[0]


def shared_jobs(messages, me=""):
    """Job links in new mails: every link in a mail from the jobs page, and job looking links in any other mail."""
    out = []
    for msg in messages:
        tagged = TAG.lower() in msg.subject.lower()
        if msg.sender == (me or "").lower() and not tagged:
            continue
        links = [u for u in find_links(msg.text + "\n" + msg.subject) if tagged or looks_like_job(u)]
        if not links:
            continue
        note = "\n".join(ln.strip() for ln in msg.text.splitlines() if ln.strip() and not any(u in ln for u in links)
                         and not ln.strip().startswith("—") and "shortlist" not in ln.lower())
        title = re.sub(rf"^\s*{re.escape(TAG)}\s*[^:]{{0,40}}:\s*", "", msg.subject) if tagged else ""
        for u in links:
            out.append({"link": u, "by": helper_name(msg), "note": note[:500], "title": title, "msgid": msg.msgid, "date": msg.date})
    return out


# Did you apply, did they answer


def domain(addr):
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def evidence(sent, received, me=""):
    """Turn the mails found for one company into facts: applied on, confirmation, reply, rejection."""
    me = (me or "").lower()
    out, their_domains = [], set()
    for m in sorted(sent, key=lambda m: m.date):
        their_domains.update(domain(a) for a in m.to if a != me and not any(b in a for b in JOB_BOARDS))
        out.append({"kind": "sent", "date": m.date, "subject": m.subject, "msgid": m.msgid})
    for m in sorted(received, key=lambda m: m.date):
        if m.sender == me or any(b in m.sender for b in JOB_BOARDS) or TAG.lower() in m.subject.lower():
            continue
        body = m.subject + "\n" + m.text
        if REJECTION.search(body):
            kind = "rejection"
        elif CONFIRMATION.search(body):
            kind = "confirmation"
        elif domain(m.sender) in their_domains or ABOUT_APPLICATION.search(body):
            kind = "interview" if INTERVIEW.search(body) else "reply"
        else:
            continue
        out.append({"kind": kind, "date": m.date, "subject": m.subject, "msgid": m.msgid, "from": m.sender,
                    "about_application": bool(ABOUT_APPLICATION.search(body))})
    return out
