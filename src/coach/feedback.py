"""R3: the feedback is assembled by rules; the model only fills in contents.

The model returns JSON (levels with evidence per criterion, two strengths, at most two improvements with a quote
and a better formulation, one next step). The rules then check it and write the frame:
- an evidence quote counts only if it occurs in the candidate's own words (else it is shown as a paraphrase),
- at most two improvement points, at least one with a better formulation,
- no third-person talk about the candidate: a short rewrite call turns those sentences into du/tu; a sentence that
  still names the candidate is dropped,
- headings, du/tu address, table, and the encouraging closing come from templates,
- mandatory blocks follow from facts of the conversation: difficult questions asked -> answer pattern,
  assessment -> presentation tip, online interview -> online tip, no own question asked -> tip to prepare some.
"""
import json
import re

from . import content

LEVELS = {"de": ["Dazu gab es keine Aussage", "Ungenügend", "Ausbaufähig", "Gut", "Sehr gut"],
          "fr": ["Aucun élément", "Insuffisant", "À développer", "Bien", "Très bien"],
          "it": ["Nessun elemento", "Insufficiente", "Da sviluppare", "Buono", "Molto buono"]}
T = {
    "de": {"overall": "Gesamteindruck", "table": "Deine Bewertung", "cols": "| Kriterium | Stufe | Beleg aus dem Gespräch |",
           "strengths": "Das ist dir gut gelungen", "improve": "Daran kannst du arbeiten", "next": "Dein nächster Schritt",
           "said": "Du hast gesagt", "better": "Stärker wäre zum Beispiel", "para": "sinngemäss",
           "pattern": "**Schwierige Fragen** (Absenzen, Noten, Abbruch): Antworte in drei Schritten – ehrlich benennen, was "
                      "passiert ist; Verantwortung übernehmen; zeigen, was du seither änderst, mit einem Beleg (z. B. «seit "
                      "dem Herbst keine Absenz mehr»).",
           "presentation": "**Kurzpräsentation**: Baue sie in drei Teilen auf – ein Einstieg, ein Kernpunkt mit Beispiel, ein "
                           "Schlusssatz – und übe sie einmal mit Uhr, damit du in der Zeit bleibst.",
           "online": "**Online-Gespräch**: Prüfe vorher Kamera und Ton, setz dich vor einen ruhigen Hintergrund und leg dir "
                     "Stichworte neben den Bildschirm.",
           "questions": "**Eigene Fragen**: Bereite für das nächste Gespräch zwei Fragen an den Betrieb vor, zum Beispiel zum "
                        "Ablauf der Lehre oder zum Team – das zeigt Interesse.",
           "questions_asked": "**Eigene Fragen**: Gut, dass du nachgefragt hast. Notiere dir fürs nächste Gespräch zwei bis "
                              "drei Fragen zum Betrieb, zum Beispiel zum Ablauf der Lehre oder zum Team, und frag auch "
                              "nach, wenn dir eine Antwort unklar ist.",
           "doubt": "**Unterstützung**: Du hast im Gespräch Zweifel geäussert – das ist ganz normal. Sprich mit der Berufsberatung (BIZ), deiner Lehrperson oder deinen Eltern darüber; sie helfen dir bei den nächsten Bewerbungen.",
           "support": "**Zum Schluss**: Du hast im Gespräch erzählt, dass dich die Absagen belasten. Das ist verständlich. Hol dir Unterstützung bei einer Person, der du vertraust – Lehrperson, Eltern oder Berufsberatung (BIZ); in einer Krise hilft die 147.",
           "closing": "Das war ein Übungsgespräch – und genau dafür ist es da. Mit jedem Mal wirst du sicherer. Bleib dran!"},
    "fr": {"overall": "Impression générale", "table": "Ton évaluation", "cols": "| Critère | Niveau | Exemple tiré de l'entretien |",
           "strengths": "Ce que tu as bien réussi", "improve": "Ce que tu peux encore travailler", "next": "Ta prochaine étape",
           "said": "Tu as dit", "better": "Plus fort serait par exemple", "para": "en substance",
           "pattern": "**Questions difficiles** (absences, notes, interruption) : réponds en trois étapes – dire honnêtement ce "
                      "qui s'est passé ; prendre ta part de responsabilité ; montrer ce que tu as changé depuis, avec une preuve.",
           "presentation": "**Courte présentation** : structure-la en trois parties – une accroche, un point clé avec un exemple, "
                           "une phrase de conclusion – et entraîne-toi une fois avec une montre pour respecter le temps.",
           "online": "**Entretien en ligne** : vérifie la caméra et le son avant, choisis un fond calme et garde quelques mots-clés "
                     "à côté de l'écran.",
           "questions": "**Tes propres questions** : prépare deux questions pour l'entreprise, par exemple sur le déroulement de "
                        "l'apprentissage ou sur l'équipe – cela montre ton intérêt.",
           "questions_asked": "**Tes propres questions** : c'est bien que tu aies posé une question. Pour le prochain "
                              "entretien, note deux ou trois questions sur l'entreprise, par exemple sur l'apprentissage "
                              "ou l'équipe, et redemande si une réponse n'est pas claire.",
           "doubt": "**Soutien** : tu as exprimé des doutes pendant l'entretien – c'est tout à fait normal. Parles-en à l'orientation professionnelle, à ton enseignant·e ou à tes parents ; ils t'aident pour les prochaines candidatures.",
           "support": "**Pour finir** : tu as dit que les refus te pèsent. C'est compréhensible. Cherche du soutien auprès d'une personne de confiance – enseignant·e, parents ou orientation professionnelle ; en cas de crise, le 147 t'aide.",
           "closing": "C'était un entretien d'entraînement – et c'est exactement à ça qu'il sert. À chaque fois, tu gagnes en "
                      "assurance. Continue comme ça !"},
    "it": {"overall": "Impressione generale", "table": "La tua valutazione", "cols": "| Criterio | Livello | Esempio dal colloquio |",
           "strengths": "Cosa ti è riuscito bene", "improve": "Su che cosa puoi ancora lavorare", "next": "Il tuo prossimo passo",
           "said": "Hai detto", "better": "Più forte sarebbe per esempio", "para": "in sostanza",
           "pattern": "**Domande difficili** (assenze, voti, interruzione): rispondi in tre passi – dire onestamente che cosa è "
                      "successo; prenderti la tua parte di responsabilità; mostrare che cosa hai cambiato da allora, con una prova.",
           "presentation": "**Breve presentazione**: costruiscila in tre parti – un inizio, un punto chiave con un esempio, una "
                           "frase finale – ed esercitati una volta con l'orologio per restare nei tempi.",
           "online": "**Colloquio online**: controlla prima videocamera e audio, scegli uno sfondo tranquillo e tieni qualche "
                     "parola chiave accanto allo schermo.",
           "questions": "**Le tue domande**: prepara due domande per l'azienda, per esempio sullo svolgimento del tirocinio o "
                        "sul team – mostra interesse.",
           "questions_asked": "**Le tue domande**: bene che tu abbia fatto una domanda. Per il prossimo colloquio annota "
                              "due o tre domande sull'azienda, per esempio sul tirocinio o sul team, e chiedi di nuovo "
                              "se una risposta non è chiara.",
           "doubt": "**Sostegno**: durante il colloquio hai espresso dei dubbi – è del tutto normale. Parlane con l'orientamento professionale, il tuo docente o i tuoi genitori; ti aiutano per le prossime candidature.",
           "support": "**Per finire**: hai detto che i rifiuti ti pesano. È comprensibile. Cerca sostegno da una persona di fiducia – docente, genitori od orientamento professionale; in caso di crisi ti aiuta il 147.",
           "closing": "Era un colloquio di esercitazione – ed è proprio a questo che serve. Ogni volta diventerai più sicuro. "
                      "Continua così!"},
}

