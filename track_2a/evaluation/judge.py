"""LLM-as-judge for simulated interviews (development only; the official benchmark is the organisers').

The judge is a model that is NOT part of the coach: Claude Opus 5.5 by default (JUDGE_PROVIDER=anthropic,
ANTHROPIC_API_KEY), Gemini Pro as a second judge of another family (JUDGE_PROVIDER=google, GOOGLE_API_KEY), or any
OpenAI-compatible server (JUDGE_PROVIDER=openai, JUDGE_BASE_URL / JUDGE_MODEL). It checks the
scenario's success_criteria_for_coach and rates five aspects from 1 to 5.

    python -m evaluation.judge runs/S-01.json runs/S-04.json ...   -> runs/judged.json and a table
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from preptalk.coach import content

URL = os.environ.get("JUDGE_BASE_URL", "http://localhost:8000/v1").rstrip("/") + "/chat/completions"
MODEL = os.environ.get("JUDGE_MODEL", "")
ASPECTS = ["realism", "adaptivity", "feedback_quality", "age_appropriateness", "language_consistency"]

PROMPT = """You evaluate an AI job-interview coach for Swiss apprenticeship applicants (14-16 years old).
The coach first plays the interviewer, then gives feedback on 11 criteria.

Scenario: {title}
Interview language: {lang}

Check each statement about the coach's behaviour with yes or no, based only on the transcript:
{criteria}

Then rate from 1 (poor) to 5 (excellent):
- realism: natural, realistic interview for this apprenticeship and company
- adaptivity: follows up on vague answers, reacts to what the candidate said
- feedback_quality: feedback is based on evidence from the conversation, criteria-based, concrete next step
- age_appropriateness: encouraging, simple language, no judgements about the person
- language_consistency: stays in the interview language, consistent form of address

Answer as JSON: {{"checks": [{{"statement": "...", "met": true|false, "reason": "..."}}], {aspects}}}

Transcript:
{transcript}"""


PROVIDER = os.environ.get("JUDGE_PROVIDER", "anthropic")


def ask_frontier(prompt, temperature=0, tries=6):
    """One judgement from Anthropic's or Google's API; returns the reply text. Overload and rate limits: wait, retry."""
    for attempt in range(tries):
        try:
            return _ask_frontier(prompt, temperature)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 529) or attempt == tries - 1:
                raise
            time.sleep(20 * (attempt + 1))


def _ask_frontier(prompt, temperature=0):
    if PROVIDER == "anthropic":
        body = {"model": os.environ.get("JUDGE_MODEL", "claude-opus-5-5"), "max_tokens": 8000,
                "messages": [{"role": "user", "content": prompt + "\n\nReply with the JSON object only."}]}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                     headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "content-type": "application/json",
                                              "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(resp.read())
        return "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")
    model = os.environ.get("JUDGE_MODEL", "gemini-pro-latest")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "x-goog-api-key": os.environ["GOOGLE_API_KEY"]})
    with urllib.request.urlopen(req, timeout=600) as resp:
        out = json.loads(resp.read())
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])


def ask(prompt, tries=3, temperature=0):
    if PROVIDER in ("anthropic", "google"):
        for attempt in range(tries):
            text = ask_frontier(prompt, temperature)
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except ValueError:
                    pass
        raise ValueError("judge reply was not JSON")
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": temperature,
            "max_tokens": 1500, "reasoning_effort": "none", "response_format": {"type": "json_object"}}
    for attempt in range(tries):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            text = json.loads(resp.read())["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", match.group(0)))  # tolerate trailing commas
            except ValueError:
                pass
        body["temperature"] = 0.2  # a different sample on the next try
    raise ValueError("judge reply was not JSON")


def judge(run):
    sc = content.scenarios()[run["scenario"]]
    transcript = "\n".join(f'{"COACH" if t["speaker"] == "coach" else "CANDIDATE"}: {t["text"]}' for t in run["log"])
    prompt = PROMPT.format(title=sc["title"], lang=run["lang"],
                           criteria="\n".join(f"- {c}" for c in sc["success_criteria_for_coach"]),
                           aspects=", ".join(f'"{a}": 1-5' for a in ASPECTS), transcript=transcript)
    best, want = None, len(sc["success_criteria_for_coach"])
    for attempt in range(5):  # an incomplete judgement (broken quote, missing ratings) is asked again; the most
        out = ask(prompt, temperature=0.2 * attempt)  # complete one counts
        score = (min(len(out.get("checks", [])), want), sum(out.get(a) is not None for a in ASPECTS))
        if best is None or score > best[0]:
            best = (score, out)
        if score == (want, len(ASPECTS)):
            break
    out = best[1]
    checks = out.get("checks", [])
    return {"scenario": run["scenario"], "lang": run["lang"], "difficulty": run.get("difficulty"),
            "checks_met": sum(1 for c in checks if c.get("met") is True), "checks_total": len(checks),
            **{a: out.get(a) for a in ASPECTS}, "calls_per_answer": run["summary"]["calls_per_answer"],
            "status": run["summary"]["status"], "checks": checks}


if __name__ == "__main__":
    results = [judge(json.loads(Path(p).read_text())) for p in sys.argv[1:]]
    Path(os.environ.get("RUNS_DIR", "runs"), "judged.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("| scenario | lang | checks | " + " | ".join(ASPECTS) + " | calls/answer | status |")
    for r in results:
        print(f'| {r["scenario"]} | {r["lang"]} | {r["checks_met"]}/{r["checks_total"]} | '
              + " | ".join(str(r[a]) for a in ASPECTS) + f' | {r["calls_per_answer"]} | {r["status"]} |')
