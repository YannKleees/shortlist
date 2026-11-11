import io
import re
import unicodedata
import zipfile
from pathlib import Path

KINDS = (".pdf", ".docx", ".tex", ".md", ".txt")  # in the order a zip is searched


def extract_text(filename, data):
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace").strip()
    if ext == ".tex":
        return latex_text(data.decode("utf-8", errors="replace"))
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs if p.text).strip()
    if ext == ".zip":
        return _from_zip(data)
    raise ValueError("Upload your CV as PDF, Word, LaTeX, TXT or a zip with one of them.")


def _from_zip(data):
    # An Overleaf download: take the CV inside, a PDF first, else the main .tex file.
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This zip file cannot be opened.") from None
    files = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX") and i.file_size < 20_000_000]
    for kind in KINDS:
        found = [i for i in files if i.filename.lower().endswith(kind)]
        if kind == ".tex":
            found = [i for i in found if b"\\begin{document}" in z.read(i)] or found
        if found:
            pick = max(found, key=lambda i: i.file_size)
            return extract_text(pick.filename, z.read(pick))
    raise ValueError("There is no CV in this zip. Put a PDF, Word or .tex file in it.")


# LaTeX

ACCENTS = {"'": "́", "`": "̀", '"': "̈", "^": "̂", "~": "̃", "c": "̧"}
DROP = {"vspace", "hspace", "label", "input", "include", "newcommand", "renewcommand", "setlength", "addtolength",
        "usepackage", "documentclass", "pagestyle", "titleformat", "color", "fontsize", "vfill", "hfill", "newpage", "pagebreak"}
LINE = {"section", "subsection", "section*", "subsection*"}
ONE = {"textbf", "textit", "emph", "underline", "texttt", "textsc", "textrm", "textsf", "mbox", "url", "uline", "hbox"}
SWITCH = {"small", "footnotesize", "scriptsize", "tiny", "normalsize", "large", "Large", "LARGE", "huge", "Huge", "scshape",
          "bfseries", "itshape", "centering", "raggedright", "noindent", "par", "linebreak", "newline", "titlerule", "hline"}


def _args(s, i, most=99):
    """Read {..} and [..] arguments from position i; returns (list of {} args, new position)."""
    out = []
    while len(out) < most:
        j = i
        while j < len(s) and s[j] in " \t\r\n":
            j += 1
        if j < len(s) and s[j] == "[":
            k = s.find("]", j)
            if k < 0:
                break
            i = k + 1
            continue
        if j < len(s) and s[j] == "{":
            depth, k = 0, j
            while k < len(s):
                depth += {"{": 1, "}": -1}.get(s[k], 0)
                if depth == 0:
                    break
                k += 1
            out.append(s[j + 1:k])
            i = k + 1
            continue
        return out, i
    return out, i


def _plain(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 < len(s) and s[i + 1] == "\\":  # a line break
            out.append("\n")
            i += 2
            continue
        if i + 1 < len(s) and s[i + 1] in ACCENTS and not (s[i + 1] == "c" and s[i + 2:i + 3].isalpha()):
            m = re.match(r"\{?(\w)\}?", s[i + 2:])
            if m:
                out.append(unicodedata.normalize("NFC", m.group(1) + ACCENTS[s[i + 1]]))
                i += 2 + m.end()
                continue
        m = re.match(r"[A-Za-z]+\*?", s[i + 1:])
        if not m:  # \& \% \$ \# \_ and friends
            out.append(s[i + 1:i + 2])
            i += 2
            continue
        name = m.group(0)
        if name in SWITCH:
            i += 1 + m.end()
            out.append("\n" if name in ("par", "linebreak", "newline") else "")
            continue
        args, i = _args(s, i + 1 + m.end(), 1 if name in ONE else 99)
        if name in DROP or name in ("begin", "end"):
            continue
        if name == "href" and len(args) == 2:  # keep the address, so the CV check sees your LinkedIn link
            label, url = _plain(args[1]).strip(), args[0].strip()
            out.append(label if url.startswith("mailto:") or url in label else f"{label} ({url})")
        elif name in LINE:
            out.append("\n\n" + " ".join(_plain(a) for a in args).upper() + "\n")
        elif name == "item" or name.endswith("Item"):
            out.append("\n- " + " ".join(_plain(a) for a in args))
        elif len(args) >= 2:
            out.append("\n" + " | ".join(_plain(a).strip() for a in args if a.strip()))
        else:
            out.append(" ".join(_plain(a) for a in args))
    return "".join(out)


def latex_text(src):
    """The readable text of a LaTeX CV, without needing LaTeX installed."""
    body = src.split("\\begin{document}", 1)[-1].split("\\end{document}", 1)[0]
    body = re.sub(r"(?<!\\)%.*", "", body)
    body = re.sub(r"\$([^$]*)\$", r"\1", body.replace("$|$", "|"))
    text = _plain(body).replace("---", "—").replace("--", "–").replace("~", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" {}") for ln in text.replace("{", "").replace("}", "").splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln != "-"))
    return re.sub(r"\n\n(?=- )", "\n", text).strip()
