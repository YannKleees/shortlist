# Shortlist

A job search app that keeps everything in one place. Save a job from any link, or let your family send you links from their phone. Shortlist tells you how well each job fits and why: the field, the level, remote or hybrid, how far it is from home, the salary, the languages and your CV. It watches your job inbox to see where you applied and who answered, reminds you to follow up, and writes motivation letters with a local LLM in their own tab.

Everything runs on your laptop. No account, no cloud database. The only hosted part is a small free page on GitHub Pages that helpers use to send you links.

![Shortlist](docs/screenshot.png)

![Why a job fits: every reason with its points, salary and distance](docs/detail.png)

## Features

1. **Save from a link.** Paste a LinkedIn, Indeed or careers page link, or the whole text a phone app shares ("Check out this job at ..."). Shortlist reads the posting once and fills in company, role, location, salary, a short summary of the job and a description of the company. Pages that block apps, such as Indeed, are saved anyway with the company and role from the shared text; paste the description later in the job and everything updates.
2. **Why it fits.** Every job gets a score from 0 to 100 and one line per reason: field, level, work setup, distance from home, CV match and languages, each with its points. You see at a glance why a job is a top pick or a stretch.
3. **Distance from home.** Add your address in Settings. Places are looked up once on OpenStreetMap and cached; the job shows the straight line distance in km with a link to the route.
4. **Jobs from your family.** Settings gives you a link for helpers. They open it on their phone, add it to the home screen, and send any job in two taps: paste the link, press Send. On Android they can also share straight from the Indeed or LinkedIn app. The job arrives in your inbox and Shortlist adds it, with their name and message.
5. **Your mail does the bookkeeping.** Connect a Gmail inbox (read only). Mails you sent to a company mark the job as applied; confirmations, replies, interview invitations and rejections land on the timeline and update the status.
6. **Application status.** CV sent, applied on, they replied on, follow up date, deadline and next step. Marking a job as applied sets a follow up 10 days later; overdue follow ups move to the top of the list. Logging a follow up email, message or call moves the next reminder a week later.
7. **People.** For each job, keep the recruiters you wrote to, the hiring manager, and anyone you know there: role, how you know them, email, LinkedIn, last contact and notes.
8. **Timeline.** Log emails, messages, calls, replies, interviews, offers and rejections with a date. Logging a reply records the reply date, so the job stops counting as waiting.
9. **Motivation letters.** A local model through Ollama writes a draft in English, French, German or Dutch from your CV and the posting. It opens in its own tab next to the job summary and the reasons it fits. Edit it there, revise it with one click (shorter, more formal, more personal, fix grammar) or your own instruction, keep every version, and download it as TXT or Word.
10. **One file.** Jobs, people, timeline, CV, letters and settings live in `shortlist.db`, with a daily copy in `backups/` (the newest 14 are kept). Export everything as JSON, including people, timeline, letters and your CV text, and import it on another machine.

## Quick start

```bash
git clone https://github.com/YannKleees/shortlist.git
cd shortlist
./start.sh          # Windows: double click start.bat
```

The first run creates a virtual environment, installs everything, and copies `.env.example` to `.env`. The app opens at http://127.0.0.1:8000 and keeps its data in `shortlist.db` in the project folder. Options: `--db path/to/file.db`, `--port 8001`, `--no-browser`, `--no-backup`.

Prefer to manage Python yourself? `pip install -e .` and `python -m shortlist` do the same. In Chrome or Edge, use "Install app" in the address bar to get Shortlist in its own window with an icon.

### First setup

Open Settings and fill in, once:

1. **CV.** Upload it as PDF, DOCX, TXT or MD.
2. **You.** Your first name, home address and the languages you speak. Every score updates.
3. **Email.** A Gmail address for your job search and an app password. Turn on 2-Step Verification for that account, then create the app password at https://myaccount.google.com/apppasswords. Shortlist checks the inbox every 10 minutes while it runs (`--mail-every 0` turns that off), or when you click Check now.
4. **Helpers.** Type their name, click Copy link and send it to them, for example on WhatsApp.

### The helper page

The helper page is `docs/index.html`, served by GitHub Pages at `https://<you>.github.io/shortlist/`. It is a static page with no backend: it opens the helper's mail app with the link, their name and their message filled in, addressed to your job inbox. Your address is in the link you send, not in the page, and the page remembers it on their phone. It speaks English, German or French, following the phone's language. To host your own, enable GitHub Pages for the `docs` folder of your fork and set `SHORTLIST_HELPER_PAGE` to its address.