PROMPT = (
    "You are an experienced, friendly career counsellor. A 14 to 16 year old has just practised a {situation} for an "
    "apprenticeship as {occupation}. Assess it only from what was said; invent nothing. Write every text field in "
    "{language}, addressed directly to the applicant in the second person singular ({address}); never write about "
    "them in the third person and never use their name. Be encouraging, simple, about behaviour not the person; "
    "never judge nervousness, slips, spelling, dialect or language level.\n"
    "Criteria (keys): {criteria}.\n"
    "Return JSON in this order: overall (2-3 sentences, start with what went well); strengths: 2 objects with text "
    "and quote (exact words); improvements: 1 or 2 objects with text (what to work on), quote (the applicant's exact "
    "weak or general words) and better (a stronger version of that answer using the applicant's own experience from "
    "the transcript); next_step: exactly one concrete practice task; self_doubt: true if the applicant expressed "
    "self-doubt or discouragement (e.g. expects rejection anyway, doubts they can do it), with self_doubt_quote, "
    "their exact words, otherwise false and an empty quote; and last criteria: an object with one entry per key, "
    "each with level (1 insufficient, 2 developing, 3 good, 4 very good, 0 if there was no evidence) and evidence "
    "(5 to 20 of the applicant's words copied exactly from the transcript, no paraphrase), for example "
    "{{\"clarity\": {{\"level\": 3, \"evidence\": \"...exact words...\"}}, ...}}."
)


def rubric_text():
    """The FHGR rubric as compact text: per criterion, what is assessed and the four level descriptions (English)."""
    lines = []
    for k in content.rubric()["criteria"]:
        levels = "; ".join(f'{lv["value"]} = {lv["description"]["en"]}' for lv in k["levels"])
        lines.append(f'- {k["key"]} ({k["what_is_assessed"]["en"]}): {levels}')
    return "\n".join(lines)


def schema(keys):
    """Reply schema for constrained decoding (vLLM json_schema). The criteria are an object with one required entry
    per key (exactly one level per criterion, none repeated or left out) and come last: a model that considers its
    answer complete after a long list would otherwise only be allowed to write whitespace until the token limit."""
    text = {"type": "string", "maxLength": 300}
    quote = {"type": "string", "maxLength": 200}  # a cut quote is still the applicant's own words
    level = {"type": "object", "properties": {"level": {"type": "integer", "enum": [0, 1, 2, 3, 4]},
                                              "evidence": quote},
             "required": ["level", "evidence"], "additionalProperties": False}
    tq = {"type": "object", "properties": {"text": text, "quote": quote},
          "required": ["text", "quote"], "additionalProperties": False}
    imp = {"type": "object", "properties": {"text": text, "quote": quote, "better": text},
           "required": ["text", "quote", "better"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "overall": {"type": "string", "maxLength": 400},
        "strengths": {"type": "array", "items": tq, "minItems": 1, "maxItems": 2},
        "improvements": {"type": "array", "items": imp, "minItems": 1, "maxItems": 2},
        "next_step": text, "self_doubt": {"type": "boolean"}, "self_doubt_quote": quote,
        "criteria": {"type": "object", "properties": {k: level for k in keys}, "required": list(keys),
                     "additionalProperties": False}},
        "required": ["overall", "strengths", "improvements", "next_step", "self_doubt", "self_doubt_quote", "criteria"],
        "additionalProperties": False}


