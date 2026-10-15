"""Run FHGR scenarios end to end: a simulator model plays the candidate, the coach (Apertus via
LLM_BASE_URL) interviews and gives feedback. The simulator is NOT Apertus and not part of the coach;
it only stands in for a teenager: Gemini Flash by default (GOOGLE_API_KEY; SIM_MODEL), or any OpenAI-compatible
server with SIM_PROVIDER=openai (SIM_BASE_URL / SIM_MODEL). SIM_HARD=1 adds two hard persona traits per scenario (one-word answers, typos,
digressions, written dialect, requests to slow down or explain, discouragement, a language switch), for robustness.

    python -m eval.simulate S-01 S-05 ...      results in runs/<scenario>.json
"""
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coach import content, session  # noqa: E402

SIM_URL = os.environ.get("SIM_BASE_URL", "http://localhost:8000/v1").rstrip("/") + "/chat/completions"
SIM_MODEL = os.environ.get("SIM_MODEL", "")
OUT = Path(os.environ.get("RUNS_DIR", "runs"))

SIM = ("Du spielst in einem Übungs-Vorstellungsgespräch die Bewerberin oder den Bewerber. Persona: {persona}\n"
       "Profil: {profile}\nAntworte immer nur mit dem, was du als diese Person jetzt sagst: kurz (1-4 Sätze), "
       "natürlich, in der Sprache des Gesprächs ({lang}){dialect}, ohne Regieanweisungen. Bleib in der Rolle.")


HARD = [
    "Antworte meistens nur mit einem bis drei Wörtern, ausser du wirst ausdrücklich um ein Beispiel gebeten.",
    "Schreib wie im Chat: viele Tippfehler, keine Grossschreibung, kaum Satzzeichen.",
    "Schweif oft vom Thema ab und erzähl von Dingen, nach denen nicht gefragt wurde (Hobbys, Familie, Ferien).",
    "Schreib so, wie du sprichst: in deinem Dialekt beziehungsweise sehr umgangssprachlich.",
    "Du verstehst nicht alles: bitte mindestens zweimal, die Frage einfacher oder langsamer zu wiederholen, und frag "
    "einmal, was ein Wort bedeutet.",
    "Du bist entmutigt: du hast schon viele Absagen und glaubst nicht, dass es klappt; sag das auch.",
    "Wechsle einmal mitten im Gespräch für einen Satz ins Englische.",
]


def hard_traits(scenario_id):
    """Two different hard traits per scenario, fixed (the same scenario always gets the same ones)."""
    seed = os.environ.get("SIM_SEED", "")  # another seed: other trait combinations (unused variants)
    h = int(hashlib.sha256((scenario_id + seed).encode()).hexdigest(), 16)
    first = h % len(HARD)
    second = (first + 1 + (h // len(HARD)) % (len(HARD) - 1)) % len(HARD)
    return [HARD[first], HARD[second]]


def simulate(messages, max_tokens=200):
    if os.environ.get("SIM_PROVIDER", "google") == "google":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"temperature": 0.9, "maxOutputTokens": 2000}}
        model = os.environ.get("SIM_MODEL", "gemini-flash-latest")
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                     data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", "x-goog-api-key": os.environ["GOOGLE_API_KEY"]})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    out = json.loads(resp.read())
                return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"]).strip()
            except Exception:  # noqa: BLE001 - rate limits: wait and retry
                time.sleep(10 * (attempt + 1))
        return "Ich weiss nicht."
    body = {"model": SIM_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7,
            "reasoning_effort": "none"}
    req = urllib.request.Request(SIM_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def run(scenario_id, max_turns=40):
    sc = content.scenarios()[scenario_id]
    cand = content.candidates()[sc["candidate_id"]]
    posting = content.postings()[sc["posting_id"]]
    ctx = content.context_from(posting=posting, candidate=cand, lang=sc["lang"], situation=sc["situation"],
                               planned=sc.get("planned_question_ids"))
    profile = {k: cand.get(k) for k in ("age", "school", "hobbies", "experiences", "strengths", "development_areas",
                                         "future_plans", "career_choice_story")}
    dialect = f", Dialekt {cand['dialect']} wenn passend" if sc.get("dialect_expected") else ""
    system = SIM.format(persona=cand.get("simulation_persona", ""), profile=json.dumps(profile, ensure_ascii=False),
                        lang=sc["lang"], dialect=dialect)
    if os.environ.get("SIM_HARD") == "1":
        system += "\nZusätzlich, für dieses Gespräch verbindlich:\n- " + "\n- ".join(hard_traits(sc["id"]))
    sim_messages = [{"role": "system", "content": system}]
    state, message, log, started = None, None, [], time.time()
    for _ in range(max_turns):
        s = session.Session(ctx, state)
        t = time.time()
        out = s.step(message)
        state = json.loads(json.dumps(s.state))
        coach_text = "\n\n".join(out)
        log.append({"speaker": "coach", "text": coach_text, "seconds": round(time.time() - t, 1)})
        if state["done"]:
            break
        sim_messages.append({"role": "user", "content": coach_text})
        message = simulate(sim_messages)
        sim_messages.append({"role": "assistant", "content": message})
        log.append({"speaker": "candidate", "text": message})
    result = {"scenario": sc["id"], "lang": sc["lang"], "situation": sc["situation"], "difficulty": sc.get("difficulty"),
              "context": ctx, "summary": session.summary(state), "seconds": round(time.time() - started),
              "log": log, "state": state}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{scenario_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


if __name__ == "__main__":
    for sid in sys.argv[1:]:
        r = run(sid)
        print(sid, r["lang"], r["summary"], f'{r["seconds"]}s', flush=True)
