import argparse
import os
import threading
import time
import webbrowser


def load_env(path=".env"):
    # KEY=value lines; values already set in the environment win.
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="shortlist", description="Personal job application tracker.")
    ap.add_argument("--db", default=os.environ.get("SHORTLIST_DB", "shortlist.db"), help="SQLite database file")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-backup", action="store_true", help="skip the daily copy of the database in backups/")
    ap.add_argument("--mail-every", type=int, default=int(os.environ.get("SHORTLIST_MAIL_MINUTES", "10")),
                    help="minutes between mail checks while the app runs, 0 to only check by hand")
    args = ap.parse_args(argv)

    import uvicorn

    from . import db
    from .server import create_app
    url = f"http://{args.host}:{args.port}"
    print(f"Shortlist running at {url}  (database: {os.path.abspath(args.db)})")
    if not args.no_backup:
        try:
            saved = db.backup(args.db, os.environ.get("SHORTLIST_BACKUPS"))
            if saved:
                print(f"Backup: {os.path.abspath(saved)}")
        except Exception as e:  # a failed backup must never stop the app
            print(f"Backup skipped: {e}")
    app = create_app(args.db)
    if args.mail_every > 0:
        threading.Thread(target=watch_mail, args=(app, args.mail_every), daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def watch_mail(app, minutes):
    # Pick up jobs people mailed you, and replies to your applications, while the app is open.
    time.sleep(5)
    while True:
        if app.state.mail_ready():
            try:
                r = app.state.check_mail()
                if r.get("added") or r.get("applied") or r.get("replies"):
                    print(f"Mail: {r['added']} new jobs, {r['applied']} applications, {r['replies']} replies")
            except Exception as e:  # never let a mail problem stop the app
                print(f"Mail check failed: {e}")
        time.sleep(minutes * 60)


if __name__ == "__main__":
    main()
