"""Interview content from the FHGR datasets: question selection and the FrameX flow program.

The datasets are not part of this repository (FHGR licence: HackApertus use only); the Docker
build fetches them from github.com/fhgr/Hackapertus into FHGR_DATA.
"""
import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(os.environ.get("FHGR_DATA", Path(__file__).resolve().parents[2] / "fhgr" / "datasets"))
LANGS = ("de", "fr", "it")
LANG_NAME = {"de": "German (Standard German as used in Switzerland, no ß)", "fr": "French", "it": "Italian"}


def _jsonl(path):
    return [json.loads(line) for line in (DATA / path).read_text(encoding="utf-8").splitlines() if line.strip()]


@lru_cache(maxsize=None)
def questions():
    return {q["id"]: q for q in _jsonl("questions/questions.jsonl")}


@lru_cache(maxsize=None)
def postings():
    return {p["id"]: p for p in _jsonl("profiles/postings.jsonl")}


@lru_cache(maxsize=None)
def candidates():
    return {c["id"]: c for c in _jsonl("profiles/candidates.jsonl")}


@lru_cache(maxsize=None)
def scenarios():
    return {s["id"]: s for s in _jsonl("scenarios/scenarios.jsonl")}


@lru_cache(maxsize=None)
def rubric():
    return json.loads((DATA / "rubric" / "criteria.json").read_text(encoding="utf-8"))


def occupation_name(posting, lang):
    occ = posting["occupation"]
    return occ.get(f"name_{lang}") or occ.get("name_de")


def find_posting(occupation_text):
    """The posting whose occupation best matches free text (word overlap), or None."""
    words = {w for w in occupation_text.lower().replace("/", " ").split() if len(w) > 3}
    best, score = None, 0
    for p in postings().values():
        names = " ".join(str(v) for k, v in p["occupation"].items() if k.startswith("name_")).lower()
        s = sum(1 for w in words if w[:6] in names)
        if s > score:
            best, score = p, s
    return best


# Main questions per situation, in interview order: (question id, follow-up mode). Mode "example": ask for a
# concrete example when the judge finds none; "own": ask for the candidate's own share when the answer blames
# others or evades. "JOB" = an occupation-specific question (Q-BFxx) or Q-04-04; "SIT" = a situational one;
# "DIF" = the difficult questions the candidate's profile gives a reason for (FHGR condition field).
PLANS = {
    "apprenticeship_interview": [("Q-02-01", None), ("Q-03-01", "example"), ("Q-03-04", "company"), ("JOB", None),
                                 ("Q-05-01", "example"), ("Q-05-03", "step"), ("DIF", "own"), ("Q-06-07", "example"),
                                 ("Q-07-01", "example"), ("SIT", None), ("Q-08-02", None)],
    "online_interview": [("Q-OTH-07", None), ("Q-OTH-08", None), ("Q-02-01", None), ("Q-03-01", "example"),
                         ("Q-03-04", "company"), ("Q-05-01", "example"), ("Q-05-03", "step"), ("DIF", "own"),
                         ("Q-06-07", "example"), ("SIT", None), ("Q-08-02", None)],
    "trial_interview": [("Q-02-01", None), ("Q-OTH-04", None), ("Q-OTH-05", None), ("JOB", None), ("Q-03-01", "example"),
                        ("Q-05-01", "example"), ("DIF", "own"), ("Q-OTH-06", None), ("Q-08-02", None)],
    "follow_up_interview": [("Q-OTH-12", "example"), ("Q-OTH-13", None), ("Q-OTH-14", "own"), ("Q-03-04", "company"),
                            ("Q-05-03", "step"), ("DIF", "own"), ("SIT", None), ("Q-08-02", None)],
    "assessment": [("Q-02-01", None), ("Q-OTH-11", None), ("Q-OTH-10", "own"), ("Q-03-01", "example"),
                   ("Q-05-01", "example"), ("DIF", "own"), ("SIT", None), ("Q-08-02", None)],
    "phone_call_trial": [("Q-OTH-01", "name"), ("Q-OTH-02", None), ("Q-OTH-03", None)],
}
SITUATIONAL = ["Q-SIT-01", "Q-SIT-02", "Q-SIT-05", "Q-SIT-08", "Q-SIT-10", "Q-SIT-12"]