def close_truncated(text):
    """JSON cut off at the token limit (under constrained decoding a model that wants to stop early may only write
    whitespace): drop the incomplete tail back to the last complete value and close the open brackets. Returns the
    parsed object or None. What is missing is then treated as not given (e.g. a criterion without level)."""
    text = text.rstrip()
    for cut in range(len(text), 0, -1):
        if text[cut - 1] not in '}]"0123456789el':  # a complete value ends with one of these
            continue
        head, stack, in_string, escape = text[:cut], [], False, False
        for ch in head:
            if in_string:
                escape, in_string = (not escape and ch == "\\"), in_string and (escape or ch != '"')
                continue
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_string:
            continue
        try:
            data = json.loads(head + "".join(reversed(stack)))
            return data if isinstance(data, dict) else None
        except ValueError:
            continue
    return None


def normalize(data):
    """Accept the shapes a model gives without schema enforcement: criteria as a dict keyed by criterion, levels
    as strings ("3", "Gut", "good"), quotes wrapped in guillemets."""
    data = dict(data or {})
    crit = data.get("criteria")
    if isinstance(crit, dict):
        crit = [dict(v, key=k) if isinstance(v, dict) else {"key": k, "level": v, "evidence": ""} for k, v in crit.items()]
    words = {"insufficient": 1, "ungenügend": 1, "insuffisant": 1, "insufficiente": 1, "developing": 2, "ausbaufähig": 2,
             "à développer": 2, "da sviluppare": 2, "good": 3, "gut": 3, "bien": 3, "buono": 3, "very good": 4,
             "sehr gut": 4, "très bien": 4, "molto buono": 4}
    fixed = []
    for c in crit or []:
        if not isinstance(c, dict):
            continue
        level = c.get("level")
        if isinstance(level, str):
            level = int(level) if level.strip().isdigit() else words.get(level.strip().lower(), 0)
        fixed.append({"key": c.get("key") or c.get("criterion"), "level": level if isinstance(level, int) else 0,
                      "evidence": str(c.get("evidence", "")).strip().strip("«»\"“”„ ")})
    data["criteria"] = fixed
    for part in ("strengths", "improvements"):
        items = data.get(part) if isinstance(data.get(part), list) else []
        fixed = []
        for i in items:
            if isinstance(i, str):  # «Topic: 'their words'» as plain text
                m = re.search(r"[«\"'“„]([^«»\"'“”]{6,})[»\"'”]", i)
                i = {"text": re.split(r"[:–-]\s*[«\"'“„]", i)[0].strip(), "quote": m.group(1) if m else ""}
            if isinstance(i, dict):
                text = next((i[k] for k in ("text", "aspect", "point", "area", "title", "description") if i.get(k)), "")
                fixed.append({"text": str(text).strip(), "quote": str(i.get("quote") or i.get("evidence") or ""),
                              "better": str(i.get("better") or i.get("improved") or i.get("suggestion") or "")})
        data[part] = fixed
    doubt = data.get("self_doubt")
    if isinstance(doubt, dict):  # nested {"self_doubt": true, "self_doubt_quote": "..."}
        data["self_doubt_quote"] = doubt.get("self_doubt_quote") or doubt.get("quote") or data.get("self_doubt_quote")
        data["self_doubt"] = doubt.get("self_doubt", doubt.get("value"))
    return data


def short(quote, words=25):
    """Quotes stay readable: at most 25 words, the rest marked with an ellipsis."""
    parts = str(quote).split()
    return " ".join(parts[:words]) + (" …" if len(parts) > words else "")


def norm(text):
    return re.sub(r"\W+", " ", str(text or "").lower()).strip()


def said(quote, candidate_turns):
    """Whether the quote is the candidate's own words (case and punctuation aside)."""
    q = norm(quote)
    return len(q) >= 3 and any(q in norm(t) for t in candidate_turns)


APPLICANT = r"\b(der Bewerber|die Bewerberin|le candidat|la candidate|il candidato|la candidata)\b"


def texts_of(data):
    """The free-text fields of the feedback contents, with their place."""
    out = [("overall", data.get("overall", "")), ("next_step", data.get("next_step", ""))]
    out += [(f"strengths[{i}]", s.get("text", "")) for i, s in enumerate(data.get("strengths", []))]
    out += [(f"improvements[{i}]", s.get("text", "")) for i, s in enumerate(data.get("improvements", []))]
    return out


ENGLISH = r"\b(the|you|your|and|with|of|to|is|are|this|that|should|could|would|answer|example|responsibility)\b"


def third_person(data, name, lang=None):
    """Fields to rewrite: they talk about the candidate by name or as «the applicant» (third person), or they are
    (partly) in English instead of the interview language."""
    pattern = re.compile(rf"\b{re.escape(name)}\b|{APPLICANT}" if name else APPLICANT, re.I)
    return [k for k, t in texts_of(data)
            if pattern.search(str(t)) or english(t)]


def english(text):
    """At least three English function words, or two in a short heading-like text."""
    hits, words = len(re.findall(ENGLISH, str(text))), len(str(text).split())
    return hits >= 3 or (hits >= 2 and words <= 8)


REWRITE = {
    "de": "«Luca hat …» wird «Du hast …», «er/sie» wird «du», «sein/ihr» wird «dein», «sollte Luca» wird «solltest du»",
    "fr": "«Luca a …» devient «Tu as …», «il/elle» devient «tu», «son/sa» devient «ton/ta»",
    "it": "«Luca ha …» diventa «Hai …», «lui/lei» diventa «tu», «suo/sua» diventa «tuo/tua»",
}
REWRITE_PROMPT = (
    "Rewrite each sentence in {language} (translate it if it is in another language) so that it speaks directly to "
    "the applicant in the second person singular "
    "({address}): {examples}. Keep the meaning, do not use the name. Return JSON with the same keys, each with its "
    "rewritten text.")


