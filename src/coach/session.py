"""One interview, driven turn by turn: FrameX decides, Apertus phrases and judges.

FrameX re-derives the whole flow from its receipts, so a session is just the list of tool
results so far. Each candidate message replays that list (no model calls), feeds the new answer
to the pending question, and runs live until the flow needs the candidate again. The session
state is plain JSON and lives in the LangGraph checkpoint.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from framex import dialogue, tools  # FrameX core: https://gitlab.com/ds-unisg/framex-core

from . import content, feedback, rules
from . import evidence as ev

FRAMEX_BINARY = os.environ.get("FRAMEX_BINARY", "framex")  # the engine binary (built in the Docker image)
MAX_TOKENS_FEEDBACK = int(os.environ.get("COACH_FEEDBACK_TOKENS", "1800"))
TIMEOUT_FEEDBACK = int(os.environ.get("COACH_FEEDBACK_TIMEOUT", "600"))


def configure_model():
    """Map the HackApertus variables (LLM_NAME, LLM_BASE_URL, LLM_API_KEY) onto FrameX's."""
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    os.environ.setdefault("LLM_API_KEY", "none")  # local servers need no key, FrameX needs the variable
    parts = urllib.parse.urlsplit(base)
    if parts.scheme == "http":  # FrameX admits plain HTTP only to loopback or this one named model host
        os.environ["FRAMEX_MODEL_HTTP_HOST"] = parts.hostname or ""
    os.environ.update({
        "FRAMEX_MODEL_PROVIDER": "openai",
        "FRAMEX_MODEL_ENDPOINT": base + "/chat/completions",
        "FRAMEX_MODEL": os.environ.get("LLM_NAME", "swiss-ai/Apertus-v1.5-8B"),
        "FRAMEX_MODEL_KEY_ENV": "LLM_API_KEY",
        "FRAMEX_MODEL_TEMPERATURE": os.environ.get("LLM_TEMPERATURE", "0"),
        "FRAMEX_MODEL_MAX_TOKENS": os.environ.get("LLM_MAX_TOKENS", "400"),
        "FRAMEX_MODEL_CACHE": os.environ.get("FRAMEX_MODEL_CACHE", "/tmp/coach-model-cache"),
        "FRAMEX_MODEL_TIMEOUT": os.environ.get("LLM_TIMEOUT", "120"),  # short calls; a timeout falls back by rule
        "FRAMEX_MODEL_JSON_EXTRACT": "1",  # servers without json_schema: take the JSON object after leading text
    })


configure_model()

# Every live model call is counted, for the "< 5 LLM calls per candidate answer" requirement.
CALLS = {"n": 0}
_model_live = tools.model_live


SCHEMA_FALLBACKS = {"n": 0}
SCHEMA_FAILED = set()  # reply schemas this server rejected; only these are sent without schema from then on
# A model call that fails (broken JSON, timeout, connection) never stops the interview: each caller has a rule
# fallback (neutral acknowledgement, fixed follow-up, free-text feedback, an honest «I will find out»).
MODEL_ERRORS = (tools.ToolResponseError, ValueError, KeyError, TimeoutError, OSError)


def _without_schema(parameters, provider):
    """One call with json_object instead of json_schema (the schema still checks the reply)."""
    old = os.environ.get("FRAMEX_MODEL_SCHEMA")
    os.environ["FRAMEX_MODEL_SCHEMA"] = "0"
    try:
        return _model_live(parameters, provider)
    finally:
        if old is None:
            os.environ.pop("FRAMEX_MODEL_SCHEMA", None)
        else:
            os.environ["FRAMEX_MODEL_SCHEMA"] = old


def _counted_model_live(parameters, provider):
    """Counted model call. If a call with a reply schema gets a server error (a server may answer 422 or 500 to
    json_schema; 400 is retried by FrameX), it is repeated once without the schema (json_object). Only when that retry succeeds was the schema the problem:
    then this one schema is remembered and sent without schema from then on. Other schemas, other conversations
    and a server that is merely slow or overloaded keep constrained decoding."""
    CALLS["n"] += 1
    schema = parameters.get("schema")
    key = json.dumps(schema, sort_keys=True) if isinstance(schema, dict) else None
    if key in SCHEMA_FAILED or os.environ.get("FRAMEX_MODEL_SCHEMA") == "0":
        return _without_schema(parameters, provider)
    try:
        result = _model_live(parameters, provider)
    except TimeoutError:  # a slow server says nothing about schema support
        raise
    except Exception as exc:
        # only a server error on the request (FrameX handles 400 itself) can mean the schema is unsupported; an
        # unreadable or cut-off reply is the model's, and the caller's rule fallback handles it without a retry
        if key is None or getattr(exc, "status", None) not in (422, 500, 501):
            raise
        CALLS["n"] += 1
        result = _without_schema(parameters, provider)
        SCHEMA_FAILED.add(key)
        SCHEMA_FALLBACKS["n"] += 1
        return result
    envelope = result[1] if isinstance(result, tuple) and len(result) == 2 else None
    if key and isinstance(envelope, dict) and "fallback" in str(envelope.get("response_format", "")):
        # FrameX already asked again with json_object after a 400: that was a second request, and this schema
        # goes without constraint from now on (one request instead of two)
        CALLS["n"] += 1
        SCHEMA_FAILED.add(key)
        SCHEMA_FALLBACKS["n"] += 1
    return result


tools.model_live = _counted_model_live


def chat(messages, max_tokens, timeout=None):
    """A plain-text chat completion (feedback, answers as the company); counted like the others."""
    CALLS["n"] += 1
    body = {"model": os.environ["FRAMEX_MODEL"], "messages": messages, "max_tokens": max_tokens,
            "temperature": float(os.environ["FRAMEX_MODEL_TEMPERATURE"])}
    req = urllib.request.Request(os.environ["FRAMEX_MODEL_ENDPOINT"], data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + os.environ["LLM_API_KEY"]})
    with urllib.request.urlopen(req, timeout=timeout or int(os.environ["FRAMEX_MODEL_TIMEOUT"])) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def structured(request, max_tokens, timeout):
    """One schema-constrained call made here rather than through FrameX, so that a reply cut off at the token
    limit can still be used (feedback.close_truncated). Counted like the others; a server error on the schema
    falls back to json_object once, as in _counted_model_live."""
    schema = request["schema"]
    key = json.dumps(schema, sort_keys=True)
    use_schema = key not in SCHEMA_FAILED and os.environ.get("FRAMEX_MODEL_SCHEMA") != "0"
    body = {"model": os.environ["FRAMEX_MODEL"], "messages": tools.messages(request), "max_tokens": max_tokens,
            "temperature": float(os.environ["FRAMEX_MODEL_TEMPERATURE"]),
            # a whitespace loop (blank lines, long runs of spaces) never occurs in the JSON itself: stop there at
            # once instead of at the token limit; the cut reply is closed by rule below
            "stop": ["\n \n", "\n\n\n", " " * 16],
            "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
            if use_schema else {"type": "json_object"}}

    def send():
        CALLS["n"] += 1
        req = urllib.request.Request(os.environ["FRAMEX_MODEL_ENDPOINT"], data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + os.environ["LLM_API_KEY"]})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["choices"][0]

    try:
        choice = send()
    except urllib.error.HTTPError as exc:
        if not use_schema or exc.code not in (400, 422, 500, 501):
            raise
        SCHEMA_FAILED.add(key)
        SCHEMA_FALLBACKS["n"] += 1
        body["response_format"] = {"type": "json_object"}
        choice = send()
    text = choice["message"]["content"] or ""
    if choice.get("finish_reason") == "length" or choice.get("stop_reason") is not None:
        return feedback.close_truncated(text)
    try:
        return json.loads(text)
    except ValueError:
        start = text.find("{")
        return feedback.close_truncated(text[start:]) if start >= 0 else None