def profile_flags(candidate):
    """Reasons in a candidate profile for FHGR's conditional and difficult questions: noted absences (Q-DIF-04),
    a low maths grade (Q-DIF-06), an interrupted apprenticeship or school (Q-DIF-05, biggest failure)."""
    if not candidate:
        return []
    school = candidate.get("school") or {}
    flags = []
    if school.get("absences_note"):
        flags.append("Q-DIF-04")
    if re.search(r"(mathe\w*|math\w*|matemat\w*)\s*[:=]?\s*[1-3]([.,]\d+)?\b", str(school.get("grades_note") or ""), re.I):
        flags.append("Q-DIF-06")
    story = json.dumps([candidate.get("career_choice_story"), candidate.get("experiences"), school], ensure_ascii=False)
    if re.search(r"abgebrochen|abbruch|interromp|interrott|aufgelöst", story, re.I):
        flags.append("Q-DIF-05")
    return flags


EXAMPLE_CHECK = ("Nennt die Person in ihren Antworten auf diese Frage eine konkrete eigene Situation, ein "
                 "Erlebnis oder ein konkretes Beispiel (nicht nur allgemeine Aussagen)?")
ANSWERED = "Geht die Person auf die Frage ein, auch kurz oder unsicher?"
ASKS_QUESTION = "Stellt die Person mindestens eine eigene Frage an den Betrieb oder zur Lehre?"
OWN_CHECK = ("Benennt die Person ehrlich ihren eigenen Anteil oder was sie selbst ändert (statt auszuweichen oder "
             "die Schuld anderen zu geben)?")
COMPANY_CHECK = ("Nennt die Person etwas Konkretes über diesen Betrieb oder die Lehre dort (nicht nur allgemeine "
                 "Aussagen wie «gute Firma» oder «spannende Projekte»)?")
STEP_CHECK = "Sagt die Person, was sie konkret tut, um an dieser Schwäche zu arbeiten?"
NAME_CHECK = "Nennt die Person ihren Vor- und Nachnamen und sagt sie, worum es geht (eine Schnupperlehre; französisch «stage», italienisch «stage»)?"

# Neutral acknowledgements when the model's reaction breaks a rule (see session.acceptable).
ACK = {"de": ["Danke dir.", "Okay, danke.", "Verstehe, danke.", "Gut, danke dir."],
       "fr": ["Merci.", "D'accord, merci.", "Je vois, merci.", "Entendu, merci."],
       "it": ["Grazie.", "Va bene, grazie.", "Capisco, grazie.", "Bene, grazie."]}
