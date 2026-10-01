
.PHONY: install dev lint format typecheck test up migrate makemigration

# Install the project plus dev tooling in editable mode.
install:
	pip install -e ".[dev]"

# Run the dev server with hot reload.
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Lint the codebase.
lint:
	ruff check .

# Auto-format the codebase.
format:
	ruff format .

# Static type checking of the app package.
typecheck:
	mypy app

# Run the test suite.
test:
	pytest

# Start the full stack (db, redis, api, worker, beat, nginx) via Docker.
up:
	docker compose up --build

# Apply all pending database migrations up to the latest revision.
migrate:
	alembic upgrade head

# Create an empty migration to fill with raw SQL.
# Usage:  make makemigration m="add users table"
makemigration:
	alembic revision -m "$(m)"
