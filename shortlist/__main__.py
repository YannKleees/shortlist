import argparse
import os
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
    args = ap.parse_args(argv)

    import uvicorn

    from .server import create_app
    url = f"http://{args.host}:{args.port}"
    print(f"Shortlist running at {url}  (database: {os.path.abspath(args.db)})")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(args.db), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
