# PrepTalk

An Apertus-based coach for Swiss apprenticeship interviews in German, French and Italian.

**Hack Apertus 2026 · Track 2A — FHGR · Team NLP-Lab**

The submission project lives in [`track_2a/`](track_2a/), following the
[organizers' repository template](https://github.com/HackApertus/project-template).

## Quickstart: terminal demo

Install **Docker with Docker Compose v2** (Docker Desktop on macOS/Windows, or Docker Engine with
the Compose plugin on Linux), **Python 3.12+**, **Git** and **Make**. Start Docker before continuing.
The TUI uses only Python's standard library; `uv sync` is not needed for this demo.

1. Clone the repository and create the configuration on first setup (private-repository access is required):

   ```bash
   git clone https://github.com/ghwiegand/PrepTalk.git
   cd PrepTalk
   cp track_2a/.env.example track_2a/.env
   ```

2. Edit `track_2a/.env`: set `LLM_BASE_URL` to a running Apertus OpenAI-compatible endpoint ending
   in `/v1`, `LLM_NAME` to its served model name, and `LLM_API_KEY` if required. For a model running
   on the same computer outside Docker, the example uses `http://host.docker.internal:8000/v1`.
   **`make run` starts the coach API and databases; you must provide the model endpoint separately.**
   A remote endpoint lets you run the demo without a local GPU. For local NVIDIA inference, see
   [`make run-gpu`](track_2a/README.md#run-it).

3. Start the backend from the repository root and wait until the coach API is ready on port 2026
   (the first build downloads dependencies and challenge data):

   ```bash
   make run
   ```

4. In a second terminal, open the same repository directory and start the TUI:

   ```bash
   make chat
   # Optional: start with French selected
   make chat ARGS="--lang fr"
   ```

Use ↑/↓ to navigate, Space/Enter to open or confirm selections, then select **Start chat**.
Scenario and posting can stay unselected. Type an answer and press Enter to send it; Escape at
the text prompt offers a Yes/No confirmation to return to the menu. Empty input + Enter exits.
Run `make stop` to stop the backend. The menu and greeting can be previewed without the backend;
the first submitted answer needs the API and model endpoint.

Voice is optional and currently macOS-only: install **CMake** and **FFmpeg**, plus the macOS
command-line build tools, run `make voice-setup`, then choose **Voice (experimental)** in the menu.
See the [voice setup and controls](track_2a/README.md#run-it) for details.

## Repository contents

| Entry point | Contents |
| --- | --- |
| [Project README](track_2a/README.md) | Setup, API, architecture, testing and evaluation commands |
| [Technical report](track_2a/technical_report.md) | Approach, use of Apertus, results, limitations and reproducibility |
| [Makefile](track_2a/Makefile) | Docker startup and development commands |
| [Source code](track_2a/src/) | Interview engine, LangGraph API and terminal client |
| [Tests](track_2a/tests/) | Unit and integration suites using local fixtures |
| [Data notes](track_2a/data/README.md) | External FHGR datasets and their licence |
| [Architecture diagram](track_2a/docs/architecture.png) | Visual overview of the system |

```text
track_2a/
├── README.md
├── technical_report.md
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── aegra.json
├── pyproject.toml
├── uv.lock
├── src/
├── data/
├── tests/
├── evaluation/
└── docs/
```

Configure `track_2a/.env` from [the example](track_2a/.env.example), including the Apertus endpoint.
From the repository root:

```bash
make run          # start the Docker stack, API on http://localhost:2026
make chat         # main menu and terminal chat, in a second terminal
make check        # lint and validate Compose
make test-unit    # fast checks using only the Python standard library
make test-docker  # all tests, using the built coach image
make stop         # stop the stack, retaining database volumes
```

The root Makefile forwards commands to `track_2a/`. You can also `cd track_2a` and run them there.
Options still work, for example `make chat ARGS="--lang fr"`.
The menu selects a scenario, posting, language and mode; both presets default to none and Chat is
the default mode. Changing the
language translates the menu immediately. Use ↑/↓ to navigate and Space to open dropdowns.
Select **Start chat** at the bottom and press Enter; Escape quits the menu.
Experimental Voice mode runs locally on macOS. Its one-time setup is `make voice-setup`; then select
Voice in the menu. It uses local Whisper transcription and macOS speech playback, with no speech API credits.
See the [project README](track_2a/README.md) for prerequisites and recording controls.
For local Python dependency installation, run `uv sync --locked` inside `track_2a/`.

`make report` builds the six-page submission report at
[`track_2a/NLP-Lab_Report.pdf`](track_2a/NLP-Lab_Report.pdf) from the LaTeX sources.
The Markdown report above is the repository's required report entry point.

Code is licensed under [Apache 2.0](LICENSE). Project-authored documentation and the report are
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Third-party dependencies and FHGR reference material retain their own licences.
