"""LangGraph entry point served by Aegra (graph id "agent").

Input: the usual chat messages. Optionally, the first input can also set scenario_id, posting_id,
candidate_id, lang ("de" | "fr" | "it") and name, e.g. for a benchmark run. Without them the coach reads
language, apprenticeship and first name from the first message and asks for the apprenticeship if missing.
"""
import hashlib
import json
import re
import threading
from collections import OrderedDict
from typing import Annotated, Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from coach import content, rules, session, trace

LOCK = threading.Lock()  # FrameX's dialogue module keeps per-run globals: one turn at a time
# A harness may resend the whole conversation without the thread state (stateless runs). The coach's state is also
# kept under a hash of the conversation so far, so such a run continues the interview instead of starting anew.
RESUME: "OrderedDict[str, dict]" = OrderedDict()
RESUME_MAX = 5000


def conversation_key(messages) -> str:
    turns = [("ai" if isinstance(m, AIMessage) else "human", text_of(m).strip())
             for m in messages if isinstance(m, (AIMessage, HumanMessage))]
    return hashlib.sha256(json.dumps(turns, ensure_ascii=False).encode()).hexdigest()


class CoachState(BaseModel):
    messages: Annotated[list, add_messages] = []
    scenario_id: Optional[str] = None
    posting_id: Optional[str] = None
    candidate_id: Optional[str] = None
    lang: Optional[str] = None
    name: Optional[str] = None
    situation: Optional[str] = None
    voice: Optional[bool] = None  # spoken feedback (no table, short sentences) for text-to-speech
    context: Optional[dict[str, Any]] = None
    coach: Optional[dict[str, Any]] = None
    trace: Optional[list[dict[str, Any]]] = None  # decision trace (filled when the interview has ended)
    setup_asked: bool = False


ASK_JOB = {
    "de": "Hallo! Ich bin dein Interview-Coach und übe mit dir ein Vorstellungsgespräch für eine Lehrstelle. "
          "Für welche Lehre möchtest du üben, und wie heisst du?",
    "fr": "Bonjour ! Je suis ton coach d'entretien et je m'entraîne avec toi pour un entretien d'apprentissage. "
          "Pour quel apprentissage veux-tu t'entraîner, et comment t'appelles-tu ?",
    "it": "Ciao! Sono il tuo coach per i colloqui e mi esercito con te per un colloquio di tirocinio. "
          "Per quale tirocinio vuoi esercitarti e come ti chiami?",
}
SETUP = ("Extract from the message of a teenager who wants to practise an apprenticeship interview: lang (the "
         "language of the message: de, fr or it; Swiss German counts as de), occupation (the apprenticeship they "
         "name, or null), name (their first name, or null). Answer as JSON "
         '{"lang": "...", "occupation": "..." | null, "name": "..." | null}.')
WORDS = {"fr": {"je", "bonjour", "suis", "pour", "est", "le", "la", "et", "mon", "merci", "apprentissage"},
         "it": {"ciao", "sono", "io", "per", "il", "che", "e", "mi", "buongiorno", "grazie", "tirocinio"},
         "de": {"ich", "hallo", "bin", "für", "und", "die", "der", "das", "grüezi", "lehre", "möchte", "isch"}}

# The first message is in English and nothing fixes the language: the interview languages are de, fr and it (FHGR).
# Said once; if the next message is English again, the interview starts as before (a harness must never get stuck).
LANGUAGES = ("PrepTalk übt Bewerbungsgespräche auf Deutsch, Französisch oder Italienisch. Für welche Lehre möchtest du "
             "üben, und wie heisst du?\n\nPrepTalk s'entraîne en allemand, en français ou en italien. Pour quel "
             "apprentissage veux-tu t'entraîner, et comment t'appelles-tu ?\n\nPrepTalk si allena in tedesco, francese o "
             "italiano. Per quale tirocinio vuoi esercitarti e come ti chiami?\n\n"
             "(PrepTalk practises Swiss apprenticeship interviews in German, French or Italian; English is not offered.)")


def text_of(message) -> str:
    c = message.content
    if isinstance(c, list):
        return " ".join(part.get("text", "") for part in c if isinstance(part, dict))
    return str(c)


def clean(value) -> Optional[str]:
    """A model's "null", "none", "unknown" or empty string means: not given."""
    if not isinstance(value, str) or value.strip().lower() in ("", "null", "none", "unknown", "n/a", "-"):
        return None
    return value.strip()


def guess_lang(text: str) -> str:
    words = set(re.findall(r"\w+", text.lower()))
    best = max(WORDS, key=lambda lang: len(words & WORDS[lang]))
    return best if words & WORDS[best] else "de"  # nothing to go by: German, the most frequent language


SITUATIONS = [("phone_call_trial", r"telefon|anruf|anrufen|\bappel\b|appeler|téléphon|telefonat|chiamat"),
              ("online_interview", r"online|video|zoom|teams|en ligne|in linea"),
              ("follow_up_interview", r"nachgespräch|nach der schnupper|après (le|mon) stage|dopo lo stage"),
              ("trial_interview", r"schnupperlehre beginn|erster schnuppertag|début du stage|inizio dello stage"),
              ("assessment", r"assessment|gruppenarbeit|travail de groupe|lavoro di gruppo")]