def rewrite_schema(fields):
    return {"type": "object", "properties": {f: {"type": "string"} for f in fields}, "required": list(fields),
            "additionalProperties": False}
FALLBACK_OVERALL = {"de": "Danke für das Gespräch – du hast dich gut darauf eingelassen.",
                    "fr": "Merci pour cet entretien – tu t'es bien engagé·e.",
                    "it": "Grazie per il colloquio – ti sei impegnato/a bene."}


def apply_rewrite(data, fields, rewritten, name, lang):
    """Put the rewritten sentences in place; what still talks about the candidate in the third person is dropped
    (overall gets a neutral sentence instead), so the rule holds whatever the model returns."""
    data = dict(data, strengths=[dict(i) for i in data.get("strengths", [])],
                improvements=[dict(i) for i in data.get("improvements", [])])
    rewritten = rewritten if isinstance(rewritten, dict) else {}
    for field in fields:
        text = rewritten.get(field)
        if isinstance(text, str) and text.strip():
            m = re.match(r"(\w+)\[(\d+)\]", field)
            if m:
                data[m.group(1)][int(m.group(2))]["text"] = str(text)
            else:
                data[field] = str(text)
    still = set(third_person(data, name))
    if "overall" in still:
        data["overall"] = FALLBACK_OVERALL[lang]
    if "next_step" in still:
        data["next_step"] = ""
    for part in ("strengths", "improvements"):
        data[part] = [i for n, i in enumerate(data[part]) if f"{part}[{n}]" not in still]
    return data


# FHGR: never judge slips, fillers, dialect or language level. An improvement point that does is dropped.
FORM_CRITIQUE = (r"füllw|\bähm|\bäh\b|«halt»|dialekt|hochdeutsch|mundart|sprachniveau|rechtschreib|grammatik|nervosität|zöger|"
                 r"nervös|leise|lauter|wortschatz|nervos|nervoso|"
                 r"mots? de remplissage|\balors,? je dirais|euh\b|dialecte|"
                 r"in realtà|riempitiv|dialetto|\bboh\b")
# self-deprecation: after the guard has met distress once, such answers are not assessed either
SELF_DEPRECATION = (r"nöd so (schlau|tüchtig|guet)|nicht so (schlau|gut wie)|zu dumm|z dumm|kann (eh |sowieso )?nichts|"
                    r"cha (eh )?nüt|eh nüt bsunders|nichts besonderes|nüt bsunders|(nimmt|nehmen) (mich |mi )?(eh |sowieso )?"
                    r"(niemand|niemert|öpper anders|jemand anders)|bringt (eh |doch )?(nichts|nüt)|was soll's|"
                    r"je suis nul|je ne vaux rien|personne ne (voudra|veut)|ça sert à rien|non valgo|sono negat|"
                    r"non ce la far|nessuno mi")


# Evidence about nervousness, voice, language level or self-devaluation is not admissible for any criterion
# (FHGR M1/L1; restfehler R3): neither a low nor a high level may rest on it.
INADMISSIBLE = (r"nervös|nervos|nervoso|aufgeregt|zitter|stotter|\bsorry\b|\bähm\b|\bäh\b|\beuh\b|leise|lauter sprechen|"
                r"langsamer|plus lentement|più piano|mein deutsch|deutsch (lerne|ist noch|nicht so gut)|wortschatz|"
                r"grammatik|mon français|il mio italiano|stressé|agitat")


def drop_inadmissible_evidence(data):
    """Criteria whose evidence is inadmissible become «not assessed» (level 0, no evidence)."""
    data = normalize(data)
    crit = []
    for c in data.get("criteria", []):
        if re.search(INADMISSIBLE, str(c.get("evidence", "")), re.I) or re.search(SELF_DEPRECATION, str(c.get("evidence", "")), re.I):
            c = dict(c, level=0, evidence="")
        crit.append(c)
    return dict(data, criteria=crit)


def drop_form_critique(data):
    """Improvement points that criticise fillers, dialect or language level are removed (rule, not prompt).
    Quoted words of the applicant do not count, only what the coach itself says."""
    def says(item):
        return re.sub(r"«[^»]*»", "", str(item.get("text", "")))
    data = dict(data, improvements=[i for i in data.get("improvements", []) if not re.search(FORM_CRITIQUE, says(i), re.I)])
    if re.search(FORM_CRITIQUE, str(data.get("next_step", "")), re.I):  # «… ohne Dialekt und mit korrekter Grammatik»
        data["next_step"] = ""
    return data