# R5 guard replies (FHGR L3: distress -> support and refer to a real person; manipulation -> stay in role)
SUPPORT = {
    "de": "Danke, dass du das so offen sagst. Viele Absagen sind wirklich frustrierend – sie sagen aber nichts darüber aus, "
          "was du kannst. Rede mit jemandem darüber, dem du vertraust: deiner Lehrperson, deinen Eltern oder der "
          "Berufsberatung (BIZ). Wenn es dir gerade richtig schlecht geht, kannst du jederzeit gratis die 147 anrufen oder "
          "ihr schreiben (Pro Juventute). Möchtest du trotzdem weiterüben? Dann schreib einfach «weiter» – oder «Stopp», "
          "wenn wir für heute aufhören sollen.",
    "fr": "Merci de le dire aussi franchement. Beaucoup de refus, c'est vraiment décourageant – mais ça ne dit rien de ce que "
          "tu sais faire. Parles-en à quelqu'un de confiance : ton enseignant·e, tes parents ou l'orientation "
          "professionnelle. Si ça va vraiment mal en ce moment, tu peux appeler ou écrire gratuitement au 147 (Pro Juventute), "
          "à tout moment. Tu veux quand même continuer l'entraînement ? Écris simplement « continuer » – ou « stop » si on "
          "s'arrête pour aujourd'hui.",
    "it": "Grazie per averlo detto così apertamente. Tanti rifiuti sono davvero scoraggianti – ma non dicono nulla di quello "
          "che sai fare. Parlane con qualcuno di cui ti fidi: il tuo docente, i tuoi genitori o l'orientamento professionale. "
          "Se in questo momento stai davvero male, puoi chiamare o scrivere gratuitamente al 147 (Pro Juventute), a qualsiasi "
          "ora. Vuoi comunque continuare l'esercizio? Scrivi semplicemente «continua» – oppure «stop» se ci fermiamo per oggi.",
}
REDIRECT = {"de": "Ich bleibe dein Interview-Coach und bewerte nur, was du im Gespräch zeigst – so hilft dir die Übung am "
                  "meisten. Lass uns weitermachen:",
            "fr": "Je reste ton coach d'entretien et j'évalue seulement ce que tu montres dans l'entretien – c'est comme ça "
                  "que l'exercice t'aide le plus. Continuons :",
            "it": "Resto il tuo coach per il colloquio e valuto solo quello che mostri nel colloquio – così l'esercizio ti "
                  "aiuta di più. Continuiamo:"}
# An answer in English (R5, rules.english): the interview stays in its language, the question is asked again.
LANGUAGE = {"de": "Wir üben das Gespräch auf Deutsch. Antworte ruhig in einfachen Sätzen, auch Mundart geht. Auf "
                  "Französisch oder Italienisch kannst du in einem neuen Gespräch üben. Hier nochmals die Frage:",
            "fr": "Nous nous entraînons en français. Tu peux répondre avec des phrases simples. Pour t'entraîner en "
                  "allemand ou en italien, commence une nouvelle conversation. Voici encore la question :",
            "it": "Ci alleniamo in italiano. Puoi rispondere con frasi semplici. Per allenarti in tedesco o in francese, "
                  "inizia una nuova conversazione. Ecco di nuovo la domanda:"}
FEEDBACK_NOW = {"de": "Gerne – dann beenden wir das Gespräch hier. Ich wechsle die Rolle und gebe dir als Coach ein Feedback zu dem, was du bis jetzt gezeigt hast.",
                "fr": "Avec plaisir – on termine l'entretien ici. Je change de rôle et je te donne, en tant que coach, un retour sur ce que tu as montré jusqu'ici.",
                "it": "Volentieri – allora chiudiamo qui il colloquio. Cambio ruolo e ti do, come coach, un feedback su quello che hai mostrato finora."}
CONTINUE = {"de": "Schön, dass du weitermachst. Nimm dir ruhig Zeit.", "fr": "Super que tu continues. Prends ton temps.",
            "it": "Bello che continui. Prenditi pure il tuo tempo."}
STOPPED = {"de": "In Ordnung, wir hören für heute auf. Du kannst jederzeit wieder üben – und denk daran: Mit jemandem zu "
                 "reden, dem du vertraust, hilft. Alles Gute!",
           "fr": "D'accord, on s'arrête pour aujourd'hui. Tu peux t'entraîner à nouveau quand tu veux – et parler à quelqu'un "
                 "de confiance aide. Bonne continuation !",
           "it": "Va bene, per oggi ci fermiamo. Puoi esercitarti di nuovo quando vuoi – e parlare con qualcuno di cui ti fidi "
                 "aiuta. In bocca al lupo!"}

REASK = {"de": "Kannst du mir dazu noch etwas mehr erzählen?",
         "fr": "Est-ce que tu peux m'en dire un peu plus ?",
         "it": "Mi puoi raccontare qualcosa in più?"}
