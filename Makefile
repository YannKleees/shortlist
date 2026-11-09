# Common commands. On Windows, use start.bat or the commands in the README.

.PHONY: run test lint docker-up docker-gpu docker-down docker-logs backup

run:            ## start locally (creates .venv on first run)
	./start.sh

test:           ## all tests
	pytest -q && npm test

lint:
	ruff check .

docker-up:      ## app + Ollama in Docker, CPU
	docker compose up -d --build
	@echo "Open http://localhost:8000  (the first start downloads the model in the background)"

docker-gpu:     ## same, with an NVIDIA GPU for Ollama
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f shortlist ollama-pull

backup:         ## copy the database out of the Docker volume
	docker compose cp shortlist:/data/shortlist.db ./shortlist-backup-$$(date +%F).db
	@echo "Saved shortlist-backup-$$(date +%F).db"
