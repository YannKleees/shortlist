"""Open Shortlist like an app: start the server quietly if it is not running yet, then open Shortlist in its own window.

    pythonw -m shortlist.launch               what the taskbar and Start menu icon run
    python -m shortlist.launch --shortcut     make that icon (Windows: Desktop and Start menu)

The server keeps running after the window closes, so your mail is still checked and notifications still arrive.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import NAME

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("SHORTLIST_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"


def running(url=URL):
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    exe = quiet if os.name == "nt" and quiet.exists() else exe
    flags = 0
    if os.name == "nt":  # no console window, and not closed together with this launcher
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    log = open(ROOT / "shortlist.log", "a", encoding="utf-8")  # noqa: SIM115, the server owns it from here
    subprocess.Popen([str(exe), "-m", "shortlist", "--no-browser", "--port", str(PORT)], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags, close_fds=True)


def app_browser():
    # Chrome or Edge can show a page as an app: its own window and taskbar icon, no tabs or address bar.
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    found = next((c for c in candidates if c and os.path.exists(c)), None)
    return found or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("msedge")


def sign_in_page(url=URL):
    # The icon on your own computer signs you in, so a forgotten password never locks you out.
    # The link works once and only for five minutes; if you are already signed in the page ignores it.
    try:
        from . import db
        con = db.connect(os.environ.get("SHORTLIST_DB", str(ROOT / "shortlist.db")))
        owner = next((u for u in db.list_users(con) if u["role"] == "owner"), None)
        if owner:
            return f"{url}/#/join/{db.new_invite(con, owner['name'], 'owner', user_id=owner['id'], minutes=5)}/auto"
    except Exception:  # the window must open anyway
        pass
    return f"{url}/"


def open_window(page=None):
    page = page or f"{URL}/"
    browser = app_browser()
    if browser:
        subprocess.Popen([browser, f"--app={page}"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(page)


def make_shortcut():
    if os.name != "nt":
        print(f"Shortcuts are made for Windows only. On a Mac, add {NAME} to the Dock from Chrome: Install page as app.")
        return 1
    quiet = Path(sys.executable).with_name("pythonw.exe")
    target = quiet if quiet.exists() else Path(sys.executable)
    icon = ROOT / "web" / "icons" / "app.ico"
    places = [Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs", desktop()]
    for folder in places:
        lnk = folder / f"{NAME}.lnk"
        old = folder / "Shortlist.lnk"  # the name the app had before
        if old.exists():
            old.unlink()
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SL_LNK); "
            "$s.TargetPath = $env:SL_TARGET; $s.Arguments = '-m shortlist.launch'; $s.WorkingDirectory = $env:SL_ROOT; "
            f"$s.IconLocation = $env:SL_ICON; $s.Description = '{NAME}: your job search'; $s.Save()"
        )
        env = {**os.environ, "SL_LNK": str(lnk), "SL_TARGET": str(target), "SL_ROOT": str(ROOT), "SL_ICON": str(icon)}
        subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True)
        print(f"Made {lnk}")
    print(f"To put it in the taskbar: open Start, find {NAME}, right click it and choose Pin to taskbar.")
    return 0


def desktop():
    # The Desktop may live in OneDrive.
    for d in (Path.home() / "OneDrive" / "Desktop", Path.home() / "Desktop"):
        if d.exists():
            return d
    return Path.home() / "Desktop"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--shortcut" in argv:
        return make_shortcut()
    os.chdir(ROOT)
    if not running():
        start_server()
        for _ in range(180):  # the first start after an update can take half a minute
            if running():
                break
            time.sleep(0.5)
    open_window(sign_in_page())
    return 0


if __name__ == "__main__":
    sys.exit(main())