FEEDBACK_HEADINGS = {
    "de": ("Gesamteindruck", "Deine Bewertung", "Deine zwei Stärken", "Dein nächster Schritt",
           "Kriterium | Stufe | Beleg aus dem Gespräch",
           "Ungenügend, Ausbaufähig, Gut, Sehr gut", "Dazu gab es im Gespräch keine Aussage",
           "Daran kannst du arbeiten"),
    "fr": ("Impression générale", "Ton évaluation", "Tes deux points forts", "Ta prochaine étape",
           "Critère | Niveau | Exemple tiré de l'entretien",
           "Insuffisant, À développer, Bien, Très bien", "Aucun élément à ce sujet dans l'entretien",
           "Ce que tu peux encore travailler"),
    "it": ("Impressione generale", "La tua valutazione", "I tuoi due punti di forza", "Il tuo prossimo passo",
           "Criterio | Livello | Esempio dal colloquio",
           "Insufficiente, Da sviluppare, Buono, Molto buono", "Nel colloquio non c'erano elementi al riguardo",
           "Su che cosa puoi ancora lavorare"),
}

TEXT = {
    "de": {
        "greet": "Hallo {name}, schön, dass du da bist! Ich bin {interviewer} und bei {company} für die Lernenden "
                 "zuständig. Wir sprechen heute etwa 20 Minuten miteinander: zuerst über dich, dann über deine "
                 "Motivation und deine Stärken. Am Schluss kannst du mir Fragen stellen, und danach bekommst du von "
                 "mir als Coach ein Feedback. Du kannst dir ruhig Zeit lassen.",
        "example": "Kannst du mir dazu ein konkretes Beispiel erzählen, etwas, das du selbst erlebt hast?",
        "questions": "Jetzt bist du dran: Hast du Fragen an uns?",
        "own": "Und was war dabei dein eigener Anteil, was machst du heute anders?",
        "company": "Was weisst du schon über uns, und was davon passt zu dir?",
        "step": "Und was tust du konkret, um daran zu arbeiten?",
        "greet_job": "Es geht um deine Bewerbung für die Lehre als {occupation}.",
        "name": "Darf ich nochmals deinen Vor- und Nachnamen haben, und worum geht es genau?",
        "phone_greet": "Wir üben jetzt einen Anruf, um eine Schnupperlehre anzufragen. Stell dir vor, du rufst bei "
                       "{company} an und ich nehme ab. Danach bekommst du von mir ein kurzes Feedback.",
        "phone_closing": "Danke für deinen Anruf, ich notiere mir das. Auf Wiederhören! So, jetzt wechsle ich die "
                         "Rolle und gebe dir als Coach ein kurzes Feedback zum Telefonat.",
        "closing_short": "Danke für das Gespräch, {name}! So, jetzt wechsle ich die Rolle und gebe dir als Coach ein kurzes Feedback.",
        "closing": "Vielen Dank für das Gespräch, {name}! Du hörst innerhalb von zwei Wochen von uns. "
                   "So, jetzt wechsle ich die Rolle: Ich bin jetzt dein Coach und gebe dir ein Feedback zum Gespräch.",
    },
    "fr": {
        "greet": "Bonjour {name}, je suis content·e que tu sois là ! Je suis {interviewer} et je m'occupe des "
                 "apprenti·e·s chez {company}. Nous allons parler environ 20 minutes : d'abord de toi, puis de ta "
                 "motivation et de tes points forts. À la fin, tu pourras me poser tes questions, puis je te donnerai, "
                 "en tant que coach, un retour sur l'entretien. Prends ton temps.",
        "example": "Est-ce que tu peux me donner un exemple concret, quelque chose que tu as vécu toi-même ?",
        "questions": "À toi maintenant : est-ce que tu as des questions pour nous ?",
        "own": "Et quelle était ta part à toi, qu'est-ce que tu fais différemment aujourd'hui ?",
        "company": "Qu'est-ce que tu sais déjà de nous, et qu'est-ce qui te correspond là-dedans ?",
        "step": "Et qu'est-ce que tu fais concrètement pour t'améliorer ?",
        "greet_job": "Il s'agit de ta candidature pour l'apprentissage de {occupation}.",
        "name": "Est-ce que tu peux me redonner ton prénom et ton nom, et me dire exactement de quoi il s'agit ?",
        "phone_greet": "On s'entraîne maintenant à téléphoner pour demander un stage. Imagine que tu appelles "
                       "{company} et que je décroche. Ensuite, je te donne un court retour.",
        "phone_closing": "Merci pour ton appel, je note tout ça. Au revoir ! Maintenant je change de rôle et je te "
                         "donne, en tant que coach, un court retour sur l'appel.",
        "closing_short": "Merci pour cet échange, {name} ! Maintenant je change de rôle et je te donne, en tant que coach, un court retour.",
        "closing": "Merci beaucoup pour cet entretien, {name} ! Tu auras de nos nouvelles d'ici deux semaines. "
                   "Maintenant je change de rôle : je suis ton coach et je te donne un retour sur l'entretien.",
    },
    "it": {
        "greet": "Ciao {name}, che bello che sei qui! Sono {interviewer} e da {company} mi occupo degli apprendisti. "
                 "Oggi parliamo per circa 20 minuti: prima di te, poi della tua motivazione e dei tuoi punti di forza. "
                 "Alla fine potrai farmi delle domande e poi, come coach, ti darò un feedback sul colloquio. "
                 "Prenditi pure il tuo tempo.",
        "example": "Mi puoi raccontare un esempio concreto, qualcosa che hai vissuto tu?",
        "questions": "Ora tocca a te: hai delle domande per noi?",
        "own": "E qual è stata la tua parte, che cosa fai di diverso oggi?",
        "company": "Che cosa sai già di noi, e che cosa di questo fa per te?",
        "step": "E che cosa fai concretamente per migliorare?",
        "greet_job": "Si tratta della tua candidatura per il tirocinio come {occupation}.",
        "name": "Mi puoi ridire il tuo nome e cognome e di che cosa si tratta esattamente?",
        "phone_greet": "Ora ci esercitiamo con una telefonata per chiedere uno stage d'orientamento. Immagina di "
                       "chiamare {company} e che io risponda. Poi ti do un breve feedback.",
        "phone_closing": "Grazie per la chiamata, me lo segno. Arrivederci! Adesso cambio ruolo e ti do, come coach, "
                         "un breve feedback sulla telefonata.",
        "closing_short": "Grazie per la chiacchierata, {name}! Adesso cambio ruolo e ti do, come coach, un breve feedback.",
        "closing": "Grazie mille per il colloquio, {name}! Riceverai nostre notizie entro due settimane. "
                   "Adesso cambio ruolo: sono il tuo coach e ti do un feedback sul colloquio.",
    },
}


