"""Pilot: evidence-driven coaching sequences (COACH_SEQUENCES=1).

Apertus does two narrow tasks: it extracts, per relevant answer, a claim, a situation, the applicant's own part and a
result (each with a short verbatim quote and a status), and it words the coaching action FrameX has chosen. FrameX
keeps the evidence of each topic, chooses the next coaching action from what is still missing, and at the end picks
one evidenced strength and one point to work on.

- A claim («Ich bin teamfähig») is stored as a claim, never as a strength. A described situation with the applicant's
  own part is the applicant's account of what they did; the feedback says so («Du hast geschildert, wie …»).
- «not_found» means no evidence in what was said, not missing ability.
- Every quote is checked verbatim against the answer it is said to come from; a quote that is not there turns the
  component into «unclear», and the correction is kept in the topic's history.
"""
import re

from . import content

COMPONENTS = ("situation", "own_part", "result")
STATUS = ("present", "not_found", "unclear")
# per question: which components a good answer needs (not every answer must contain all three)
TOPICS = {
    "Q-03-01": ("situation",),                         # why this occupation: an experience behind the choice
    "Q-05-01": ("situation", "own_part"),              # strengths: a situation that shows it, what you did
    "Q-06-07": ("situation", "own_part", "result"),    # trial apprenticeship: what happened, what you did, learnt
    "Q-07-01": ("situation", "own_part"),              # alone or team: a situation, your part in it
    "Q-OTH-12": ("situation", "own_part", "result"),   # follow-up talk after the trial apprenticeship
}
BUDGET_TOPIC = 2       # follow-ups per topic
BUDGET_INTERVIEW = 5   # follow-ups per interview (one-word personas would otherwise double the interview)

CHECK = {  # the criteria FrameX checks; the rules below decide them from the evidence, no model call
    "situation": "Evidence: a concrete situation the applicant experienced",
    "own_part": "Evidence: what the applicant did themselves in that situation",
    "result": "Evidence: the result or what the applicant learnt from it",
}
ACTION_TEXT = {  # the checked standard wording of each coaching action (fallback of the model's personalised one)
    "de": {"situation": "Erzähl mir von einer konkreten Situation, in der du das erlebt hast.",
           "own_part": "Was hast du in dieser Situation selbst gemacht?",
           "result": "Und was ist dabei herausgekommen, oder was hast du daraus gelernt?"},
    "fr": {"situation": "Raconte-moi une situation concrète où tu as vécu cela.",
           "own_part": "Qu'est-ce que tu as fait toi-même dans cette situation ?",
           "result": "Et qu'est-ce que ça a donné, ou qu'est-ce que tu en as appris ?"},
    "it": {"situation": "Raccontami una situazione concreta in cui l'hai vissuto.",
           "own_part": "Che cosa hai fatto tu in quella situazione?",
           "result": "E che cosa ne è venuto fuori, o che cosa hai imparato?"},
}
GOAL = {"situation": "a concrete situation they experienced themselves (when, where, what happened)",
        "own_part": "what they did themselves in the situation they described",
        "result": "what came out of it or what they learnt from it"}

EXTRACT = (
    "You read one answer a 14 to 16 year old gave in a practice job interview (question and answer below). Find, "
    "only in this answer: claim (a general statement about themselves, e.g. «I am a team player»), situation (a "
    "concrete situation they experienced: when, where, what happened), own_part (what they did themselves in it), "
    "result (what came out of it or what they learnt). For each give status present, not_found or unclear and a "
    "quote: at most 15 consecutive words copied character by character from the answer, in the answer's own "
    "language (German, French or Italian), never translated (empty if not_found). A claim is not a situation; a "
    "plan or wish is not a situation. If the situation sentence already says what they did themselves (e.g. "
    "«I organised …», «ich habe … organisiert»), that is also the own_part. Answer as JSON.")


def schema():
    item = {"type": "object", "properties": {"status": {"type": "string", "enum": list(STATUS)},
                                             "quote": {"type": "string", "maxLength": 160}},
            "required": ["status", "quote"], "additionalProperties": False}
    keys = ("claim",) + COMPONENTS
    return {"type": "object", "properties": {k: item for k in keys}, "required": list(keys),
            "additionalProperties": False}


def norm(text):
    return re.sub(r"\W+", " ", str(text or "").lower()).strip()


def verbatim(quote, answer):
    q = norm(quote)
    return len(q.split()) >= 2 and q in norm(answer)