PHONE = {  # the basic structure of a call asking for a trial apprenticeship, checked by rules on the applicant's words
    "greeting": r"\b(grüezi|guten (tag|morgen|abend)|hallo|grüess|griezi|bonjour|bonsoir|salut|buongiorno|buonasera|salve|ciao)\b",
    "full_name": None,  # first and last name: see full_name()
    "request": r"schnupper|stage|praktikum|tirocinio|anfrag|demande|chiedere|richiesta",
    "week": r"\b(kw|kalenderwoche|semaine|settimana)\s*\d|\b\d{1,2}\.\s*(bis|-|–)\s*\d{1,2}\.|\bvom \d|\bdu \d{1,2}|\bdal \d{1,2}|"
            r"\b(erste|zweite|dritte|letzte|première|deuxième|dernière|prima|seconda|ultima) (\w+ )?(woche|semaine|settimana)|"
            r"\b\d{1,2}\.?\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|"
            r"janvier|février|mars|avril|juin|juillet|août|septembre|octobre|novembre|décembre|gennaio|febbraio|marzo|"
            r"aprile|maggio|giugno|luglio|agosto|settembre|ottobre|dicembre)",
    "thanks": r"\b(danke|merci|grazie)",
    "goodbye": r"tschüss|tschau|auf wiederhören|auf wiedersehen|uf widerluege|adieu|au revoir|bonne (journée|soirée)|"
               r"arrivederci|buona (giornata|serata)|\bciao\b|à bientôt|a presto",
}
PHONE_LABEL = {"de": {"greeting": "Begrüssung", "full_name": "Vor- und Nachname", "request": "Anliegen (Schnupperlehre)",
                      "week": "konkrete Wunschwoche", "thanks": "Dank", "goodbye": "Verabschiedung"},
               "fr": {"greeting": "Salutation", "full_name": "Prénom et nom", "request": "Demande (stage)",
                      "week": "semaine précise souhaitée", "thanks": "Remerciement", "goodbye": "Au revoir"},
               "it": {"greeting": "Saluto", "full_name": "Nome e cognome", "request": "Richiesta (stage)",
                      "week": "settimana precisa desiderata", "thanks": "Ringraziamento", "goodbye": "Saluto finale"}}


def full_name(turns, first_name):
    """A first name followed by a capitalised last name (or two capitalised words after «ich heisse» etc.)."""
    text = " ".join(turns)
    if first_name and re.search(rf"\b{re.escape(first_name)}\s+[A-ZÄÖÜÉÈ][\wäöüéèà'-]{{2,}}", text):
        return True
    return bool(re.search(r"(heisse|heiße|bin|name ist|m'appelle|je suis|mi chiamo|sono)\s+[A-ZÄÖÜÉÈ][\wäöüéèà'-]+\s+"
                          r"[A-ZÄÖÜÉÈ][\wäöüéèà'-]{2,}", text))


def phone_checklist(turns, lang, first_name):
    """✓/○ per element of the call, decided by rules on the applicant's words only (the model ticked a full name
    when only «Ana» was said, error analysis)."""
    lines = []
    for key, label in PHONE_LABEL[lang].items():
        ok = full_name(turns, first_name) if key == "full_name" else bool(
            re.search(PHONE[key], " ".join(turns), re.I))
        lines.append(f"{'✓' if ok else '○'} {label}")
    return lines


PHONE["questions"] = r"\?"  # the applicant asked something back (only in turns after the first)
PHONE_LABEL["de"]["questions"] = "Rückfragen gestellt"
PHONE_LABEL["fr"]["questions"] = "Questions posées"
PHONE_LABEL["it"]["questions"] = "Domande poste"
PHONE_TEXT = {
    "de": {"strength": {"request": "Gut gemacht: Dein Anliegen war klar, man wusste sofort, worum es geht.",
                        "greeting": "Gut gemacht: Du hast freundlich begrüsst und bist gut ins Gespräch gestartet.",
                        "questions": "Gut gemacht: Du hast nachgefragt und Interesse gezeigt.",
                        "none": "Gut, dass du den Anruf geübt hast – das braucht Mut."},
           "tip": "Für den nächsten Anruf: Schreib dir vorher einen Stichwortzettel mit {items}, und leg ihn neben das Telefon.",
           "tip_all": "Für den nächsten Anruf: Leg dir einen Stichwortzettel mit Name, Anliegen und Wunschwoche bereit, dann kann nichts fehlen.",
           "close": "Ein Anruf wird mit jedem Üben leichter. Bleib dran!",
           "items": {"greeting": "einer Begrüssung", "full_name": "deinem Vor- und Nachnamen", "request": "deinem Anliegen",
                     "week": "der Woche, die du dir wünschst", "thanks": "einem Dank", "goodbye": "einer Verabschiedung",
                     "questions": "einer Rückfrage"}, "and": "und"},
    "fr": {"strength": {"request": "Bien joué : ta demande était claire, on a tout de suite compris de quoi il s'agit.",
                        "greeting": "Bien joué : tu as salué poliment et bien commencé l'appel.",
                        "questions": "Bien joué : tu as posé des questions et montré ton intérêt.",
                        "none": "C'est bien d'avoir entraîné cet appel – il faut du courage."},
           "tip": "Pour le prochain appel : prépare un petit aide-mémoire avec {items}, et garde-le près du téléphone.",
           "tip_all": "Pour le prochain appel : garde un aide-mémoire avec ton nom, ta demande et la semaine souhaitée.",
           "close": "Chaque appel devient plus facile avec l'entraînement. Continue comme ça !",
           "items": {"greeting": "une salutation", "full_name": "ton prénom et ton nom", "request": "ta demande",
                     "week": "la semaine souhaitée", "thanks": "un remerciement", "goodbye": "une formule pour prendre congé",
                     "questions": "une question à poser"}, "and": "et"},
    "it": {"strength": {"request": "Ben fatto: la tua richiesta era chiara, si capiva subito di che cosa si tratta.",
                        "greeting": "Ben fatto: hai salutato con gentilezza e hai iniziato bene la chiamata.",
                        "questions": "Ben fatto: hai fatto delle domande e mostrato interesse.",
                        "none": "È bello che tu abbia provato la chiamata – ci vuole coraggio."},
           "tip": "Per la prossima chiamata: preparati un foglietto con {items}, e tienilo vicino al telefono.",
           "tip_all": "Per la prossima chiamata: tieni pronto un foglietto con nome, richiesta e settimana desiderata.",
           "close": "Ogni chiamata diventa più facile con l'esercizio. Continua così!",
           "items": {"greeting": "un saluto", "full_name": "il tuo nome e cognome", "request": "la tua richiesta",
                     "week": "la settimana che desideri", "thanks": "un ringraziamento", "goodbye": "un saluto finale",
                     "questions": "una domanda da fare"}, "and": "e"},
}