def _pick(ids, seed):
    ids = list(ids)
    return ids[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(ids)] if ids else None


def plan(context):
    """The main questions and their follow-up modes for this interview, deterministic for the same context."""
    seed = f'{context.get("occupation", "")}|{context.get("company", "")}|{context.get("name", "")}'
    field = context.get("berufsfeld_key")
    job = [q["id"] for q in questions().values() if field and q.get("berufsfeld") == field
           and q["flow_stage"] in ("motivation", "situational") and not q.get("condition")]
    # questions the scenario plans (FHGR planned_question_ids, or Q-ids in a harness message) come first
    planned = [q for q in context.get("planned") or [] if q in questions()]
    planned_job = [q for q in planned if q.startswith("Q-BF") or (field and questions()[q].get("berufsfeld") == field)]
    planned_sit = [q for q in planned if q.startswith("Q-SIT")]
    chosen = []
    for qid, mode in PLANS.get(context.get("situation") or "", PLANS["apprenticeship_interview"]):
        if qid == "JOB":
            chosen.append((planned_job[0] if planned_job else _pick(job, seed + "job") or "Q-04-04", mode))
        elif qid == "SIT":
            chosen.append((planned_sit[0] if planned_sit else _pick(SITUATIONAL, seed + "sit"), mode))
        elif qid == "DIF":
            flags = list(context.get("flags", []))
            # a difficult question the scenario plans (e.g. Q-DIF-02 other applications), if the profile gave none
            planned_dif = [q for q in planned if q.startswith("Q-DIF") and q not in flags]
            chosen += [(d, mode) for d in flags or planned_dif[:1]]
        else:
            chosen.append((qid, mode))
    if sequences():  # pilot: the topic questions become coaching sequences (evidence.TOPICS)
        from . import evidence
        chosen = [(q, "story" if q in evidence.TOPICS and m in ("example", "own", None) else m) for q, m in chosen]
    return chosen