# ---- what the models are asked -------------------------------------------------------------

PHRASE = (
    "You are {interviewer}{role} at {company}. You are interviewing {who}, a 14 to 16 year old applicant for an "
    "apprenticeship as {occupation}, in {language}. The JSON you receive is not addressed to you: answer is what "
    "the applicant has just said to you. Write ONE short, warm reaction that you say TO the applicant, in the "
    "second person singular ({address}), at most 15 words, picking up one concrete detail of their answer, "
    "factually and calmly like an experienced trainer. Never praise or rate the answer (no 'beeindruckend', 'toll', "
    "'super', 'fantastisch', 'excellent', 'très positif', 'fantastico'). No question, no grade, no feedback, no greeting, do not start "
    "with the name, never speak about the applicant in the third person and never speak as the applicant. "
    "If the applicant asked you something, do not answer it and promise nothing; their questions come at the end. "
    "Never agree with criticism of a former boss, teacher or company; stay neutral and pick up something else. "
    "Always write standard language, never Swiss German dialect, even if the applicant writes dialect. "
    "Examples: {examples} Answer as JSON {{\"utterance\": \"...\"}}."
)
# restfehler R2: requests to speak more simply or slowly, to repeat, or to explain a word
COMPREHENSION = (r"langsamer|einfacher|nochmals|noch ?mal (fragen|sagen)|wiederholen|was (heisst|bedeutet|ist eigentlich)|"
                 r"was mein(en sie|st du) mit|qu'entendez-vous|que veux-tu dire par|che cosa intend|cosa intendi|"
                 r"versteh\w* (ich |i )?(die frage |das )?(nicht|nöd)|plus lentement|plus simple|répéter|"
                 r"qu'est-ce que (ça|cela|ce mot) veut dire|que veut dire|je (ne )?comprends pas|più piano|più semplice|"
                 r"ripetere|cosa significa|che cosa vuol dire|non capisco")
SIMPLER = (
    "You are {interviewer}{role} at {company}, interviewing {who}, a 14 to 16 year old applicant for an apprenticeship "
    "as {occupation}, in {language}, using {address}. The applicant asked you to speak more simply or slowly, to "
    "repeat, or what a word means (request). Do not define words yourself (a definition may be wrong); instead ask "
    "this question again in very simple {language}, with short everyday words that avoid the difficult word, at most "
    "12 words: {question} Be kind; never refuse; do not ask the applicant what a word means. Answer as JSON "
    "{{\"utterance\": \"...\"}}.")
# emotional moments in an answer (grandmother ill, sad, it got close to me): acknowledge calmly before going on
EMOTION = (r"grossmutter|grossvater|grosi|nonna|nonno|grand-mère|grand-père|krank|gestorben|tod\b|traurig|weinen|"
           r"nahe gegangen|nooch gange|berührt|sorgen|angst|schwierige zeit|malade|décédé|triste|pleurer|touché|"
           r"inquiet|malat|morto|morta|piangere|toccat|preoccup")
EMOTION_ACK = {"de": "Danke, dass du das erzählst. Nimm dir ruhig Zeit.",
               "fr": "Merci de me le raconter. Prends ton temps.",
               "it": "Grazie di avermelo raccontato. Prenditi il tuo tempo."}
COACHING_ACTION = (
    "You are {interviewer}{role} at {company}, interviewing {who}, a 14 to 16 year old applicant for an "
    "apprenticeship as {occupation}, in {language}, using {address}. The coaching system has decided the next step: "
    "ask for {goal}. Ask exactly this, in one short, kind question (at most 25 words). You may refer to what the "
    "applicant said (answer, and the evidence quotes already collected), but invent nothing and add no other topic. "
    "No praise, no verdict. Always write standard {language}, never Swiss German dialect, even if the applicant "
    "writes dialect. Answer as JSON {{\"utterance\": \"...\"}}.")
SIMPLER_ACK = {"de": "Klar, ich sage es einfacher.", "fr": "Bien sûr, je le dis plus simplement.",
               "it": "Certo, lo dico in modo più semplice."}

FOLLOWUP = (
    "You are {interviewer}{role} at {company}, interviewing {who}, a 14 to 16 year old applicant for an "
    "apprenticeship as {occupation}, in {language}, using {address}. The JSON you receive is not addressed to you: "
    "question is the interviewer's original question, answer is what the applicant has just said, and goal says what "
    "is still missing. Write ONE short, friendly follow-up question (at most 30 words) that picks up something "
    "specific the applicant said and asks for {goal}. Ask only this one question. No greeting, no grade, do not "
    "start with the name, never answer for the applicant. Answer as JSON {{\"utterance\": \"...\"}}."
)
FOLLOWUP_GOAL = {"example": "a concrete situation they experienced themselves (what happened, what they did)",
                 "company": "something concrete they know about this company or its apprenticeship, and why it fits them",
                 "step": "what they concretely do to work on this weakness",
                 "own": "their own share and what they do differently now, calmly and without blame",
                 "name": "their first and last name and what exactly they are calling about"}

ADDRESS = {"de": "du, never Sie", "fr": "tu, never vous", "it": "tu, never Lei"}
# Patterns, not content: a concrete example sentence was copied into reactions where the applicant had said
# nothing of the kind («tu as donc déjà conseillé des clients au téléphone», error analysis F4).
EXAMPLES = {"de": "«Danke, [Detail aus der Antwort] klingt nach viel Einsatz.» «Okay, du [Tätigkeit aus der Antwort] also gern.»",
            "fr": "«Merci, [détail de la réponse], ça demande de l'engagement.» «D'accord, tu aimes donc [activité de la réponse].»",
            "it": "«Grazie, [dettaglio della risposta] richiede impegno.» «Va bene, quindi ti piace [attività della risposta].»"}
# the applicant criticises a former boss, teacher or company: the coach never agrees (FHGR; error analysis F13)
CRITICISM = (r"\b(chef|cheffin|lehrmeister|lehrer|lehrerin|betrieb|firma|vorgesetzt\w*|patron|patronne|ancien|ancienne|"
             r"prof|entreprise|capo|ex|professore|professoressa|azienda|datore)\b.{0,60}\b(nul|nulle|schlecht|unfair|"
             r"ungerecht|blöd|doof|mies|gemein|nervig|injuste|mauvais|méchant|pas sympa|horrible|pessimo|ingiusto|"
             r"cattivo|antipatico|insopportabile)\b|contrairement à (mon|ma) (ancien|ancienne)|"
             r"im gegensatz zu (meinem|meiner) (alten|früheren)|a differenza del mio (vecchio|ex)")