def ground(quote, answer, min_share=0.4):
    """The sentence of the answer that shares the most words with the quote (at least min_share of the quote's
    words; for a translated quote names and numbers usually carry it), cut to 25 words; '' if none."""
    from .feedback import short
    qw = set(norm(quote).split())
    best, share = "", 0.0
    for sent in re.split(r"(?<=[.!?…;])\s+", answer or ""):
        sw = set(norm(sent).split())
        if qw and sw:
            sh = len(qw & sw) / len(qw)
            if sh > share:
                best, share = sent.strip(), sh
    return short(best, 25) if share >= min_share else ""


def checked(extraction, answer, ref):
    """The extraction after the verbatim rule: a quote that is not in the answer makes the item «unclear»."""
    out, corrections = {}, []
    for k in ("claim",) + COMPONENTS:
        item = extraction.get(k) if isinstance(extraction, dict) else None
        status = item.get("status") if isinstance(item, dict) else "unclear"
        quote = str(item.get("quote", "")).strip().strip("«»\"'") if isinstance(item, dict) else ""
        if status not in STATUS:
            status = "unclear"
        if status == "present" and not verbatim(quote, answer):
            # the model often translates or rephrases its quote: ground it in the answer sentence with the most
            # words in common (deterministic); if none shares enough, the component becomes «unclear»
            grounded = ground(quote, answer)
            corrections.append({"component": k, "was": quote, "now": grounded or "unclear",
                                "why": "quote not verbatim; grounded in the answer" if grounded else "quote not in the answer",
                                "ref": ref})
            if grounded:
                quote = grounded
            else:
                status, quote = "unclear", ""
        if status != "present":
            quote = ""
        out[k] = {"status": status, "quote": quote, "ref": ref}
    return out, corrections


def with_rules(extraction, answer, lang):
    """A situation or own part the extraction missed but the R1 rule finds counts as present (measured on 60
    labelled answers: extraction recall 0.83 / 0.78, rule recall 0.93; a missed component means a needless
    follow-up). The rule's quote is the answer sentence with the most concrete markers."""
    from . import feedback, rules
    out = dict(extraction)
    if out.get("situation", {}).get("status") != "present" and rules.concrete(answer, lang)[0]:
        out["situation"] = {"status": "present", "quote": feedback.best_sentence(answer, lang), "ref": extraction.get("situation", {}).get("ref"), "by": "rule"}
    if (out.get("own_part", {}).get("status") != "present" and out["situation"].get("status") == "present"
            and re.search(feedback.OWN[lang], answer, re.I)):
        sent = next((x for x in re.split(r"(?<=[.!?…;])\s+", answer) if re.search(feedback.OWN[lang], x, re.I)), "")
        out["own_part"] = {"status": "present", "quote": feedback.short(sent, 25), "ref": extraction.get("own_part", {}).get("ref"), "by": "rule"}
    return out


def merge(topic, extraction, answer_ref):
    """Add one answer's checked extraction to the topic: a component once present stays present (with the message
    it came from); every step is kept in the history."""
    topic.setdefault("history", []).append({"ref": answer_ref, "extraction": extraction})
    comp = topic.setdefault("components", {})
    for k in ("claim",) + COMPONENTS:
        new = extraction.get(k, {})
        old = comp.get(k)
        if new.get("status") == "present" and (not old or old.get("status") != "present"):
            comp[k] = new
        elif not old:
            comp[k] = new
        elif old.get("status") == "not_found" and new.get("status") == "unclear":
            comp[k] = new
    return topic


def missing(topic, needs):
    """The first relevant component without evidence (the next coaching action), or None."""
    comp = topic.get("components", {})
    return next((c for c in needs if comp.get(c, {}).get("status") != "present"), None)


def decide(topic, component, needs, total_followups):
    """FrameX's decision for one component check: (has evidence or move on?, reason)."""
    comp = topic.get("components", {})
    if comp.get(component, {}).get("status") == "present":
        return True, f"evidence: {component} present"
    if topic.get("followups", 0) >= BUDGET_TOPIC:
        return True, "move on: follow-up budget of the topic used"
    if total_followups >= BUDGET_INTERVIEW:
        return True, "move on: follow-up budget of the interview used"
    if component != missing(topic, needs):
        return True, "move on: an earlier component is still missing and was asked for"
    return False, f"evidence: {component} not found"