### With Docker

Docker runs the app and Ollama side by side, so you do not need Python or Ollama installed:

```bash
cp .env.example .env              # optional settings
docker compose up -d --build      # or: make docker-up
```

Open http://localhost:8000. On the first start, a one off `ollama-pull` container downloads the letter model (about 5 GB) into a volume; follow it with `docker compose logs -f ollama-pull`. With an NVIDIA GPU and the NVIDIA Container Toolkit, use the GPU override for much faster letters:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build   # or: make docker-gpu
```

| Volume | Holds |
|---|---|
| `shortlist-data` | `shortlist.db`: jobs, people, timeline, CV, letters, settings |
| `ollama-models` | downloaded models |

Both ports are bound to `127.0.0.1`, so nothing is reachable from your network. The app runs as a non-root user and has a health check. Back up the database with `make backup`, and change the model with `OLLAMA_MODEL=qwen2.5:7b docker compose up -d`.

For motivation letters, install [Ollama](https://ollama.com) and pull a model once:

```bash
ollama pull llama3.1:8b
```

You can switch the model in the app by clicking the model name in the header. Good options are `llama3.1:8b` for English and `qwen2.5:7b` or `mistral-nemo` for French and German. With a GPU, letters take a few seconds; on a laptop CPU, up to a minute.

## Reading LinkedIn and Indeed links

Neither LinkedIn nor Indeed offers a job API for individuals, and scraping them breaks their terms of service. Shortlist only reads the single public page you paste, once, when you save it. It reduces the link to the canonical posting URL (so the same job is never saved twice) and takes company, role, location and text from the page's structured data. For LinkedIn it uses the public job card, which needs no login. Indeed blocks apps completely, so Indeed jobs are saved from the shared text, and the job asks you to paste the description.

## How the fit score works

A rule based extractor reads seniority, minimum years, domain, work setup, job type and required languages from the job title and the posting. The title decides the level first, so "mentoring from senior data scientists" does not make an internship senior. Years only count next to the word experience, so "founded 150 years ago" is ignored, and a language only counts as required when the posting asks you to speak it and does not call it a plus. A TF-IDF similarity compares the posting with your CV. Together they give a score from 0 to 100, a fit label (Top pick, Good, Maybe, Stretch) and plain sentences for the pros and cons. With `ANTHROPIC_API_KEY` set and `pip install -e ".[claude]"`, Claude does the extraction instead through a forced tool call with a fixed JSON schema, which handles context like "Dutch is a plus".

| Component | Points | Highest when |
|---|---|---|
| Data science content | 35 | data science or ML work |
| Junior fit | 30 | internship, trainee, working student, 0 to 1 year |
| Work setup | 15 | hybrid |
| Distance | 10 | up to 20 km from home, or remote (without a home address: Luxembourg area or the Netherlands) |
| CV similarity | 10 | posting close to your CV |

Requiring a language you do not speak costs 15 points. Senior roles and 3 or more years of experience are capped at 35. Uploading a new CV, or changing your home or languages, updates every saved job; your own edits stay.

## Letters

Open a job, scroll to Motivation letter, click Open in new tab, choose the language and click Write draft. Edit the text directly and save, or use the Revise buttons: each revision becomes a new version, so you can always go back. The prompt gives the model your CV, the posting and the language, and tells it to use only facts from those two texts, write 250 to 350 words in four paragraphs, and avoid placeholders. Treat every draft as a draft: local models still make things up now and then, so read it before sending.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SHORTLIST_DB` | `shortlist.db` | database file |
| `SHORTLIST_BACKUPS` | `backups/` next to the database | folder for the daily database copies |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama address |
| `OLLAMA_MODEL` | `llama3.1:8b` | model for letters |
| `ANTHROPIC_API_KEY` | none | optional Claude extraction |
| `SHORTLIST_MAIL_MINUTES` | `10` | minutes between mail checks, 0 for by hand only |
| `SHORTLIST_HELPER_PAGE` | `https://yannkleees.github.io/shortlist/` | the helper page the Settings link points to |

Settings changed in the app are stored in the database and override the defaults.