def detect_situation(text: str) -> str:
    for situation, pattern in SITUATIONS:
        if re.search(pattern, text, re.I):
            return situation
    return "apprenticeship_interview"


def setup_from(state: CoachState, text: str) -> Optional[dict]:
    """The interview context from explicit fields or from the candidate's message (one model call)."""
    ids = re.findall(r"\b([SPC])-(\d{2})\b", text)  # «S-04», «P-11», «C-03» in a harness message
    for kind, number in ids:
        field = {"S": "scenario_id", "P": "posting_id", "C": "candidate_id"}[kind]
        if getattr(state, field) is None:
            setattr(state, field, f"{kind}-{number}")
    if state.scenario_id and state.scenario_id in content.scenarios():
        sc = content.scenarios()[state.scenario_id]
        return content.context_from(posting=content.postings()[sc["posting_id"]],
                                    candidate=content.candidates()[sc["candidate_id"]], lang=state.lang or sc["lang"],
                                    name=state.name, situation=state.situation or sc["situation"],
                                    planned=sc.get("planned_question_ids"))
    candidate = content.candidates().get(state.candidate_id or "")
    posting = content.postings().get(state.posting_id or "") or (
        content.postings().get(candidate["target_posting_id"]) if candidate else None)
    planned = re.findall(r"\bQ-[A-Z0-9]+-\d{2}\b", text)  # planned questions named in a harness message
    if posting:
        return content.context_from(posting=posting, candidate=candidate, lang=state.lang, name=state.name,
                                    situation=state.situation or detect_situation(text), planned=planned)
    lang, occupation, name = state.lang or guess_lang(text), None, state.name
    if text.strip():
        try:
            out = json.loads(re.search(r"\{.*\}", session.chat(
                [{"role": "system", "content": SETUP}, {"role": "user", "content": text}], 80), re.S).group(0))
            lang = state.lang or (out.get("lang") if out.get("lang") in content.LANGS else lang)
            occupation, name = clean(out.get("occupation")), name or clean(out.get("name"))
        except Exception:  # noqa: BLE001 - fall back to asking
            pass
    situation = state.situation or detect_situation(text)
    if not occupation:
        return {"lang": lang, "name": name, "incomplete": True, "situation": situation}
    posting = content.find_posting(occupation)
    if posting and occupation.lower()[:5] in str(posting["occupation"]).lower():
        return content.context_from(posting=posting, lang=lang, name=name, situation=situation)
    return content.context_from(lang=lang, name=name, occupation=occupation, situation=situation)


def coach(state: CoachState):
    human = [m for m in state.messages if isinstance(m, HumanMessage)]
    text = text_of(human[-1]) if human else ""
    # a harness may describe the scenario in a system message or in the first message: read both for the setup
    system = " ".join(text_of(m) for m in state.messages if isinstance(m, SystemMessage))
    with LOCK:
        if state.context is None and state.coach is None and any(isinstance(m, AIMessage) for m in state.messages):
            saved = RESUME.get(conversation_key(state.messages[:-1] if human and state.messages[-1] is human[-1]
                                                else state.messages))
            if saved:
                state.context, state.coach, state.setup_asked = saved["context"], saved["coach"], saved["setup_asked"]
        ctx, started = state.context, False
        explicit = state.lang or state.scenario_id or state.posting_id or state.candidate_id \
            or re.search(r"\b[SPC]-\d{2}\b", f"{system} {text}")
        noted = any(isinstance(m, AIMessage) and text_of(m) == LANGUAGES for m in state.messages)
        if (ctx is None or ctx.get("incomplete")) and not explicit and not noted and rules.english(text):
            reply = AIMessage(content=LANGUAGES)
            remember(state.messages + [reply], ctx, None, state.setup_asked)
            return {"messages": [reply]}
        if ctx is None or ctx.get("incomplete"):
            ctx = setup_from(state, f"{system} {text}".strip())
            if ctx.get("incomplete"):
                if state.setup_asked:  # asked once already: practise for a general apprenticeship
                    ctx = content.context_from(lang=ctx["lang"], name=ctx.get("name"), occupation="",
                                               situation=ctx.get("situation"))
                else:
                    reply = AIMessage(content=ASK_JOB[ctx["lang"]])
                    remember(state.messages + [reply], ctx, None, True)
                    return {"messages": [reply], "context": ctx, "setup_asked": True}
            started = True
        if state.voice is not None:
            ctx = dict(ctx, voice=bool(state.voice))
        s = session.Session(ctx, state.coach)
        reply = s.step(None if started else text)
    message = AIMessage(content="\n\n".join(reply))
    with LOCK:
        remember(state.messages + [message], ctx, s.state, state.setup_asked)
    out = {"messages": [message], "context": ctx, "coach": s.state}
    if s.state.get("done"):
        out["trace"] = trace.rows(s.state)
    return out


def remember(messages, ctx, coach_state, setup_asked):
    RESUME[conversation_key(messages)] = {"context": ctx, "coach": json.loads(json.dumps(coach_state)),
                                          "setup_asked": setup_asked}
    while len(RESUME) > RESUME_MAX:
        RESUME.popitem(last=False)


def create_graph():
    builder = StateGraph(CoachState)
    builder.add_node("coach", coach)
    builder.add_edge(START, "coach")
    builder.add_edge("coach", END)
    return builder.compile()


graph = create_graph()