# ---- feedback from the evidence ---------------------------------------------------------------------------------
def select(topics, lang=None):
    """One evidenced strength and one point to work on, by explicit criteria.

    Strength: a topic with a described situation AND the applicant's own part (an account of what they did, not a
    claim); prefer topics that also have a result, then the main answer over follow-ups. No such topic: no strength.
    Point: in topic order, the first relevant component still missing after the coaching actions; a topic that has
    only a claim gives «a concrete situation» with the claim as quote. Everything present: the result of the
    strongest topic, if it is missing; otherwise no point from the evidence."""
    from . import feedback
    def admissible(item):  # self-devaluation and nervousness are never quoted as evidence (FHGR, restfehler R3)
        q = item.get("quote", "")
        return not re.search(feedback.SELF_DEPRECATION, q, re.I) and not re.search(feedback.INADMISSIBLE, q, re.I)
    topics = {n: dict(t, components={k: (v if admissible(v) else dict(v, status="unclear", quote=""))
                                     for k, v in t.get("components", {}).items()}) for n, t in topics.items()}
    strength, point = None, None
    ranked = []
    for name, t in topics.items():
        comp = t.get("components", {})
        if all(comp.get(c, {}).get("status") == "present" for c in ("situation", "own_part")):
            ranked.append((comp.get("result", {}).get("status") == "present", name, t))
    if ranked:
        ranked.sort(key=lambda x: (not x[0], list(topics).index(x[1])))
        _, name, t = ranked[0]
        comp = t["components"]
        strength = {"topic": name, "situation": comp["situation"]["quote"], "own_part": comp["own_part"]["quote"],
                    "result": comp.get("result", {}).get("quote", "")}
    for name, t in topics.items():
        gap = missing(t, TOPICS.get(t.get("qid"), COMPONENTS))
        if gap:
            claim = t.get("components", {}).get("claim", {})
            point = {"topic": name, "component": gap,
                     "quote": claim.get("quote", "") if gap == "situation" else t["components"].get("situation", {}).get("quote", "")}
            break
    return strength, point


ATTRIBUTION = (r",?\s*(was|das|und|which) (zeigt|beweist)\b.*$|,?\s*(ce qui (montre|prouve)|montrant|prouvant)\b.*$|"
               r",?\s*(dimostrando|il che dimostra|che dimostra|mostrando)\b.*$|,?\s*(zeigt|zeigst) (dass|deine|du)\b.*$")
POINT_TEXT = {"situation": "tell a concrete situation that shows what you claim",
              "own_part": "say more precisely what you did yourself",
              "result": "say what came out of it or what you learnt"}


def feedback_text(strength, point):
    """The selected observations for the feedback model (it words them; it must not choose other topics)."""
    lines = ["Observations FrameX selected from the interview (use exactly these, invent nothing):"]
    if strength:
        lines.append("- Strength (an account the applicant gave, not a proven ability): they described a situation "
                     f"«{strength['situation']}» and what they did «{strength['own_part']}»"
                     + (f" with the result «{strength['result']}»" if strength["result"] else "") + ". "
                     "Write it as «you described how you …», never as «you are …».")
    else:
        lines.append("- No evidenced strength: do not write a strength about abilities; strengths may only name "
                     "concrete things the applicant said and did.")
    if point:
        lines.append(f"- Point to work on: {POINT_TEXT[point['component']]}"
                     + (f" (their words: «{point['quote']}»)" if point["quote"] else "") + ".")
    lines.append("strengths: exactly this one (or none); improvements: exactly this one point first; next_step "
                 "practises it.")
    return "\n".join(lines)


def apply(data, strength, point, candidate_turns=None):
    """Rules: one strength (with its situation as quote) or none; the selected point first with its quote."""
    data = dict(data)
    if strength:
        st = dict((data.get("strengths") or [{}])[0])
        # an account of what they did, not an attributed ability: cut «…, was zeigt, dass du belastbar bist»
        st["text"] = re.sub(ATTRIBUTION, ".", str(st.get("text", "")), flags=re.I).strip()
        data["strengths"] = [dict(st, quote=strength["situation"])]
    else:
        data["strengths"] = []
    imps = [dict(i) for i in data.get("improvements") or []]
    if point:
        first = dict(imps[0]) if imps else {"text": "", "better": ""}
        if point["quote"]:
            first["quote"] = point["quote"]
        imps = [first] + imps[1:2]
    data["improvements"] = imps
    return data


def topic_of(question, plan, lang):
    """(qid, needs) if this main question opens a coaching sequence."""
    for qid, mode in plan:
        if mode == "story" and content.questions().get(qid, {}).get("text", {}).get(lang) == question:
            return qid, TOPICS.get(qid, COMPONENTS)
    return None