FORBIDDEN = {"de": r"\b(Sie|Ihnen|Ihr|Ihre)\b", "fr": r"\b(vous|votre|vos)\b", "it": r"\b(Lei|Sua|Suo)\b"}
FIRST_PERSON_AS_APPLICANT = r"\b(mon profil|mes expériences|meine Erfahrungen|il mio profilo)\b"
# Swiss German in the coach's own words (it speaks standard German; the applicant may write dialect)
DIALECT = (r"\b(isch|gsi|hesch|nöd|nüt|öppis|scho|hälft|händ|gfallt|mer|dä|de Plan|chasch|wotsch|gärn|gmacht|gbackt|"
           r"bim|un|e konkrete|wo du .{0,20}hesch|hani|gsit|öpper|eifach|mega)\b")
# a reaction must not answer or promise (the company answers questions at the end)
PROMISE = r"\b(du kannst|kannst du|du darfst|wir bieten|bei uns|tu pourras|tu peux|potrai|puoi)\b"


ENGLISH = r"\b(you|your|could|would|the|please|example)\b"
# words of the other two languages: a reaction or follow-up in the wrong language is replaced by the rules
OTHER_LANG = {"de": r"\b(tu|est|les|avec|pour|très|che|sei|hai|della|molto)\b",
              "fr": r"\b(hast|bist|das|und|ich|nicht|che|sei|hai|della|molto)\b",
              "it": r"\b(hast|bist|das|und|ich|nicht|est|les|avec|pour|très)\b"}


REQUEST = r"^(erzähl|erzähle|beschreib|beschreibe|sag|nenn|nenne|raconte|décris|dis-moi|donne|racconta|raccontami|descrivi|dimmi)\b"


def acceptable_action(text, context):
    """A coaching action may be a question or a request («Erzähl mir von …»); otherwise the reask rules apply:
    interview language and address, not English, at most one question, at most 35 words, no praise."""
    request = bool(re.search(REQUEST, text, re.I))
    return (("?" in text or request) and text.count("?") <= 1 and len(text.split()) <= 35
            and not re.search(FORBIDDEN[context["lang"]], text) and not re.search(ENGLISH, text, re.I)
            and not re.search(OTHER_LANG[context["lang"]], text, re.I) and not re.search(PRAISE, text, re.I)
            and not (context["lang"] == "de" and re.search(DIALECT, text, re.I)))


def acceptable_reask(text, context):
    """A follow-up from attempt 2 on: a question, in the interview language and address, not too long."""
    return ("?" in text and len(text.split()) <= 45 and not re.search(FORBIDDEN[context["lang"]], text)
            and not re.search(ENGLISH, text, re.I) and not re.search(OTHER_LANG[context["lang"]], text, re.I)
            and not (context["lang"] == "de" and re.search(DIALECT, text, re.I)))


def copies_example(text, lang):
    """Whether a reaction repeats six or more consecutive words of the prompt's own examples: the model then
    states something the applicant never said («tu as donc déjà conseillé des clients au téléphone»)."""
    words = re.findall(r"\w+", EXAMPLES[lang].lower())
    grams = {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}
    said = re.findall(r"\w+", text.lower())
    return any(" ".join(said[i:i + 6]) in grams for i in range(len(said) - 5))


# praise and verdicts in reactions: a real trainer stays neutral (frontier judges: «praises nearly every answer»)
PRAISE = (r"beeindruck|\btoll\b|\bsuper\b|fantastisch|grossartig|großartig|wunderbar|hervorragend|ausgezeichnet|"
          r"perfekt|lobenswert|sehr gut|\bstark\b|bravo|\bklasse\b|\bwow\b|"
          r"impressionn|génial|formidable|excellent|parfait|très bien|bravo|"
          r"fantastic|ottim|eccellent|bravissim|stupend|perfett|impressionant|"
          # verdicts on the answer (restfehler R4): «c'est un bon point», «tu as bien compris», «das zeigt …»
          r"bon point|bien compris|bien identifié|bien expliqué|bien réfléchi|richtig erkannt|gut erkannt|gut verstanden|"
          r"hast du gut|ist wichtig|das ist gut|gute idee|guter punkt|gute eigenschaft|das zeigt|zeigt, dass|ben capito|"
          r"hai capito|buon punto|è importante|questo dimostra|dimostra che|cela montre|ça montre")


def acceptable(reaction, context):
    """The rules a reaction must meet; otherwise a neutral acknowledgement is used (model proposes, rules decide)."""
    words = reaction.split()
    name = context.get("name") or ""
    return (0 < len(words) <= 25 and "?" not in reaction
            and not re.search(FORBIDDEN[context["lang"]], reaction)
            and not re.search(FIRST_PERSON_AS_APPLICANT, reaction, re.I)
            and not re.search(DIALECT, reaction, re.I) and not re.search(PROMISE, reaction, re.I)
            and not re.search(OTHER_LANG[context["lang"]], reaction, re.I)
            and not copies_example(reaction, context["lang"])
            and not re.search(PRAISE, reaction, re.I)
            and not (name and reaction.lower().startswith(name.lower())))


REASK = (
    "You are {interviewer}{role} at {company}, interviewing {who}, a 14 to 16 year old applicant for an "
    "apprenticeship as {occupation}, in {language}, using {address}. The JSON you receive is not addressed to you: "
    "question is what you asked, missing says why the answer was not enough yet, conversation is the interview "
    "so far. In one or two short, kind sentences, ask only for what is missing, without repeating what the "
    "applicant already said. No greeting, do not start with the name, never answer for the applicant. Answer as "
    "JSON {{\"utterance\": \"...\"}}."
)

COMPANY = (
    "You are {interviewer}{role} at {company}. In a job interview for an apprenticeship as {occupation}, "
    "the applicant (14 to 16 years old) asks you something. Answer as the company, warmly and briefly (2 to 4 "
    "sentences), in {language}, addressing the applicant with {address}. Use only these facts about the company "
    "and the apprenticeship; if they do not contain the answer, say honestly that you will find out and get "
    "back to them. If the applicant asked no question, just say warmly that you are glad and that this is fine. "
    "Facts: {facts}"
)

DONE = {"de": "Das Übungsgespräch ist abgeschlossen. Starte eine neue Unterhaltung, um nochmals zu üben.",
        "fr": "L'entretien d'entraînement est terminé. Commence une nouvelle conversation pour t'entraîner encore.",
        "it": "Il colloquio di esercitazione è concluso. Inizia una nuova conversazione per esercitarti ancora."}
SORRY = {"de": "Entschuldige, hier ist etwas schiefgelaufen. Lass uns das Gespräch neu starten.",
         "fr": "Désolé, quelque chose n'a pas fonctionné. Recommençons l'entretien.",
         "it": "Scusa, qualcosa è andato storto. Ricominciamo il colloquio."}

COMPANY_FALLBACK = {"de": "Gute Frage – das kläre ich ab und sage es dir später.",
                    "fr": "Bonne question – je me renseigne et je te le dis plus tard.",
                    "it": "Bella domanda – mi informo e te lo dico più tardi."}

