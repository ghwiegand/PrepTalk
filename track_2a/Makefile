.PHONY: run run-gpu stop chat voice-setup eval report lint check test test-unit test-integration test-docker

SCENARIOS ?= S-01 S-04 S-05
ARGS ?=
PYTHON ?= python3
export PYTHONPATH := $(CURDIR)/src:$(CURDIR)$(if $(PYTHONPATH),:$(PYTHONPATH))

# Coach API (Aegra, port 2026) with PostgreSQL and Redis; Apertus is reached at LLM_BASE_URL (.env).
run:
	@test -f .env || cp .env.example .env
	docker compose up --build

# Same, plus Apertus 1.5 8B served by vLLM on a local NVIDIA GPU (sets LLM_BASE_URL accordingly).
run-gpu:
	@test -f .env || cp .env.example .env
	LLM_BASE_URL=http://apertus:8000/v1 docker compose --profile apertus up --build

stop:
	docker compose --profile apertus down

# Talk to the running coach in the terminal (needs Python 3 on the host, standard library only).
chat:
	@$(PYTHON) -m preptalk.cli $(ARGS)

# Optional local macOS voice tools/model; text chat needs none of these assets.
voice-setup:
	@$(PYTHON) -m preptalk.cli.voice_setup

# Simulated interviews on FHGR scenarios (inside the container; simulator Gemini Flash, GOOGLE_API_KEY in .env).
eval:
	docker compose exec coach python -m evaluation.simulate $(SCENARIOS)

# Fast local checks; no services or model calls.
lint:
	ruff check src tests evaluation docs/make_figures.py

check: lint
	docker compose config --no-interpolate --quiet

# All automated tests use local fixtures; no external model or running API is needed.
# Integration tests require the pinned FrameX binary and FHGR datasets (available in the Docker image).
test:
	$(PYTHON) -m unittest discover -s tests -t . -v

test-unit:
	$(PYTHON) -m unittest discover -s tests/unit -t . -v

test-integration:
	$(PYTHON) -m unittest discover -s tests/integration -t . -v

# Use the built coach image's Python dependencies, FrameX binary and challenge data.
test-docker:
	docker compose run --rm --no-deps --entrypoint python -v "$(CURDIR)/tests:/app/tests:ro" coach \
		-m unittest discover -s tests -t . -v

# Typeset report (pdfLaTeX or Tectonic) -> NLP-Lab_Report.pdf; numbers in docs/report/report.tex and
# docs/report/consistency*.tex (written by python -m evaluation.consistency).
report:
	@if command -v pdflatex >/dev/null 2>&1; then \
		cd docs/report && pdflatex -interaction=nonstopmode -halt-on-error report.tex >/dev/null && pdflatex -interaction=nonstopmode -halt-on-error report.tex >/dev/null; \
	elif command -v tectonic >/dev/null 2>&1; then \
		cd docs/report && tectonic --keep-logs report.tex; \
	else \
		echo "Install pdfLaTeX or Tectonic to build the report." >&2; exit 1; \
	fi
	cp docs/report/report.pdf NLP-Lab_Report.pdf
