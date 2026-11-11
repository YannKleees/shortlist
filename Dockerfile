# Shortlist web app. Ollama runs in its own container, see docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SHORTLIST_DB=/data/shortlist.db

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml README.md LICENSE ./
RUN mkdir shortlist && touch shortlist/__init__.py \
    && pip install . \
    && pip uninstall -y shortlist && rm -rf shortlist

COPY shortlist ./shortlist
COPY web ./web
RUN pip install --no-deps . \
    && useradd --create-home --uid 1000 app \
    && mkdir /data && chown app:app /data

USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "-m", "shortlist", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