FEEDBACK = (
    "Du bist ein erfahrener, freundlicher Berufsberater, der angehende Lernende beim Üben von "
    "Vorstellungsgesprächen unterstützt. Bewerte das soeben geführte Übungsgespräch ({situation}) für eine Lehre "
    "als {occupation}. Nutze ausschliesslich das Gesagte aus dem Gespräch, erfinde nichts hinzu.\n\n"
    "Kriterien:\n{criteria}\n\n"
    "Stufen: {levels}. Pro Kriterium: eine konkrete Stelle aus dem Gespräch als Beleg (Zitat oder Paraphrase), "
    "dann die Stufe. Bewerte nie ohne Beleg; ohne Aussage schreibe «{none}».\n\n"
    "Umgangsregeln (die Person ist jugendlich): wertschätzend und ermutigend, nie herablassend oder ironisch; "
    "einfache, klare Sprache, kurze Sätze; sprich die Person überall direkt in der du-Form an («du hast …»), "
    "auch bei den Stärken – schreibe nie «{name} hat …» oder «er/sie hat …»; "
    "nur das gezeigte Verhalten, keine Charakterzuschreibungen oder Diagnosen; «noch nicht» statt «nicht»; "
    "Nervosität, Versprecher, Pausen, Rechtschreibung, Dialekt und Sprachniveau nie negativ bewerten; keine "
    "Vergleiche mit anderen; keine Angst erzeugen (etwa wegen Noten oder Absenzen).\n\n"
    "Ausgabe ganz in {language}, genau in diesem Aufbau:\n"
    "**{h1}**: zwei bis drei Sätze, beginnend mit dem, was dir gut gelungen ist.\n"
    "**{h2}**: eine Tabelle mit den Spalten {cols}, eine Zeile pro Kriterium.\n"
    "**{h3}**: zwei kurze Punkte, jeweils mit deinem Beleg.\n"
    "**{h5}**: höchstens zwei Punkte. Für einen davon: zitiere eine allgemeine oder schwache Formulierung der Person "
    "und zeige eine stärkere Version, die ihr eigenes Erlebnis aus dem Gespräch nutzt. Wenn im Gespräch ein schwieriges "
    "Thema vorkam (Absenzen, Noten, Abbruch, Lücke, Fehler), gib dazu das Antwortmuster: ehrlich benennen – "
    "Verantwortung übernehmen – zeigen, was du gelernt oder geändert hast, mit einem Beleg.{extra}\n"
    "**{h4}**: genau ein konkreter Übungsauftrag für das nächste Mal.\n"
    "Schliesse mit einem ermutigenden Satz, der betont, dass es ein Übungsgespräch war und Üben hilft."
)
EXTRA = {"online_interview": " Gib bei einem Punkt einen Tipp für Online-Gespräche (Kamera, Ton, Notizen, Hintergrund).",
         "assessment": " Beziehe dich auch auf die Präsentation und die Rolle in der Gruppenarbeit.",
         "follow_up_interview": " Beziehe dich auch darauf, wie die Person die Schnupperlehre reflektiert."}
SITUATION_NAME = {"apprenticeship_interview": "Vorstellungsgespräch", "online_interview": "Online-Vorstellungsgespräch",
                  "trial_interview": "Gespräch zu Beginn einer Schnupperlehre", "follow_up_interview":
                  "Nachgespräch nach der Schnupperlehre", "assessment": "Assessment mit Präsentation und Gruppenarbeit",
                  "phone_call_trial": "Anruf für eine Schnupperlehre"}


class NeedInput(BaseException):
    """The flow waits for the candidate. A BaseException, so FrameX's tool runner does not turn it
    into a failure receipt but lets it end this run."""


