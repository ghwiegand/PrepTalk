# PrepTalk

An Apertus-based coach for Swiss apprenticeship interviews in German, French and Italian.

**Hack Apertus 2026 · Track 2A — FHGR · Team NLP-Lab**

The submission project lives in [`track_2a/`](track_2a/), following the
[organizers' repository template](https://github.com/HackApertus/project-template).

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
The menu selects a scenario, posting and language; both presets default to none. Changing the
language translates the menu immediately. Use ↑/↓ to navigate and Space to open dropdowns.
Select **Start chat** at the bottom and press Enter; Escape quits the menu.
For local Python dependency installation, run `uv sync --locked` inside `track_2a/`.

`make report` builds `track_2a/NLP-Lab_Report.pdf` from the detailed LaTeX sources. The submission
form requires a PDF of at most six pages; the existing detailed report must still be shortened
before it is uploaded. The Markdown report above is the repository's required report entry point.

Code is licensed under [Apache 2.0](LICENSE). Project-authored documentation and the report are
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Third-party dependencies and FHGR reference material retain their own licences.