## API

The web page uses a small JSON API that you can also script against. Interactive docs are at http://127.0.0.1:8000/docs.

| Method and path | Purpose |
|---|---|
| `GET /api/status` | CV and LLM status |
| `GET, POST /api/jobs` | list jobs or add one by hand |
| `POST /api/jobs/import-link` | save a job from a link or shared text; never fails on unreadable pages |
| `POST /api/jobs/{id}/text` | add the job description for a page that could not be read |
| `POST /api/mail/check` | read new jobs and application mails from your inbox |
| `PUT /api/settings` | home, languages, mail, model |
| `GET, PATCH, DELETE /api/jobs/{id}` | one job with its people, timeline and letters; update; delete |
| `POST /api/jobs/{id}/contacts`, `PATCH, DELETE /api/contacts/{id}` | people |
| `POST /api/jobs/{id}/events`, `DELETE /api/events/{id}` | timeline |
| `POST /api/cv` | upload your CV |
| `GET, POST /api/jobs/{id}/letters` | list or write letter drafts |
| `PUT /api/letters/{id}`, `POST /api/letters/{id}/revise`, `GET /api/letters/{id}/download` | edit, revise or download a letter |
| `POST /api/import/json`, `GET /api/export` | move everything between machines |

## Data model

| Table | Holds |
|---|---|
| `jobs` | posting, summary, company description, score and reasons, salary, distance, who sent it, status, CV sent, applied, replied, follow up and deadline dates |
| `contacts` | people per job: name, role, relation, email, LinkedIn, phone, last contact, notes |
| `events` | timeline per job: date, kind, text |
| `letters` | every letter version per job |
| `cv`, `settings` | your CV and app settings, including the mail app password |
| `places`, `mail_seen` | cached map lookups, and mails already turned into timeline entries |

Deleting a job deletes its people, timeline and letters. Older databases are migrated in place on start.

## Privacy

`shortlist.db`, backups, exports and CV files are in `.gitignore`. The server listens on `127.0.0.1` only. Letters are written locally by Ollama. The outgoing requests are the job page you paste, a Wikipedia lookup for the company description, OpenStreetMap lookups for your home and the job towns, your Gmail inbox over IMAP (read only, nothing is marked read, moved or deleted), and Claude if you set an API key. The Gmail app password is stored in `shortlist.db` on your laptop and is never shown again or exported; revoke it any time in your Google account.

## Limitations

1. Indeed, and sometimes LinkedIn, block apps. The job is still saved from the shared text; paste the description to complete it.
2. Helpers' jobs arrive when Shortlist runs and checks the inbox. Until then they wait safely in the mail.
3. The distance is a straight line, not the drive. The route link opens the real route.
4. The Wikipedia description only appears for companies with an article; otherwise write one line yourself.
5. Rule extraction misses nuance that the optional Claude extraction catches.
6. Local 7B and 8B models write decent first drafts, but you should always edit them.

## Tests

```bash
pip install -e ".[dev]"
pytest -q        # database, migration, CV parsing, link parsing, people, timeline, letters, scoring, API
npm test         # front end logic
ruff check .     # lint
```

GitHub Actions runs the linter, both test suites on Python 3.11 and 3.13, and builds and smoke tests the Docker image on every push.

## Project structure

```
shortlist/
  __main__.py     start the server
  server.py       FastAPI app and JSON API
  db.py           SQLite schema, migration and queries
  ingest.py       reading links and shared text; summaries; company descriptions
  mail.py         read only Gmail/IMAP: shared jobs, applications, replies
  geo.py          OpenStreetMap lookups and distance from home
  cvparse.py      text from PDF, DOCX, TXT, MD
  letters.py      Ollama letters and Word export
  extract.py      rule and Claude extraction, salary
  similarity.py   CV similarity
  score.py        score and the reasons behind it
  scoring.py      glue between extraction and scoring
web/              the app (Tailwind, vanilla JS); letter.html is the letter tab
docs/             the helper page for GitHub Pages, and the screenshots
tests/            pytest suite
examples/         example CV
start.sh, start.bat   one command setup and start
Dockerfile, docker-compose.yml, docker-compose.gpu.yml   containers for the app and Ollama
Makefile          shortcuts: run, test, lint, docker-up, docker-gpu, backup
.env.example      configuration template
```

## License

MIT