def sequences():
    """Pilot switch: evidence-driven coaching sequences instead of one example check per question."""
    return os.environ.get("COACH_SEQUENCES", "0") == "1"


def fx(value):
    return json.dumps(value, ensure_ascii=False)


def program(context):
    """The FrameX flow (F-Logic) for one interview."""
    lang = context["lang"]
    phone = context.get("situation") == "phone_call_trial"
    # without a name: "Hallo , schön" -> "Hallo, schön", "Gespräch, !" -> "Gespräch!"
    t = {k: re.sub(r",\s*!", "!", re.sub(r"\s+,", ",", v.format(**context))) for k, v in TEXT[lang].items()}
    if context.get("situation") in ("trial_interview", "follow_up_interview"):  # no «you will hear from us»
        t["closing"] = t["closing_short"]
    if context.get("occupation") and not phone:  # name the apprenticeship right after the introduction
        parts = re.split(r"(?<=[.!])\s+", t["greet"], maxsplit=2)
        t["greet"] = " ".join(parts[:2] + [t["greet_job"]] + parts[2:])
    steps = plan(context)
    after = "closing" if phone else "askQuestions"
    lines = [
        "world open.",
        "coach:flow#Flow[flow#start -> greet; flow#checkWithAnswer -> true; flow#historyOnReask -> true].",
        f"greet:flow#Say[flow#text -> {fx(t['phone_greet' if phone else 'greet'])}; flow#next -> q1].",
    ]
    checks = {"example": (EXAMPLE_CHECK, t["example"]), "own": (OWN_CHECK, t["own"]), "name": (NAME_CHECK, t["name"]),
              "company": (COMPANY_CHECK, t["company"]), "step": (STEP_CHECK, t["step"])}
    for i, (qid, mode) in enumerate(steps, 1):
        q = questions()[qid]
        nxt = f"q{i + 1}" if i < len(steps) else after
        text = q["text"][lang]
        if qid == "Q-OTH-01":  # the company picks up the phone
            text = re.sub(r"die Firma|entreprise …|l'azienda …", context["company"], text)
        if mode == "story":  # pilot: one check per relevant component, a coaching action for what is missing
            from . import evidence
            needs = evidence.TOPICS[qid]
            lines.append(f"q{i}:flow#Collect[flow#ask -> {fx(text)}; flow#criterion -> {fx(ANSWERED)}; "
                         f"flow#slot -> a{i}; flow#maxAttempts -> 2; flow#next -> q{i}k1].")
            for j, comp in enumerate(needs, 1):
                after_j = f"q{i}k{j + 1}" if j < len(needs) else nxt
                lines.append(f"q{i}k{j}:flow#Check[flow#about -> q{i}; flow#criterion -> {fx(evidence.CHECK[comp])}; "
                             f"flow#slot -> k{i}x{j}; flow#ifSlot -> k{i}x{j}; flow#to -> {after_j}; "
                             f"flow#ifUnknown -> q{i}f{j}; flow#otherwise -> q{i}f{j}].")
                lines.append(f"q{i}f{j}:flow#Collect[flow#ask -> {fx(evidence.ACTION_TEXT[lang][comp])}; "
                             f"flow#criterion -> {fx(ANSWERED)}; flow#slot -> f{i}x{j}; flow#maxAttempts -> 1; "
                             f"flow#next -> {after_j}].")
        elif mode:
            criterion, follow_up = checks[mode]
            lines.append(f"q{i}:flow#Collect[flow#ask -> {fx(text)}; flow#criterion -> {fx(ANSWERED)}; "
                         f"flow#slot -> a{i}; flow#maxAttempts -> 2; flow#next -> q{i}ex].")
            lines.append(f"q{i}ex:flow#Check[flow#about -> q{i}; flow#criterion -> {fx(criterion)}; "
                         f"flow#slot -> ex{i}; flow#ifSlot -> ex{i}; flow#to -> {nxt}; flow#otherwise -> q{i}more].")
            lines.append(f"q{i}more:flow#Collect[flow#ask -> {fx(follow_up)}; flow#criterion -> {fx(ANSWERED)}; "
                         f"flow#slot -> more{i}; flow#maxAttempts -> 1; flow#next -> {nxt}].")
        else:
            lines.append(f"q{i}:flow#Collect[flow#ask -> {fx(text)}; flow#criterion -> {fx(ANSWERED)}; "
                         f"flow#slot -> a{i}; flow#maxAttempts -> 2; flow#next -> {nxt}].")
        lines.append(f'q{i}[questionId -> {fx(qid)}].')
    if not phone:
        lines += [
            f"askQuestions:flow#Collect[flow#ask -> {fx(t['questions'])}; flow#criterion -> {fx(ANSWERED)}; "
            "flow#slot -> questionsHandled; flow#maxAttempts -> 1; flow#next -> asksCheck].",
            f"asksCheck:flow#Check[flow#about -> askQuestions; flow#criterion -> {fx(ASKS_QUESTION)}; "
            "flow#slot -> asked; flow#ifSlot -> asked; flow#to -> answerQuestions; flow#ifUnknown -> answerQuestions; "
            "flow#otherwise -> closing].",
            "answerQuestions:flow#Action[flow#next -> closing].",
            "external companyAnswer(answerQuestions) using _company_answer[question -> ?A; tool#order -> 5]",
            "    <- answerQuestions[flow#runNow -> true] AND askQuestions[flow#lastAnswer -> ?A].",
        ]
    lines += [
        f"closing:flow#Say[flow#text -> {fx(t['phone_closing' if phone else 'closing'])}; flow#next -> feedback].",
        "feedback:flow#Action[flow#next -> flow#end].",
        "external coachFeedback(feedback) using _feedback[tool#order -> 6] <- feedback[flow#runNow -> true].",
    ]
    return "\n".join(lines) + "\n"


