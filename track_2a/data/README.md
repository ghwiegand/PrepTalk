# Data provenance

PrepTalk uses the datasets from the [FHGR HackApertus challenge](https://github.com/fhgr/Hackapertus):
interview questions, answer annotations, candidate profiles, apprenticeship postings, scenarios,
rubric criteria, background documents and reference feedback.

FHGR licenses the material for HackApertus use. It is fetched separately and is not redistributed
in this repository. The Docker build pins the dataset repository to commit
`d8edb68f4944c0c2e70459f6cb00dcade3bc9efa` and copies the datasets into `/app/fhgr/datasets`.

For local execution, provide `track_2a/fhgr/datasets/` or set `FHGR_DATA` to another dataset directory.
The `fhgr/` directory is Git-ignored. Local challenge PDFs under `docs/challenge_docs/` are also ignored.

No new dataset is submitted. The small handwritten guard-evaluation cases live in
`evaluation/data/guard_cases.json`; deterministic test fixtures live in `tests/support/`.
Generated evaluation output belongs in the Git-ignored `runs/` directory.

The organizers cap a submitted `data/` directory at 100 MB. This directory contains documentation only.
