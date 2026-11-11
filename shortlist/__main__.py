import argparse
import os
import threading
import time
import webbrowser

from . import NAME


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
    ap.add_argument("--sign-in-link", metavar="NAME", help="print a one time sign in link for this person, for example if you forgot your password")
    args = ap.parse_args(argv)
    if args.sign_in_link:
        return print_sign_in_link(args)

    import uvicorn

    from . import db
    from .server import create_app
    url = f"http://{args.host}:{args.port}"
    print(f"{NAME} running at {url}  (database: {os.path.abspath(args.db)})")
    if not args.no_backup:
        try:
            saved = db.backup(args.db, os.environ.get("SHORTLIST_BACKUPS"))
            if saved:
                print(f"Backup: {os.path.abspath(saved)}")
        except Exception as e:  # a failed backup must never stop the app
            print(f"Backup skipped: {e}")
    app = create_app(args.db)
    threading.Thread(target=watch, args=(app, args.mail_every), daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    # Behind a host such as Fly.io or a Tailscale/Cloudflare tunnel, trust its https headers so cookies are marked secure.
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=True, forwarded_allow_ips="*")


def print_sign_in_link(args):
    from . import db
    con = db.connect(args.db)
    user = db.user_by_name(con, args.sign_in_link)
    if not user:
        names = ", ".join(u["name"] for u in db.list_users(con)) or "nobody yet"
        print(f"No account called {args.sign_in_link!r}. Accounts: {names}")
        return 1
    base = os.environ.get("SHORTLIST_PUBLIC_URL", "").rstrip("/") or f"http://127.0.0.1:{args.port}"
    print(f"{base}/#/join/{db.new_invite(con, user['name'], user['role'], user_id=user['id'])}")
    print(f"Open it once within {db.INVITE_DAYS} days to sign in as {user['name']}, then set a new password under You.")
    return 0


def watch(app, minutes):
    # While the app runs: pick up jobs people mailed you and replies to your applications, and send the daily reminder.
    time.sleep(5)
    while True:
        if minutes > 0 and app.state.mail_ready():
            try:
                r = app.state.check_mail()
                if r.get("added") or r.get("applied") or r.get("replies"):
                    print(f"Mail: {r['added']} new jobs, {r['applied']} applications, {r['replies']} replies")
            except Exception as e:  # never let a mail problem stop the app
                print(f"Mail check failed: {e}")
        try:
            if time.localtime().tm_hour >= 8:
                app.state.daily()
        except Exception as e:
            print(f"Reminder failed: {e}")
        try:
            if 8 <= time.localtime().tm_hour < 22:  # no phone buzzing at night
                good = app.state.find()
                if good:
                    print(f"Find: {len(good)} new jobs that fit")
        except Exception as e:
            print(f"Job search failed: {e}")
        time.sleep(max(minutes, 10) * 60)


if __name__ == "__main__":
    main()