def context_from(posting=None, candidate=None, lang=None, name=None, occupation=None, situation=None, planned=None):
    """Interview context: who interviews whom for which apprenticeship, in which language."""
    lang = lang or (candidate or {}).get("interview_language") or (posting or {}).get("lang") or "de"
    if lang not in LANGS:
        lang = "de"
    ctx = {"lang": lang, "name": name or (candidate or {}).get("first_name") or "",
           "situation": situation if situation in PLANS else "apprenticeship_interview",
           "flags": profile_flags(candidate), "planned": list(planned or [])}
    if posting:
        iv = posting.get("interviewer") or {}
        ctx.update(
            posting_id=posting["id"],
            occupation=occupation_name(posting, lang),
            berufsfeld_key=posting["occupation"].get("berufsfeld_key"),
            company=posting["company"]["name"],
            place=posting["company"].get("place", ""),
            interviewer=iv.get("name") or "Sandra",
            interviewer_role=iv.get("role", ""),
            interviewer_style=iv.get("style", ""),
        )
    else:
        ctx.update(occupation=occupation or "", berufsfeld_key=None,
                   company={"de": "unserem Lehrbetrieb", "fr": "notre entreprise formatrice",
                            "it": "la nostra azienda formatrice"}[lang],
                   place="", interviewer="Sandra", interviewer_role="", interviewer_style="freundlich")
    if not ctx["name"]:
        ctx["name"] = ""
    return ctx


def company_facts(context):
    """What the coach may say as the company when answering the candidate's questions."""
    p = postings().get(context.get("posting_id") or "")
    if not p:
        return {"company": context.get("company"), "occupation": context.get("occupation")}
    keys = ("company", "offers", "insider_facts", "selection_process", "start_date", "bm_possible", "requirements")
    return {k: p.get(k) for k in keys if p.get(k)}
