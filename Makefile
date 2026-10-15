.PHONY: run run-gpu stop chat eval report lint check

SCENARIOS ?= S-01 S-04 S-05
ARGS ?=

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
	python3 src/chat_client.py $(ARGS)

# Simulated interviews on FHGR scenarios (inside the container; simulator Gemini Flash, GOOGLE_API_KEY in .env).
eval:
	docker compose exec coach python -m eval.simulate $(SCENARIOS)

# Fast local checks; no services or model calls.
lint:
	ruff check src docs/make_figures.py

check: lint
	docker compose config --no-interpolate --quiet

# Typeset report (pdfLaTeX or Tectonic) -> NLP-Lab_Report.pdf; numbers in docs/report/report.tex and
# docs/report/consistency*.tex (written by python -m eval.consistency).
report:
	@if command -v pdflatex >/dev/null 2>&1; then \
		cd docs/report && pdflatex -interaction=nonstopmode -halt-on-error report.tex >/dev/null && pdflatex -interaction=nonstopmode -halt-on-error report.tex >/dev/null; \
	elif command -v tectonic >/dev/null 2>&1; then \
		cd docs/report && tectonic --keep-logs report.tex; \
	else \
		echo "Install pdfLaTeX or Tectonic to build the report." >&2; exit 1; \
	fi
	cp docs/report/report.pdf NLP-Lab_Report.pdf