def phone_feedback(turns, lang, first_name):
    """Phone-call feedback from templates only (restfehler R1): one strength, the checklist, a tip for at most the
    two most important missing elements, an encouraging close. No model text, so nothing can be lost or invented."""
    text = " ".join(turns)
    later = " ".join(turns[1:])
    ok = {}
    for key in PHONE_LABEL[lang]:
        if key == "full_name":
            ok[key] = full_name(turns, first_name)
        elif key == "questions":
            ok[key] = "?" in later
        else:
            ok[key] = bool(re.search(PHONE[key], text, re.I))
    t = PHONE_TEXT[lang]
    strength = next((t["strength"][k] for k in ("request", "greeting", "questions") if ok[k]), t["strength"]["none"])
    checklist = [f"{'✓' if ok[k] else '○'} {PHONE_LABEL[lang][k]}" for k in PHONE_LABEL[lang]]
    missing = [k for k in ("full_name", "week", "request", "greeting", "thanks", "goodbye") if not ok[k]][:2]
    if missing:
        names = [t["items"][k] for k in missing]
        tip = t["tip"].format(items=f" {t['and']} ".join(names))
    else:
        tip = t["tip_all"]
    return "\n".join([strength, ""] + checklist + ["", tip, "", t["close"]])


def drop_english_better(data):
    """A «better formulation» in English (seen: «I take responsibility …» in a French interview) is left out."""
    return dict(data, improvements=[dict(i, better="") if english(i.get("better", "")) else i
                                    for i in data.get("improvements", [])])


def problems(data, name):
    """The rules the model's contents break (each becomes one line of the repair request)."""
    data = normalize(data)
    out = []
    if not isinstance(data.get("criteria"), list) or not data["criteria"]:
        out.append("criteria is missing")
    if not data.get("improvements"):
        out.append("improvements is missing (1 or 2 items)")
    elif not any(str(i.get("better", "")).strip() for i in data["improvements"]):
        out.append("no improvement has a better formulation in 'better'")
    return out


def assemble(data, context, candidate_turns, facts):
    """The final feedback text: rules write the frame and the mandatory blocks, the model's contents fill it."""
    data = normalize(data)
    lang = context["lang"]
    t, levels = T[lang], LEVELS[lang]
    crit = {k["key"]: k for k in content.rubric()["criteria"]}
    lines = [f"**{t['overall']}**", str(data.get("overall", "")).strip(), "", f"**{t['table']}**", "", t["cols"], "|---|---|---|"]
    by_key = {c.get("key"): c for c in data.get("criteria", []) if isinstance(c, dict)}
    for key, k in crit.items():
        c = by_key.get(key, {})
        level = c.get("level") if isinstance(c.get("level"), int) and 0 <= c.get("level") <= 4 else 0
        ev = str(c.get("evidence", "")).strip().strip("«»\"")
        if level == 0 or not ev:
            evidence, level = "–", 0
        elif said(ev, candidate_turns):
            evidence = f"«{short(ev, 20)}»"
        else:
            evidence = f"({t['para']}) {ev}"
        label = k["label"].get(lang, k["label"]["de"])
        lines.append(f"| {label} | {levels[level]} | {evidence.replace('|', '/')} |")
    if data.get("strengths"):
        lines += ["", f"**{t['strengths']}**"]
    for s in (data.get("strengths") or [])[:2]:
        q = str(s.get("quote", "")).strip().strip("«»\"")
        lines.append(f"- {str(s.get('text', '')).strip()}" + (f" («{short(q)}»)" if q and said(q, candidate_turns) else ""))
    improve_at = len(lines)
    for s in (data.get("improvements") or [])[:2]:
        lines.append(f"- {str(s.get('text', '')).strip()}")
        q = str(s.get("quote", "")).strip().strip("«»\"")
        if q and said(q, candidate_turns):
            lines.append(f"  {t['said']}: «{short(q)}»")
        if str(s.get("better", "")).strip():
            lines.append(f"  {t['better']}: «{str(s['better']).strip().strip('«»\"')}»")
    # self-doubt counts only with the applicant's own words as evidence (rule), and only when no distress was handled
    doubt = data.get("self_doubt") is True or str(data.get("self_doubt", "")).strip().lower() == "true"
    facts = dict(facts, doubt=bool(not facts.get("support") and doubt
                                    and said(data.get("self_doubt_quote", ""), candidate_turns)))
    # FHGR R2: at most two points to work on. Order: the model's first point, the situation's mandatory tip
    # (answer pattern, presentation, online), the model's second point, the own-questions tip. Support notes are
    # not points to work on and always stay.
    model_points = lines[improve_at:]
    lines = lines[:improve_at]
    groups = [[f"- {t[f]}"] for f in ("pattern", "presentation", "online") if facts.get(f)]
    split = [i for i, line in enumerate(model_points) if line.startswith("- ")] + [len(model_points)]
    items = [model_points[a:b] for a, b in zip(split, split[1:])]
    ordered = items[:1] + groups + items[1:] + [[f"- {t[f]}"] for f in ("questions", "questions_asked") if facts.get(f)]
    for item in ordered[:2]:
        lines += item
    for fact in ("support", "doubt"):
        if facts.get(fact):
            lines.append(f"- {t[fact]}")
    if len(lines) > improve_at:  # improvement points or mandatory blocks
        lines[improve_at:improve_at] = ["", f"**{t['improve']}**"]
    step = str(data.get("next_step", "")).strip()
    lines += (["", f"**{t['next']}**", step] if step else []) + ["", t["closing"]]
    return "\n".join(lines)


