"""Read menu choices from local FHGR data or its pinned public revision. No model calls."""

import json
from functools import lru_cache
import urllib.request

from preptalk.coach.content import DATA

FHGR_COMMIT = "d8edb68f4944c0c2e70459f6cb00dcade3bc9efa"
BASE_URL = f"https://raw.githubusercontent.com/fhgr/Hackapertus/{FHGR_COMMIT}/datasets"


def read_records(relative):
    path = DATA / relative
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(f"{BASE_URL}/{relative}", timeout=15) as response:
            text = response.read().decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@lru_cache(maxsize=1)
def load():
    postings = {p["id"]: p for p in read_records("profiles/postings.jsonl")}
    scenarios = {s["id"]: s for s in read_records("scenarios/scenarios.jsonl")}
    return {"posting": postings, "scenario": scenarios}
