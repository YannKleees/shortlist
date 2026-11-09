import io

import requests

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"

SYSTEM = """You write motivation letters for job applications.
Rules:
1. Use only facts from the CV and the posting. Never invent experience, grades, projects, dates or skills.
2. Write in {language}, in the formal register usual for that language.
3. 250 to 350 words, four short paragraphs: why this role and company, two or three concrete matches between the CV
   and the posting, what the candidate wants to learn and contribute, a short closing.
4. Address the company by name. Start with a proper salutation and end with a sign off and the candidate's name if the CV gives it.
5. No headings, no placeholders in brackets, no bullet points, no flattery.
Return only the letter text."""


def build_messages(cv, job, language="English", notes=""):
    posting = job.get("posting_text") or " ".join(x for x in [job.get("role", ""), job.get("location", ""), job.get("pros", "")] if x)
    user = (
        f"Company: {job.get('company', '')}\nRole: {job.get('role', '')}\nLocation: {job.get('location', '')}\n\n"
        f"<posting>\n{posting[:8000]}\n</posting>\n\n<cv>\n{cv[:8000]}\n</cv>\n"
    )
    if notes:
        user += f"\nExtra instructions from the candidate: {notes}\n"
    return [{"role": "system", "content": SYSTEM.format(language=language)}, {"role": "user", "content": user}]


REVISE = """You edit motivation letters.
Apply the candidate's instruction to the letter. Keep it in {language}.
Do not add new facts: use only what is already in the letter, the CV and the posting.
Return only the revised letter text."""


def revise_messages(text, instruction, cv, job, language="English"):
    user = (f"Company: {job.get('company', '')}\nRole: {job.get('role', '')}\n\n<cv>\n{cv[:6000]}\n</cv>\n\n"
            f"<letter>\n{text}\n</letter>\n\nInstruction: {instruction}")
    return [{"role": "system", "content": REVISE.format(language=language)}, {"role": "user", "content": user}]


def chat(messages, model=DEFAULT_MODEL, url=DEFAULT_URL, post=requests.post):
    r = post(f"{url.rstrip('/')}/api/chat", json={"model": model, "messages": messages, "stream": False,
                                                  "options": {"temperature": 0.6}}, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def generate(cv, job, language="English", notes="", model=DEFAULT_MODEL, url=DEFAULT_URL, post=requests.post):
    return chat(build_messages(cv, job, language, notes), model, url, post)


def status(url=DEFAULT_URL, get=requests.get):
    try:
        r = get(f"{url.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        return {"online": True, "models": [m["name"] for m in r.json().get("models", [])]}
    except Exception:
        return {"online": False, "models": []}


def to_docx(text):
    import docx
    from docx.shared import Pt
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    for para in [p.strip() for p in text.split("\n\n")]:
        if para:
            d.add_paragraph(para)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