def facts_of(context, record, guard_events=()):
    """Facts of this conversation that make a feedback block mandatory."""
    # the company answer runs after every closing question; whether the applicant really asked one is the rule's call
    asked_own_question = any(e["tool"] == "_company_answer" and e.get("output", {}).get("asked", True) for e in record)
    company = any(e["tool"] == "_company_answer" for e in record)
    distress = any(g.get("kind") == "distress" for g in guard_events)
    return {"support": distress, "pattern": bool(context.get("flags")), "presentation": context.get("situation") == "assessment",
            "online": context.get("situation") == "online_interview", "questions": not asked_own_question,
            "questions_asked": asked_own_question and company}


# ---- spoken feedback (voice mode): the same checked contents, rendered for text-to-speech -------------------------
SPOKEN = {
    "de": {"good": "Besonders gut", "also": "Auch gut", "said": "zum Beispiel, als du gesagt hast", "two": "Zwei Dinge kannst du beim nächsten Mal ausprobieren.",
           "one": "Eine Sache kannst du beim nächsten Mal ausprobieren.", "first": "Erstens", "second": "Zweitens",
           "could": "Du könntest zum Beispiel sagen", "next": "Dein nächster Schritt"},
    "fr": {"good": "Ce qui était particulièrement bien", "also": "Bien aussi", "said": "par exemple quand tu as dit", "two": "Tu peux essayer deux choses la prochaine fois.",
           "one": "Tu peux essayer une chose la prochaine fois.", "first": "Premièrement", "second": "Deuxièmement",
           "could": "Tu pourrais dire par exemple", "next": "Ta prochaine étape"},
    "it": {"good": "Particolarmente bene", "also": "Bene anche", "said": "per esempio quando hai detto", "two": "La prossima volta puoi provare due cose.",
           "one": "La prossima volta puoi provare una cosa.", "first": "Primo", "second": "Secondo",
           "could": "Potresti dire per esempio", "next": "Il tuo prossimo passo"},
}


def plain(text):
    """No markdown for a voice: bold markers and table pipes removed."""
    return re.sub(r"\*\*([^*]+)\*\*\s*:?\s*", r"\1: ", str(text)).replace("|", " ").strip()


def sentence(text):
    text = str(text).strip()
    return text if not text or text[-1] in ".!?" else text + "."


def assemble_spoken(data, context, candidate_turns, facts):
    """Spoken feedback in short sentences, like FHGR's examples F-27/F-28: overall impression, what went well with
    the candidate's own words, at most two things to try, the mandatory hints, one next step, the closing."""
    data = normalize(data)
    lang = context["lang"]
    t, w = T[lang], SPOKEN[lang]
    doubt = data.get("self_doubt") is True or str(data.get("self_doubt", "")).strip().lower() == "true"
    facts = dict(facts, doubt=bool(not facts.get("support") and doubt
                                    and said(data.get("self_doubt_quote", ""), candidate_turns)))
    parts = [sentence(data.get("overall", ""))]
    for i, s in enumerate((data.get("strengths") or [])[:2]):
        q = str(s.get("quote", "")).strip().strip("«»\"")
        text = str(s.get("text", "")).strip().rstrip(".")
        evidence = f", {w['said']}: «{short(q, 15)}»" if q and said(q, candidate_turns) else ""
        parts.append(f"{w['good'] if i == 0 else w['also']}: {text}{evidence}.")
    improvements = (data.get("improvements") or [])[:2]
    if improvements:
        parts.append(w["two"] if len(improvements) == 2 else w["one"])
        for i, s in enumerate(improvements):
            lead = f"{w['first'] if i == 0 else w['second']}: " if len(improvements) == 2 else ""
            parts.append(sentence(f"{lead}{str(s.get('text', '')).strip()}"))
            if str(s.get("better", "")).strip():
                parts.append(f"{w['could']}: «{short(str(s['better']).strip().strip('«»'), 25)}»")
    for fact in ("support", "doubt", "pattern", "presentation", "online", "questions", "questions_asked"):
        if facts.get(fact):
            parts.append(plain(t[fact]))
    if str(data.get("next_step", "")).strip():
        parts.append(f"{w['next']}: {sentence(data['next_step'])}")
    parts.append(t["closing"])
    return " ".join(p for p in parts if p)


# ---- observations collected during the interview (FrameX decides what the feedback is about) ----------------------
# The rules that steered the interview (R1 concrete example, R1b company, R1c step) also decide, per answer, what is
# a strength and what is still open. FrameX picks one strength and at most two points to work on from them; the
# model only words them. The evidence comes from decisions made during the interview, not from searching the
# transcript afterwards (the rejected two-stage feedback).
# the parts of a good example answer: situation, own contribution, result (what came out, what was learnt)
OWN = {"de": r"\b(ich (habe|hab|ha|bin|han)|habe ich|hab ich|han i|i ha|ich \w+te\b|machte ich|half ich)\b",
       "fr": r"\b(j'ai|je suis allée?|je me suis|j'étais)\b", "it": r"\b(ho|sono stat[oa]|mi sono)\b"}
RESULT = {"de": r"\b(am ende|am schluss|danach|daraus|gelernt|gemerkt|hat (dann )?(funktioniert|geklappt|gelobt)|"
                r"ergebnis|erfolg|geschafft|lob|stolz|seither|seitdem|funktioniert)\b",
          "fr": r"\b(à la fin|ensuite|j'ai appris|j'ai compris|résultat|réussi|ça a marché|fier|fière|depuis)\b",
          "it": r"\b(alla fine|poi|ho imparato|ho capito|risultato|riuscit[oa]|ha funzionato|orgoglios[oa]|da allora)\b"}