class Session:
    def __init__(self, context, state=None):
        self.context = context
        self.state = state or {"record": [], "pending": None, "done": False, "calls": 0, "answers": 0}
        self.program = content.program(context)

    def progress(self):
        """Main-question progress, independent of how many answers or follow-ups were needed."""
        total = len(content.plan(self.context))
        step = self.state.get("current_step", "")
        match = re.fullmatch(r"q(\d+)(more|f\d+)?", step)
        current = int(match[1]) if match else None
        completed = current - 1 if current else total if step == "askQuestions" else 0
        phase = "questions" if step == "askQuestions" else "interview"
        if self.state.get("done"):
            status = self.state.get("status")
            if status == "completed":
                completed, phase = total, "completed"
            else:
                phase = "early_feedback" if status == "feedback on request" else "ended"
        return {"total": total, "completed": completed, "current": current,
                "phase": phase, "follow_up": bool(match and match[2])}

    # ---- the channel FrameX's dialogue tools talk to ----
    class Channel(dialogue.Channel):
        def __init__(self, session):
            super().__init__()
            self.session, self.answer_text, self.out = session, None, []

        def say(self, text, live=True):
            if self.session.context.get("lang") == "de":
                text = text.replace("ß", "ss")  # Swiss Standard German
            self.transcript.append({"speaker": "bot", "text": text})
            if live:
                self.session.reply.append(text)

        def answer(self):
            if self.answer_text is None:
                raise NeedInput()
            text, self.answer_text = self.answer_text, None
            self.transcript.append({"speaker": "user", "text": text})
            return text

    def _coaching_action(self, action, standard, transcript, names):
        """Pilot: Apertus words exactly the coaching action FrameX chose; it may only refer to what the applicant
        said (the evidence of this topic); the checked standard wording is the fallback."""
        c = self.context
        topic = self._topics().get(self.state.get("current_topic"), {})
        known = {k: v["quote"] for k, v in topic.get("components", {}).items() if v.get("status") == "present"}
        prompt = COACHING_ACTION.format(goal=ev.GOAL[action], **names)
        fields = {"answer": transcript[-1]["text"], "evidence": known}
        try:
            phrased, envelope = tools.model({"prompt": prompt, **fields, "schema": dialogue.UTTERANCE_SCHEMA})
        except MODEL_ERRORS:
            phrased, envelope = {}, {"mode": "model unavailable"}
        text = phrased.get("utterance") if isinstance(phrased, dict) else phrased if isinstance(phrased, str) else None
        if isinstance(text, str) and acceptable_action(text.strip(), c):
            return text.strip(), None, dict(envelope or {}, action=action)
        return standard, None, {"mode": "standard wording (model reply broke a rule)", "action": action}

    def _simpler(self, question, request, names):
        """The question again in simple words, after a short explanation if a word was asked about."""
        c = self.context
        terms = rules.glossary_terms(request, c["lang"])
        prompt = SIMPLER.format(question=question, **names)
        try:
            phrased, evidence = tools.model({"prompt": prompt, "request": request, "schema": dialogue.UTTERANCE_SCHEMA})
        except MODEL_ERRORS:
            phrased, evidence = {}, {"mode": "model unavailable"}
        text = phrased.get("utterance") if isinstance(phrased, dict) else phrased if isinstance(phrased, str) else None
        if not (isinstance(text, str) and acceptable_reask(text.strip(), c) and len(text.split()) <= 25
                and not re.search(r"nicht langsamer|pas plus lentement|non più piano", text, re.I)
                and not re.search(r"\b(bedeutet|heisst|signifie|veut dire|significa|vuol dire)\b", text, re.I)):
            text, evidence = f"{SIMPLER_ACK[c['lang']]} {question}", {"mode": "fixed (model reply broke a rule)"}
        return " ".join(terms + [text.strip()]), None, evidence

    def _phrase(self, parameters):
        """Attempt 1: a short reaction to the last answer (model) + the FHGR question as written, so every
        interview asks the planned questions. From attempt 2 on: the model asks for what is missing."""
        c = self.context
        names = dict(interviewer=c["interviewer"], company=c["company"],
                     role=f' ({c["interviewer_role"]})' if c.get("interviewer_role") else "",
                     who=c["name"] or "the applicant", occupation=c.get("occupation") or "an apprenticeship",
                     language=content.LANG_NAME[c["lang"]], address=ADDRESS[c["lang"]],
                     examples=EXAMPLES[c["lang"]])
        transcript = dialogue.CHANNEL.transcript
        last_user = transcript[-1]["text"] if transcript and transcript[-1]["speaker"] == "user" else ""
        if last_user and re.search(COMPREHENSION, last_user, re.I):
            # restfehler R2: a request to speak simply or to explain a word comes on top of the answer; the next
            # question is asked in simple words, terms of the training system from the glossary
            return self._simpler(parameters["question"], last_user, names)
        followup = next((k for k in FOLLOWUP_GOAL if parameters["question"] == content.TEXT[c["lang"]].get(k)), None)
        action = next((k for k, v in ev.ACTION_TEXT[c["lang"]].items() if v == parameters["question"]), None)
        if parameters["attempt"] == 1 and action and transcript and transcript[-1]["speaker"] == "user":
            return self._coaching_action(action, parameters["question"], transcript, names)
        if parameters["attempt"] == 1 and followup and transcript and transcript[-1]["speaker"] == "user":
            # a follow-up that picks up the answer (one call, replacing the reaction); rules check it below
            asked = next((t["text"] for t in reversed(transcript) if t["speaker"] == "bot"), "")
            prompt = FOLLOWUP.format(goal=FOLLOWUP_GOAL[followup], **names)
            fields = {"question": asked, "answer": transcript[-1]["text"], "goal": FOLLOWUP_GOAL[followup]}
            try:
                phrased, evidence = tools.model({"prompt": prompt, **fields, "schema": dialogue.UTTERANCE_SCHEMA})
            except tools.ToolResponseError as exc:
                phrased, evidence = {}, dict(exc.evidence or {})
            except MODEL_ERRORS:
                phrased, evidence = {}, {"mode": "model unavailable"}
            if isinstance(phrased, str):
                phrased = {"utterance": phrased}
            text = phrased.get("utterance") if isinstance(phrased, dict) else None
            if isinstance(text, str) and acceptable_reask(text.strip(), c) and len(text.split()) <= 35:
                return text.strip(), None, evidence
            return parameters["question"], None, {"mode": "fixed follow-up (model reply broke a rule)"}
        if parameters["attempt"] == 1:
            last = transcript[-1]["text"] if transcript and transcript[-1]["speaker"] == "user" else None
            if not last:
                return parameters["question"], None, {"mode": "as written; no model"}
            prompt, fields = PHRASE.format(**names), {"answer": last}
        else:
            prompt = REASK.format(**names)
            fields = {"question": parameters["question"], "conversation": dialogue.conversation()[-6:]}
            missing = parameters.get("missing")
            if isinstance(missing, str) and not re.search(r"json|format|reply|verdict", missing, re.I):
                fields["missing"] = missing  # never pass a technical reason on to the candidate
        if "problem" in parameters:
            prompt += dialogue.REPAIR
            fields.update(previousReply=parameters["received"], problem=parameters["problem"])
        try:
            phrased, evidence = tools.model({"prompt": prompt, **fields, "schema": dialogue.UTTERANCE_SCHEMA})
        except tools.ToolResponseError as exc:
            raw = dialogue.raw_reply(exc.evidence).strip()
            phrased, evidence = ({"utterance": raw} if raw and "{" not in raw else {}), dict(exc.evidence or {})
        except MODEL_ERRORS:
            phrased, evidence = {}, {"mode": "model unavailable"}
        if isinstance(phrased, str):  # a bare JSON string (Apertus in Italian): the text is the reaction
            phrased = {"utterance": phrased}
        utterance = phrased.get("utterance") if isinstance(phrased, dict) else None
        # R2: wording decides nothing, so a broken reply is never repaired with another model call; the rules
        # use a neutral acknowledgement (attempt 1) or a fixed follow-up (attempt 2+) instead.
        if not (isinstance(utterance, str) and utterance.strip()):
            utterance = "" if parameters["attempt"] == 1 else content.REASK[c["lang"]]
        utterance = utterance.strip()
        if parameters["attempt"] == 1:
            last_answer = transcript[-1]["text"] if transcript and transcript[-1]["speaker"] == "user" else ""
            utterance = utterance.strip("«»\"' ")
            if utterance and utterance[-1] not in ".!":
                utterance += "."
            if re.search(EMOTION, last_answer, re.I):  # restfehler R8: a calm acknowledgement, no verdict
                utterance = EMOTION_ACK[c["lang"]]
            elif (not utterance or not acceptable(utterance, c) or "[" in utterance
                    or re.search(CRITICISM, last_answer, re.I)):
                acks = content.ACK[c["lang"]]
                utterance = acks[len(transcript) % len(acks)]
            utterance = f"{utterance} {parameters['question']}"
        elif not acceptable_reask(utterance, c):
            utterance = content.REASK[c["lang"]]
        return utterance, None, evidence

    def _judge(self, parameters):
        """The model's verdict, then the deterministic answer rules (rules.py) on the example check. Without a
        model (timeout, connection) the rules decide alone: the answer counts, the example rule checks it.
        Pilot (COACH_SEQUENCES=1): answers in a coaching sequence are read by the evidence extraction instead, and
        the component checks are decided by FrameX from the evidence, without a model call."""
        if content.sequences():
            handled = self._sequence_judge(parameters)
            if handled:
                return handled
        try:
            output, evidence = dialogue.judge(parameters)
        except MODEL_ERRORS:
            output = {"verdict": "unclear" if parameters.get("presaid") is True else "yes",
                      "reason": "rule: model unavailable, answer accepted"}
            if "checkCriterion" in parameters:
                example = parameters["checkCriterion"] == content.EXAMPLE_CHECK
                output.update(check="unclear" if example else "yes", checkReason="model unavailable")
            if parameters.get("more") is True:
                output["more"] = True
            evidence = {"mode": "rules only (model unavailable)"}
        return rules.apply_check_rules(parameters, output, self.context["lang"], self.context,
                                       {content.EXAMPLE_CHECK: "example", content.COMPANY_CHECK: "company",
                                        content.STEP_CHECK: "step"}), evidence

    # ---- pilot: evidence-driven coaching sequences ----
    def _topics(self):
        return self.state.setdefault("topics", {})

    def _sequence_judge(self, parameters):
        """Returns (output, evidence) for answers and checks of a coaching sequence, None otherwise."""
        c, lang = self.context, self.context["lang"]
        crit = parameters.get("checkCriterion") or parameters.get("criterion")
        component = next((k for k, v in ev.CHECK.items() if v == crit), None)
        question = parameters.get("question", "")
        topics = self._topics()
        opened = ev.topic_of(question, content.plan(c), lang)
        follow = next((k for k, v in ev.ACTION_TEXT[lang].items() if v == question), None)
        current = self.state.get("current_topic")
        if parameters.get("collect") and (opened or (follow and current)):
            if opened:
                qid, needs = opened
                current = qid
                self.state["current_topic"] = qid
                topics.setdefault(qid, {"qid": qid, "needs": list(needs), "followups": 0})
            topic = topics[current]
            if follow:
                topic["followups"] = topic.get("followups", 0) + 1
            answer = str(parameters.get("answer", ""))
            ref = len([t for t in dialogue.CHANNEL.transcript if t["speaker"] == "user"])
            guarded = {g.get("message") for g in self.state.get("guard", [])}
            extraction, mode = {}, "live"
            if answer not in guarded:
                old = os.environ.get("FRAMEX_MODEL_MAX_TOKENS")
                os.environ["FRAMEX_MODEL_MAX_TOKENS"] = "300"
                try:
                    extraction, _ = tools.model({"prompt": ev.EXTRACT, "question": question, "answer": answer,
                                                 "schema": ev.schema()})
                except MODEL_ERRORS:
                    extraction, mode = {}, "extraction failed: components unclear"
                finally:
                    os.environ["FRAMEX_MODEL_MAX_TOKENS"] = old or "120"
            checked, corrections = ev.checked(extraction, answer, ref)
            checked = ev.with_rules(checked, answer, lang)
            ev.merge(topic, checked, ref)
            if corrections:
                topic.setdefault("corrections", []).extend(corrections)
            words = len(answer.split())
            output = {"verdict": "yes" if words >= 1 else "unclear", "label": "answered" if words >= 1 else "unclear",
                      "reason": f"evidence: {', '.join(k for k in ev.COMPONENTS if checked[k]['status'] == 'present') or 'none'}"}
            if component:
                ok, why = ev.decide(topic, component, topic["needs"], self._followups())
                output.update(check="yes" if ok else "no", checkReason=why)
            return output, {"mode": mode}
        if component and current in topics:  # a component check after another check: decided from the evidence
            topic = topics[current]
            ok, why = ev.decide(topic, component, topic["needs"], self._followups())
            return {"verdict": "yes" if ok else "no", "reason": why}, {"mode": "decided by FrameX from evidence"}
        return None

    def _followups(self):
        return sum(t.get("followups", 0) for t in self._topics().values())

    def _company_answer(self, parameters):
        c = self.context
        facts = json.dumps(content.company_facts(c), ensure_ascii=False)[:3500]
        system = COMPANY.format(interviewer=c["interviewer"],
                                role=f' ({c["interviewer_role"]})' if c.get("interviewer_role") else "",
                                company=c["company"], occupation=c.get("occupation") or "",
                                language=content.LANG_NAME[c["lang"]], address=ADDRESS[c["lang"]], facts=facts)
        try:
            text = chat([{"role": "system", "content": system}, {"role": "user", "content": parameters["question"]}], 300)
            mode = "live"
        except MODEL_ERRORS:
            text, mode = COMPANY_FALLBACK[c["lang"]], "fixed (model unavailable)"
        # rules (restfehler R9): only offers and numbers from the company data; training terms from the glossary
        kept = rules.grounded_company_answer(text, json.dumps(content.company_facts(c), ensure_ascii=False), c["lang"])
        terms = rules.glossary_terms(parameters["question"], c["lang"])
        if kept != text.strip():
            mode += ", unsupported sentences removed"
        if len(kept.split()) < 8:  # nothing of substance left: say honestly that it will be clarified
            kept = f"{kept} {COMPANY_FALLBACK[c['lang']]}".strip()
        text = " ".join(terms + [kept])
        dialogue.CHANNEL.say(text)
        return {"said": True, "asked": "?" in parameters["question"]}, {"mode": mode}

    def _assessed_turns(self):
        """The conversation as the feedback sees it: messages a guard rule handled (distress, manipulation, the
        feedback request) are not assessed and never quoted as evidence (FHGR: distress is met with support, not
        graded); a marker keeps the conversation readable."""
        guarded = {g.get("message") for g in self.state.get("guard", [])}
        discouraged = any(str(g.get("kind", "")).startswith("distress") for g in self.state.get("guard", []))
        return [dict(t, text="[not assessed: handled by the coach's support or safety rules]")
                if t["speaker"] != "bot" and (t["text"] in guarded or (
                    discouraged and re.search(feedback.SELF_DEPRECATION, t["text"], re.I)))
                else t for t in dialogue.CHANNEL.transcript]

    def _structured_feedback(self):
        """R3: model fills contents (JSON, schema-constrained), rules check and assemble (feedback.py).
        Returns None when the model gives no usable JSON; the caller then uses the free-text prompt."""
        c, lang = self.context, self.context["lang"]
        keys = [k["key"] for k in content.rubric()["criteria"]]
        turns = self._assessed_turns()
        transcript = "\n".join(("Interviewer: " if t["speaker"] == "bot" else "Applicant: ") + t["text"] for t in turns)
        candidate_turns = [t["text"] for t in turns if t["speaker"] != "bot" and not t["text"].startswith("[not assessed")]
        criteria = ", ".join(keys)
        if os.environ.get("COACH_FEEDBACK_RUBRIC", "1") == "1":  # the FHGR level descriptions, for calibrated levels
            criteria = "\n" + feedback.rubric_text() + "\nGive each level by these descriptions, judged on the whole conversation"
        prompt = feedback.PROMPT.format(situation=SITUATION_NAME.get(c.get("situation"), "Vorstellungsgespräch"),
                                        occupation=c.get("occupation") or "an apprenticeship",
                                        language=content.LANG_NAME[lang], address=ADDRESS[lang], criteria=criteria)
        old = os.environ.get("FRAMEX_MODEL_MAX_TOKENS")
        old_timeout = os.environ.get("FRAMEX_MODEL_TIMEOUT")
        os.environ["FRAMEX_MODEL_MAX_TOKENS"] = str(MAX_TOKENS_FEEDBACK)
        os.environ["FRAMEX_MODEL_TIMEOUT"] = str(TIMEOUT_FEEDBACK)  # the longest answer of the interview
        try:
            # FrameX picks what the feedback is about from the decisions made during the interview
            excluded = [g.get("message") for g in self.state.get("guard", [])]
            strength, points = (feedback.observations(self.state.get("record", []), c, excluded)
                                if os.environ.get("COACH_OBSERVATIONS", "0") == "1" else (None, []))
            observed = ("\n\n" + feedback.observations_text(strength, points)) if (strength or points) else ""
            ev_strength = ev_point = None
            if content.sequences() and self._topics():  # pilot: one evidenced strength, one point to work on
                ev_strength, ev_point = ev.select(self._topics(), lang)
                observed = "\n\n" + ev.feedback_text(ev_strength, ev_point)
            request = {"prompt": prompt, "input": "Transcript:\n" + transcript + observed, "schema": feedback.schema(keys)}
            try:
                data = structured(request, MAX_TOKENS_FEEDBACK, TIMEOUT_FEEDBACK)
            except MODEL_ERRORS:
                return None
            if not isinstance(data, dict):
                return None
            issues = feedback.problems(data, c.get("name"))
            if issues:  # one repair call, naming exactly the broken rules
                repair = dict(request, input=request["input"] + "\n\nYour previous JSON:\n"
                              + json.dumps(data, ensure_ascii=False) + "\n\nIt broke these rules: " + "; ".join(issues)
                              + ". Return the corrected complete JSON.")
                try:
                    fixed, _ = tools.model(repair)
                    if isinstance(fixed, dict) and len(feedback.problems(fixed, c.get("name"))) < len(issues):
                        data = fixed
                except MODEL_ERRORS:
                    pass
            if isinstance(data, dict) and (strength or points):
                data = feedback.apply_observations(feedback.normalize(data), strength, points)
            if isinstance(data, dict) and content.sequences() and self._topics():
                data = ev.apply(feedback.normalize(data), ev_strength, ev_point, candidate_turns)
            data = feedback.drop_inadmissible_evidence(feedback.drop_english_better(feedback.drop_form_critique(feedback.normalize(data))))
            fields = feedback.third_person(data, c.get("name"))
            self.third_person_fields = fields
            if fields:  # «Luca hat …» -> «Du hast …»: a short rewrite call, then the rule drops what is left
                texts = dict(feedback.texts_of(data))
                rewritten = None
                try:
                    rewritten, _ = tools.model({"prompt": feedback.REWRITE_PROMPT.format(
                        language=content.LANG_NAME[lang], address=ADDRESS[lang], examples=feedback.REWRITE[lang]),
                        "input": json.dumps({f: texts[f] for f in fields}, ensure_ascii=False),
                        "schema": feedback.rewrite_schema(fields)})
                except MODEL_ERRORS:
                    pass
                data = feedback.apply_rewrite(data, fields, rewritten, c.get("name"), lang)
        finally:
            if old is None:
                os.environ.pop("FRAMEX_MODEL_MAX_TOKENS", None)
            else:
                os.environ["FRAMEX_MODEL_MAX_TOKENS"] = old
            os.environ["FRAMEX_MODEL_TIMEOUT"] = old_timeout or "120"
        facts = feedback.facts_of(c, self.state["record"], self.state.get("guard", []))
        voice = c.get("voice") or os.environ.get("COACH_VOICE") == "1"
        self.last_feedback_data = data
        return (feedback.assemble_spoken if voice else feedback.assemble)(data, c, candidate_turns, facts)

    def _second_person(self, text):
        """Free-text feedback: lines that talk about the candidate by name are rewritten into du/tu (one short call);
        a line that still names the candidate keeps the name only in a quote-free form the rules cannot fix, so it is
        left as it is (the structured path is the main path; this is its fallback)."""
        c, lang = self.context, self.context["lang"]
        name = c.get("name")
        if not name:
            return text
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        lines = text.split("\n")
        parts = {}  # line number -> (prefix the rules keep: table cells, list marker, bold heading; sentence; suffix)
        for i, line in enumerate(lines):
            if not pattern.search(re.sub(r"«[^»]*»", "", line)) or line.lstrip().startswith(("Grazie", "Danke", "Merci")):
                continue
            m = re.match(r"^(\|.*\|\s*)([^|]+?)(\s*\|\s*)$", line) \
                or re.match(r"^(\s*(?:(?:\d+\.|[-*])\s+)?(?:\*\*[^*]+\*\*\s*:?\s*)?)(.+?)()$", line)
            if m and pattern.search(m.group(2)):
                parts[i] = m.groups()
        if not parts:
            return text
        bad = {f"l{i}": p[1] for i, p in parts.items()}
        old = os.environ.get("FRAMEX_MODEL_MAX_TOKENS")
        os.environ["FRAMEX_MODEL_MAX_TOKENS"] = str(MAX_TOKENS_FEEDBACK)
        try:
            out, _ = tools.model({"prompt": feedback.REWRITE_PROMPT.format(
                language=content.LANG_NAME[lang], address=ADDRESS[lang], examples=feedback.REWRITE[lang])
                + " Keep any Markdown (table pipes, bold, list markers) exactly.",
                "input": json.dumps(bad, ensure_ascii=False), "schema": feedback.rewrite_schema(list(bad))})
        except MODEL_ERRORS:
            return text
        finally:
            os.environ["FRAMEX_MODEL_MAX_TOKENS"] = old or "400"
        for i, (prefix, _, suffix) in parts.items():
            new = out.get(f"l{i}") if isinstance(out, dict) else None
            if isinstance(new, str) and new.strip() and "|" not in new and "\n" not in new:
                lines[i] = prefix + new.strip() + suffix
        return "\n".join(lines)

    def _feedback(self, parameters):
        c, lang = self.context, self.context["lang"]
        crit = content.rubric()["criteria"]
        criteria = "\n".join(f'{i}. {k["label"].get(lang, k["label"]["de"])} – {k["what_is_assessed"]["de"]}'
                             for i, k in enumerate(crit, 1))
        transcript = "\n".join(("Interviewer: " if t["speaker"] == "bot" else "Bewerber/in: ") + t["text"]
                               for t in self._assessed_turns())
        h = content.FEEDBACK_HEADINGS[lang]
        situation = c.get("situation") or "apprenticeship_interview"
        if situation != "phone_call_trial":
            text = self._structured_feedback()
            if text:
                dialogue.CHANNEL.say(text)
                return {"said": True}, {"mode": "live, assembled by rules"}
        if situation == "phone_call_trial":  # from templates and rules only (restfehler R1)
            turns = [t["text"] for t in self._assessed_turns() if t["speaker"] != "bot"]
            dialogue.CHANNEL.say(feedback.phone_feedback(turns, lang, c.get("name")))
            return {"said": True}, {"mode": "assembled by rules"}
        else:
            system = FEEDBACK.format(occupation=c.get("occupation") or "Lehrstelle", criteria=criteria,
                                     situation=SITUATION_NAME.get(situation, "Vorstellungsgespräch"),
                                     language=content.LANG_NAME[lang], h1=h[0], h2=h[1], h3=h[2], h4=h[3],
                                     h5=h[7], cols=h[4], levels=h[5], none=h[6], extra=EXTRA.get(situation, ""),
                                     name=c.get("name") or "die Person")
        try:
            text, mode = chat([{"role": "system", "content": system},
                               {"role": "user", "content": "Gespräch:\n" + transcript}], MAX_TOKENS_FEEDBACK,
                              TIMEOUT_FEEDBACK), "live"
            text = self._second_person(text)
        except MODEL_ERRORS:
            text, mode = feedback.T[lang]["closing"], "closing only (model unavailable)"
        dialogue.CHANNEL.say(text)
        return {"said": True}, {"mode": mode}

    # ---- replay and live execution ----
    def _wrap(self, name, function):
        def tool(parameters):
            i = self.calls_seen
            self.calls_seen += 1
            record = self.state["record"]
            if i < len(record):  # replay: same order, same results, no model call
                entry = record[i]
                if entry["tool"] != name:
                    raise RuntimeError(f"replay diverged at call {i}: {entry['tool']} != {name}")
                for t in entry.get("transcript", []):
                    if t["speaker"] == "bot":
                        self.channel.say(t["text"], live=False)
                    else:
                        self.channel.transcript.append(t)
                return entry["output"], {"mode": "replayed"}
            before = len(self.channel.transcript)
            if name in ("_turn", "_repairTurn") and "step" in parameters:
                self.state["current_step"] = parameters["step"]
            pending = self.state.get("pending")
            if pending and pending["index"] == i and name in ("_turn", "_repairTurn"):
                # the question was phrased and shown last time; this message is the answer
                self.channel.say(pending["utterance"], live=False)
                answer = self.channel.answer()
                self.state["answers"] += 1
                output = {"question": parameters["question"], "utterance": pending["utterance"], "answer": answer}
                self.state["pending"] = None
            else:
                try:
                    output, _ = function(parameters)
                except NeedInput:
                    utterance = self.channel.transcript[-1]["text"]
                    self.state["pending"] = {"index": i, "utterance": utterance, "question": parameters.get("question", "")}
                    raise
                except Exception as exc:  # kept for diagnosis; the interview then ends with SORRY
                    self.state["error"] = f"{name}: {type(exc).__name__}: {exc}"[:500]
                    raise
            record.append({"tool": name, "output": output, "transcript": self.channel.transcript[before:]})
            return output, {"mode": "live"}
        return tool

    def _guard(self, message):
        """R5: clear patterns decide at once; otherwise the model classifies the message (distress, manipulation,
        none) with one short schema-constrained call. Any failure counts as none, so the interview goes on."""
        kind = rules.guard(message)
        if kind or os.environ.get("COACH_GUARD_MODEL", "1") == "0":
            return kind
        old = os.environ.get("FRAMEX_MODEL_MAX_TOKENS")
        os.environ["FRAMEX_MODEL_MAX_TOKENS"] = "80"
        try:
            out, _ = tools.model({"prompt": rules.GUARD_PROMPT, "input": message, "schema": rules.GUARD_SCHEMA})
            label = out.get("label") if isinstance(out, dict) else None
            return label if label in ("distress", "manipulation") else None
        except Exception:  # noqa: BLE001 - a broken guard reply must not stop the interview
            return None
        finally:
            os.environ["FRAMEX_MODEL_MAX_TOKENS"] = old or "400"

    def _guarded(self, message):
        """The coach's reply when a guard rule takes over this message, or None for the normal flow."""
        lang, pending = self.context["lang"], self.state.get("pending") or {}
        question = pending.get("question") or pending.get("utterance", "")
        if self.state.get("paused"):  # after a supportive pause: go on, or stop
            self.state["paused"] = False
            if re.search(rules.STOP, message, re.I):
                self.state.update(done=True, status="stopped")
                return [content.STOPPED[lang]]
            if len(message.split()) <= 4:  # «weiter», «ok», «oui», «sì, continua» ...
                return [f"{content.CONTINUE[lang]} {question}"]
            return None  # a real answer: the flow takes it
        calls = CALLS["n"]
        kind = self._guard(message)
        self.state["calls"] += CALLS["n"] - calls
        if not kind:
            return None
        if kind == "language" and sum(g["kind"] == "language" for g in self.state.get("guard", [])) >= 2:
            self.state["guard"].append({"kind": "language (again, interview goes on)", "message": message})
            return None
        if kind == "distress" and any(g["kind"] == "distress" for g in self.state.get("guard", [])) \
                and not re.search(rules.CRISIS, message, re.I):
            self.state["guard"].append({"kind": "distress (again, interview goes on)", "message": message})
            return None
        self.state.setdefault("guard", []).append({"kind": kind, "message": message})
        if kind == "stop":
            self.state.update(done=True, status="stopped")
            return [content.STOPPED[lang]]
        if kind == "feedback":
            return self._feedback_now(message)
        if kind == "manipulation":
            return [f"{content.REDIRECT[lang]} {question}"]
        if kind == "language":
            return [f"{content.LANGUAGE[lang]} {question}"]
        self.state["paused"] = True
        return [content.SUPPORT[lang]]

    def _feedback_now(self, message):
        """Feedback on the conversation so far (the candidate asked for it, or a harness ends the interview early)."""
        self.reply = [content.FEEDBACK_NOW[self.context["lang"]]]
        self.channel = self.Channel(self)
        self.channel.transcript = list(self.state.get("transcript", [])) + [{"speaker": "user", "text": message}]
        dialogue.CHANNEL = self.channel
        calls = CALLS["n"]
        self._feedback({})
        self.state["calls"] += CALLS["n"] - calls
        self.state.update(done=True, status="feedback on request", transcript=self.channel.transcript)
        return self.reply

    def step(self, message=None):
        """Feed one candidate message (None to start) and return what the coach says."""
        if self.state["done"]:
            return [DONE[self.context["lang"]]]
        if message and self.state.get("pending"):
            guarded = self._guarded(message)
            if guarded:
                self.state["transcript"] = self.state.get("transcript", []) + [
                    {"speaker": "user", "text": message}, {"speaker": "bot", "text": " ".join(guarded)}]
                return guarded
        self.reply, self.calls_seen = [], 0
        self.channel = self.Channel(self)
        self.channel.answer_text = message if self.state.get("pending") else None
        dialogue.CHANNEL = self.channel
        dialogue.phrase = self._phrase
        tools_ = dict(dialogue.TOOLS, _judge=self._judge, _repairJudge=self._judge)
        adapters = {name: self._wrap(name, fn) for name, fn in tools_.items()}
        adapters["_company_answer"] = self._wrap("_company_answer", self._company_answer)
        adapters["_feedback"] = self._wrap("_feedback", self._feedback)
        source = dialogue.FLOW.read_text() + "\n" + self.program
        calls_before = CALLS["n"]
        try:
            result = tools.run(source, FRAMEX_BINARY, max_actions=200, adapters=adapters)
            self.state["done"] = True
            self.state["status"] = result["status"]
            if result["status"] != "completed" and not self.reply:
                self.reply.append(SORRY[self.context["lang"]])
        except NeedInput:
            pass
        self.state["calls"] += CALLS["n"] - calls_before
        self.state["transcript"] = self.channel.transcript
        return self.reply


def summary(state):
    answers = max(state.get("answers", 0), 1)
    return {"llm_calls": state.get("calls", 0), "candidate_answers": state.get("answers", 0),
            "calls_per_answer": round(state.get("calls", 0) / answers, 2), "status": state.get("status")}


if __name__ == "__main__":  # terminal chat for development: python -m coach.session [posting id]
    posting = content.postings().get(sys.argv[1]) if len(sys.argv) > 1 else None
    ctx = content.context_from(posting=posting, name=os.environ.get("COACH_NAME", "Lea"))
    s = Session(ctx)
    message = None
    while True:
        started = time.time()
        for line in s.step(message):
            print("\nCoach:", line)
        print(f"   [{time.time() - started:.1f}s, {summary(s.state)}]")
        if s.state["done"]:
            break
        message = input("\nDu: ")
