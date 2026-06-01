.DEFAULT_GOAL := help
VENV         := .venv
PYTHON       := $(VENV)/bin/python
PORT         ?= 7103
IMAGE_TAG    ?= aspose-ci-runner:latest

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  Dev"
	@echo "    run          Start the app (single worker, port $(PORT))"
	@echo "    run-reload   Start with --reload for development"
	@echo "    install      Create venv and install dependencies"
	@echo "    install-ci   Install CI-only dependencies (no sentence-transformers)"
	@echo ""
	@echo "  Quality"
	@echo "    lint         Run ruff linter"
	@echo "    lint-fix     Run ruff linter and auto-fix violations"
	@echo "    test         Run unit tests with coverage"
	@echo "    test-fast    Run unit tests without coverage"
	@echo "    check        lint + test (full quality gate)"
	@echo ""
	@echo "  Docker"
	@echo "    build-image  Build the CI Docker image (Dockerfile.ci)"
	@echo ""
	@echo "  Setup"
	@echo "    env          Copy .env.example → .env (first-time setup)"

# ── Dev ───────────────────────────────────────────────────────────────────────
.PHONY: run
run:
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT) --workers 1

.PHONY: run-reload
run-reload:
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT) --reload

.PHONY: install
install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt

.PHONY: install-ci
install-ci:
	$(VENV)/bin/pip install -r requirements-ci.txt

# ── Quality ───────────────────────────────────────────────────────────────────
.PHONY: lint
lint:
	$(PYTHON) -m ruff check .

.PHONY: lint-fix
lint-fix:
	$(PYTHON) -m ruff check . --fix

.PHONY: test
test:
	$(PYTHON) -m pytest tests/ -v --cov --cov-report=term-missing

.PHONY: test-fast
test-fast:
	$(PYTHON) -m pytest tests/ -q

.PHONY: check
check: lint test

# ── Docker ────────────────────────────────────────────────────────────────────
.PHONY: build-image
build-image:
	docker build -f Dockerfile.ci -t $(IMAGE_TAG) .

# ── Setup ─────────────────────────────────────────────────────────────────────
.PHONY: env
env:
	@if [ -f .env ]; then \
		echo ".env already exists — skipping. Delete it first to reset."; \
	else \
		cp .env.example .env; \
		echo ".env created from .env.example — fill in your secrets."; \
	fi