TOPIC = {"result": ("", "what came out of your example (the result or what you learnt)"),
         "own_part": ("", "what you did yourself in your example"),
         "example": ("a concrete example from your own experience", "a concrete example (what happened, what you did)"),
         "company": ("what you know about the company", "concrete knowledge about the company and why it fits you"),
         "step": ("a concrete step against your weakness", "a concrete step you take against your weakness"),
         "own": ("naming your own part honestly", "naming your own part and what you do differently now")}


def best_sentence(text, lang):
    """The sentence of an answer with the most concrete markers (something done, when, where, how much)."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?…])\s+", text or "") if len(x.split()) >= 5
             and not re.search(INADMISSIBLE, x, re.I) and not re.search(SELF_DEPRECATION, x, re.I)]
    if not sents:
        return ""
    return short(max(sents, key=lambda x: concreteness(x, lang)), 25)


def concreteness(text, lang):
    """Markers of something done, numbers, names (capitalised words not at the start), a little length."""
    from . import rules
    names = len(re.findall(r"(?<=\s)[A-ZÄÖÜ][\w-]{2,}", text)) if lang != "de" else len(re.findall(r"\b[A-Z][a-z]*[A-Z-]\w*", text))
    return (2 * len(re.findall(rules.NARRATIVE[lang], text, re.I)) + len(re.findall(r"\d", text)) + names
            + min(len(text.split()), 30) / 30)


def observations(record, context, excluded=()):
    """(strength, points): strength = (topic, quote) or None; points = [(topic, quote), …] at most two.
    Decided by the same rules that steered the interview, on each answer and on the answer to its follow-up."""
    from . import content, rules
    lang = context["lang"]
    mode_of = {}
    for qid, mode in content.plan(context):
        q = content.questions().get(qid)
        if q and mode:
            mode_of[q["text"][lang]] = mode
    follow_of = {content.TEXT[lang][k]: k for k in ("example", "company", "step", "own")}
    def decide(mode, answer):
        if mode == "example":
            return rules.concrete(answer, lang)[0]
        if mode == "company":
            return rules.company_specific(answer, context)[0]
        if mode == "step":
            return rules.step_concrete(answer, lang)[0]
        return None
    items = []  # (mode, main answer, ok, follow-up answer, ok after follow-up)
    for e in record:
        o = e.get("output", {})
        if e.get("tool") not in ("_turn", "_repairTurn") or "answer" not in o or o["answer"] in excluded:
            continue
        if re.search(SELF_DEPRECATION, o["answer"], re.I):  # never quoted, neither as strength nor as point
            continue
        q, a = o.get("question", ""), o["answer"]
        if q in mode_of and mode_of[q] in ("example", "company", "step"):
            items.append([mode_of[q], a, decide(mode_of[q], a), None, None])
        elif q in follow_of and items and items[-1][0] == follow_of[q] and items[-1][3] is None:
            items[-1][3], items[-1][4] = a, decide(follow_of[q], a)
    strong = [(m, a) for m, a, ok, fa, fok in items if ok] + [(m, fa) for m, a, ok, fa, fok in items if fok]
    strength = None
    if strong:
        m, a = max(strong, key=lambda x: concreteness(best_sentence(x[1], lang), lang))
        quote = best_sentence(a, lang)
        strength = (TOPIC[m][0], quote) if quote else None
    order = {"example": 0, "own_part": 1, "result": 2, "step": 3, "company": 4}
    open_ = sorted([(m, a) for m, a, ok, fa, fok in items if not ok and not fok], key=lambda x: order[x[0]])
    # a concrete example that still lacks the applicant's own part or the result: a precise point to work on
    for m, a in strong:
        if m == "example" and not any(x[0] == "example" for x in open_):
            if not re.search(OWN[lang], a, re.I):
                open_.append(("own_part", a))
            elif not re.search(RESULT[lang], a, re.I):
                open_.append(("result", a))
    open_.sort(key=lambda x: order[x[0]])
    points, seen = [], set()
    for m, a in open_:
        if m not in seen:
            seen.add(m)
            # own part / result refer to the example already quoted as the strength: no second quote of it
            quote = "" if m in ("own_part", "result") or re.search(INADMISSIBLE, a, re.I) else short(a, 25)
            points.append((TOPIC[m][1], quote))
    return strength, points[:2]


def observations_text(strength, points):
    lines = ["Observations decided during the interview (use exactly these; do not choose other topics):"]
    if strength:
        lines.append(f"- Strength: {strength[0]}. Their words: «{strength[1]}»")
    for i, (topic, quote) in enumerate(points, 1):
        lines.append(f"- Point to work on {i}: {topic}." + (f" Their words: «{quote}»" if quote else " (in the example above)"))
    lines.append("Write strengths[0] about the strength; write improvements in this order about these points, each "
                 "with a better version built from the applicant's own experience; next_step practises point 1.")
    return "\n".join(lines)


def apply_observations(data, strength, points):
    """Rules: the selected quotes are the evidence of the matching strength and improvement points."""
    data = dict(data, strengths=[dict(i) for i in data.get("strengths", [])],
                improvements=[dict(i) for i in data.get("improvements", [])])
    if strength and data["strengths"]:
        data["strengths"][0]["quote"] = strength[1]
    for i, (_, quote) in enumerate(points[:len(data["improvements"])]):
        if quote:
            data["improvements"][i]["quote"] = quote
    if points and not data["improvements"]:
        data["improvements"] = [{"text": "", "quote": q, "better": ""} for _, q in points]
    data["improvements"] = data["improvements"][:max(len(points), 1)] if points else data["improvements"]
    return data
