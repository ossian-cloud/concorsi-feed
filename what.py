"""The job a call is for, without the procedural words in front of it.
inPA titles mostly open with boilerplate ("Concorso pubblico, per titoli ed esami, per la copertura a tempo
pieno e indeterminato di n. 2 posti di..."). For lists and feed titles I strip a chain of such fillers from
the start and keep one word for the kind of procedure: "Concorso: n. 2 posti di...". Only official words
are removed, never added; when too little would be left, the title stays as it is."""
import re

import titles

KIND = re.compile(r"(?:(?:bando|indizione|avviso|avvio|riapertura (?:dei )?termini|pubblico|procedura|di|del|dell['’]|per|relativo al(?:la)?)\s+)*"
                  r"(concorso|concorsi|selezione|procedura (?:concorsuale|selettiva|comparativa)|mobilit[aà]|stabilizzazione|avviso|bando|interpello)\b", re.I)
FILLERS = [re.compile(p, re.I) for p in [
    r"(?:anche|intercompartimentale|intracompartimentale|esterna|interna|esterno|interno)\b(?:\s+e\s+(?:compartimentale|interuniversitaria))?",
    r"(?:del|dei) compart[oi] (?:funzioni locali|sanit[aà]|universit[aà]|istruzione e ricerca|funzioni centrali)(?:\s+(?:e|ed)\s+intercompartimentale)?\b",
    r"(?:e|ed)\s+(?:interregionale|intercompartimentale|compartimentale|non vincolante|volontaria|esterna)\b",  # "mobilità regionale ed interregionale"
    r"(?:e|ed)\s+(?:per\s+)?(?:soli\s+)?(?:titoli|esami|esame|colloquio|prova[- ]colloquio|valutazione (?:dei )?titoli)\b",  # "per titoli e per esami"
    r"(?:e|ed)\s+(?:dell['’]\s*|del(?:l['’])?\s+)?art\.?\s*\d+\s+del\s+(?:CCNL(?:\s+\d{4}/\d{4})?(?:\s+del\s+comparto\s+\w+)?|R\.O\.U\.S\.)",  # "e dell’art. 57 del CCNL 2006/2009"
    r"(?:ex\.?\s+)?(?:art\.?|articolo)\s*30\b.{0,80}?\b165(?:/\d{2,4})?(?=\W)",  # "art. 30, comma 2-bis D.Lgs. 165/2001"
    r"nel\s+comune\s+di\s+(?-i:[A-Z]\w+(?:\s+[A-Z]\w+)?),",
    r"(?:pubblic[oa]|ordinari[oa]|unic[oa]|esterna|volontaria|interna|(?:tra|fra) (?:aziende ed? enti|enti(?: pubblici)?|p\.?a\.?|pp\.?aa\.?|pubbliche amministrazioni|amministrazioni pubbliche|amministrazioni)"
    r"|unificat[oa]|congiunt[oa]|regionale|interregionale|nazionale|comparativa|selettiva|concorsuale|straordinari[oa]|esplorativ[oa]|in entrata)\b",
    r"(?:di|per|mediante|ai fini del(?:la)?|finalizzat[oa] al(?:la|l['’])?|volt[oa] al(?:la|l['’])?)\b",
    r"(?:soli\s+)?(?:titoli|esami|esame|colloquio|prova (?:pratica|scritta|orale))(?:\s+(?:e|ed)\s+(?:eventuale\s+)?(?:titoli|esami|esame|colloquio|prova (?:pratica|scritta|orale)))?(?:\s+pratic[oa])?\b",
    r"\(?(?:ai sensi|ex\.?) (?:dell['’]\s*|degli |dell )?art.{0,80}?(?:\d{4}|(?:165|267)(?:/\d{2,4})?)\b(?:,?\s*n\.?\s*\d+\b)?\)?",
    r"(?:assunzione|copertura)(?=\s+(?:di|dei|delle|della|a tempo)\b.*(?:\d|\bun[oa]?\b|\bposti?\b|\bunit))",
    r"(?:la copertura|la stabilizzazione|l['’]\s*assunzione|il reclutamento|il conferimento|l['’]affidamento|la stipula)\b",
    r"(?:a\s+)?tempo (?:pieno|parziale|indeterminato|determinato)(?:\s*\([^)]{1,30}\))?(?:\s*(?:e|ed|/)?\s*(?:a tempo\s+)?(?:pieno|parziale|indeterminato|determinato)(?:\s*\([^)]{1,30}\))?)*",
    r"\(\s*\d+\s*(?:h|ore)\b[^)]{0,20}\)",  # "(20 ore settimanali)"
    r"(?:\d+\s*)?ore(?:\s+settimanali)?\b(?:\s+estendibil\w*\s+a\s+\d+\s*ore(?:\s+settimanali)?)?",  # "18 ore settimanali" left by "a tempo parziale"
    r"(?:e|ed)\s+(?:in)?determinat[oa]\b",
    r"(?:al|con percentuale(?: pari)? al)\s*\d+\s*%",  # "al 50%": part time
    r"(?:e\s+)?part[- ]?time\b(?:\s*\(?\s*(?:al\s*)?\d+(?:[.,]\d+)?\s*%\s*\)?)?",  # "part time (50%)"
    r"(?:per\s+(?:la durata di\s+)?)?(?:\d+|un|uno|due|tre|sei|dodici|diciotto|ventiquattro|trentasei)\s+(?:mesi|mese|anno|anni)\b(?:\s+(?:eventualmente\s+)?(?:rinnovabil|prorogabil)\w*)?",
    r"a(?=\s+n\.?\s*\d)",  # "a n. 1 posto"
    r"(?:e|ed)\s+(?=a tempo|a orario|orario|a pieno|pieno)",  # "e a orario pieno": the rest of a contract phrase
    r"(?:a\s+)?orario\s+(?:pieno|ridotto|parziale)(?:\s*(?:e|ed)\s+(?:indeterminato|determinato))?",
    r"(?:e\s+)?(?:s\.?\s?m\.?\s?i\.?|ss\.?\s?mm\.?\s?(?:e\s+)?ii\.?)",
    r"n?\.?\s*\d+/\d+\.?(?=\s)",  # a reference number, "43994/2026."
    r"[,:;.–—/-]",
]]
LEFTOVER = re.compile(r"(?:e|ed|o|del|della|dei|degli|ai sensi|art\.?|ex)(?=\s)|dell['’]", re.I)  # a phrase cut in half: keep the title whole
RANK = ["Avviso", "Interpello", "Selezione", "Stabilizzazione", "Concorso", "Mobilità"]  # the more specific word wins


def kind_of(word):
    word = word.lower()
    return ("Mobilità" if word.startswith("mobilit") else "Concorso" if word.startswith("concors") else
            "Interpello" if word.startswith("interpello") else "Selezione" if word.startswith(("selezione", "procedura")) else "Stabilizzazione" if word.startswith("stabil") else "Avviso")


LEAD = re.compile(r"\s[–—-]\s*|[.:_]\s*|,\s+|\s*-(?=[a-z])")  # "Comune di Bergamo – ", "Comune di X. ", "Comune di X, concorso"
ENTE = re.compile(r"(?:comune|provincia|citt[àa]|unione|azienda|asl|asst|ausl|università|universita|conservatorio|accademia|istituto|"
                  r"fondazione|regione|ministero|i\.?r\.?c\.?c\.?s\.?|aou|aulss|ulss|ats|asp|ente|consorzio|comunità|camera|politecnico|scuola)\b", re.I)
KEEP_UPPER = {"AFAM", "ASL", "ASP", "ASST", "OSS", "ICT", "CED", "PNRR", "ATA", "SUAP", "URP", "ZTL", "CCNL", "DPR", "ISEE", "IRCCS", "AOU", "AUSL", "ULSS", "AULSS", "UOC", "UOSD", "USL"}
CONTRACT = (r"(?:a tempo\s+(?:pieno|parziale|indeterminato|determinato)|a pieno|pieno|indeterminato|determinato|parziale|a orario\s+\w+|orario\s+\w+)"
            r"(?:\s*(?:\([^)]{1,30}\)|e|ed|/|,)?\s*(?:a tempo\s+)?(?:pieno|parziale|indeterminato|determinato|a orario\s+\w+|orario\s+\w+|full[- ]time|part[- ]time|\d+\s*ore(?:\s+settimanali)?))*")
MIDDLE = re.compile(r"\b((?:n\.?\s*|nr\.?\s*|n°\s*)?(?:\d+|un[oa]?|due|tre|quattro|cinque|sei)\s*(?:\(\w+\)\s*)?(?:posti|posto|unit[aà])),?\s+" + CONTRACT +
                    r",?\s+(?=(?:di|da|in qualità di|nel profilo|con il profilo|con profilo|nell['’]area|area)\b)", re.I)


KNOWN = re.compile(r"(?:posto|posti|unit[aà]|area|tecnic|amministrativ|profil|tempo|indetermin|determin|contratt|dipartiment|serviz|settore|manutentiv|esperto|esperti)")
ROMAN = re.compile(r"^(?:II|III|IV|VI|VII|VIII|IX|XI|XII)\W*$")


def unshout(t):
    """Capitals left in a title that is otherwise in lower case: "n. 3 POSTI A TEMPO INDETERMINATO" -> lower case. Acronyms stay;
    places are restored. Only runs of two or more capitalised words, or one long one (6+ letters), are touched."""
    words = t.split(" ")

    def up(w):
        c = re.sub(r"['’/]", "", w.strip(",;:/–-()“”\"'’."))
        return c.isalpha() and c.isupper() and c not in KEEP_UPPER and (len(c) > 1 or c in "AEOI") and not re.search(r"\.", w.strip(",;:"))
    i, out = 0, list(words)
    while i < len(words):
        if not up(words[i]):
            i += 1
            continue
        j = i
        while j < len(words) and up(words[j]):
            j += 1
        run = words[i:j]
        big = [w for w in run if len(w.strip(",;:/–-()“”\"'’.")) > 1]
        if len(big) >= 2 and any(len(w.strip(",;:/–-()“”\"'’.")) >= 5 for w in big) or (len(big) == 1 and KNOWN.match(big[0].strip(",;:/–-()“”\"'’.").lower())):
            out[i:j] = [w if ROMAN.match(w) else w.lower() for w in run]
        i = j
    return titles.restore_places(" ".join(out))


TEMP = re.compile(r"(?<!in)determinat|\b(?:mesi|mese|anno|anni)\b", re.I)
PART = re.compile(r"parzial|part[- ]?time|ridott|%|\b(?:[1-9]|[12]\d|3[0-5])\s*ore\b", re.I)  # 36 hours a week is full time


def contract(dropped):
    """What the stripped contract words said, when it isn't the default (permanent, full time): ' a tempo determinato'."""
    text = " ".join(dropped)
    kinds = [w for w, rx in (("determinato", TEMP), ("parziale", PART)) if rx.search(text)]
    return " a tempo " + " e ".join(kinds) if kinds else ""


def what(t):
    t = " ".join(t.split())
    dropped = []
    if not KIND.match(t):  # an ente's name in front, then the procedure
        for lead in LEAD.finditer(t[:90]):
            comma = lead.group(0)[0] in ",-"  # a bare comma or hyphen: only after an ente's name
            if lead.start() >= 3 and KIND.match(t[lead.end():]) and (not comma or ENTE.match(t)):
                t = t[lead.end():]
                break
        else:  # "Accademia belle arti urbino selezione pubblica ...": no separator, but an ente word first
            m = ENTE.match(t)
            k = m and re.search(r"\s(?=(?:selezione|concorso|avviso|bando|procedura|mobilit[aà])\s)", t[:80], re.I)
            before = k and t[:k.start()].split()[-1].lower().strip(",.:")
            if k and not re.search(r"\d", t[:k.start()]) and before not in titles.SMALL:
                t = t[k.end():]
    kind, rest = None, t
    for _ in range(4):  # "Avviso di procedura di mobilità volontaria, ai sensi..." -> Mobilità
        m = KIND.match(rest)
        if not m:
            break
        k = kind_of(m.group(1))
        kind = k if kind is None or RANK.index(k) > RANK.index(kind) else kind
        rest, changed = rest[m.end():].lstrip(), True
        while changed:
            changed = False
            for rx in FILLERS:
                f = rx.match(rest)
                if f and f.end():
                    dropped.append(f.group(0))
                    rest, changed = rest[f.end():].lstrip(), True
    if kind is None or len(rest) < 15 or LEFTOVER.match(rest) or (len(t) - len(rest) < 12 and not re.match(r"(?:n\.?|nr\.?|\d+|un[oa]?)\s(?!\s*\d+\s+del\b)", rest, re.I)):
        t = unshout(t)
        return t[:1].upper() + t[1:]
    m = MIDDLE.search(rest)
    if m:
        dropped.append(m.group(0)[len(m.group(1)):])
        rest = rest[:m.start()] + m.group(1) + " " + rest[m.end():]
    rest = unshout(rest)
    return f"{kind}{contract(dropped)}: {rest[:1].lower() + rest[1:] if not rest[:2].isupper() else rest}"


# The job alone, for JobPosting.title: after "n. 2 posti di" up to the first area, contract or punctuation.
POSTS = re.compile(r"\b(?:(?:n\.?\s*|nr\.?\s*|numero\s+)?(?:\d+|un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\s*)?(?:\(\w+\)\s*)?"
                   r"(?:posti|posto|unit[aà]|figur[ae]|incarichi|incarico|borse?(?: di studio)?)\s+(?:(?:di|per|a|da)\s+)?(?:(?:profilo|profili)\s+(?:professionale\s+)?(?:di\s+)?)?", re.I)
ROLE_END = re.compile(r"\s+(?:a tempo|con contratto|area\b|cat\.|categoria|presso|da assegnare|da destinare|nel(?:l['’]|la|lo|le)?\s|per (?:il|la|l['’]|le|i|gli)\s|ccnl|del ruolo|ruolo|livello|comparto|-\s|–|—|ai sensi|riservat|\(|ex\s)|\s+(?:di cui|a\.a\.|art\.|afam\s*\d*\b|e\.?q\.?(?=\s|$)|comune di|triennio|in libera professione|tempo\b|\d+\s*%)|\s+(?:nei|negli|in possesso|dpr|d\.p\.r|inquadrat[oa]|appartenente|da (?:collocare|inquadrare|adibire|impiegare)|part[- ]time|ed e\.?\s?q|-)\b|\s+[“-]|[–—_]|\s+con\s+(?:conoscenze|riserva)|\s+di [IVX]+\b|\s+[IVX]+\s+liv|[;:(,”\x22»]", re.I)
ROLE_FILLER = re.compile(r"\s*(?:a tempo (?:pieno|parziale|indeterminato|determinato|intederminato)(?:\s*(?:e|ed|/)\s*(?:a tempo\s+)?(?:pieno|parziale|indeterminato|determinato))*(?:\s*\([^)]{1,40}\))?"
                 r"|(?:di|del|nel|nell['’]|con(?: il)?|il|al|alla|in|per)\s+(?=(?:profilo|personale|qualifica|ruolo)\b)|(?:profilo|qualifica)(?: professionale)?(?: di)?\b|personale\b(?: (?:con|nel|di))?"
                 r"|(?:di|del)\s+(?=\S)|[“”\"«»,]\s*)\s*", re.I)
JOB_NOUN = re.compile(r"(?:funzionari|istruttor|dirigent|operator|assistent|agent|specialist|tecnic|collaborator|esecutor|infermier|medic|ricercator|docent|educat|autist|operai|ingegner|architett|geometr|psicolog|farmacist|veterinar|ostetric|fisioterapist|logopedist|biolog|chimic|avvocat|commissari|ispettor|vigil|bibliotecari|cuoc|maestr|insegnant|professor|accompagnator|gestor|espert|analist|addett|coordinat|responsabil|segretari|comandant|ufficial|sottufficial|cantonier|necrofor|elettricist|idraulic|giardinier|tecnolog|dietist|ortottist|puericultr|ausiliari|commess|impiegat|archivist|statistic|economist|giornalist|interpret|tradutt|programmator|sistemist|perit|direttor|primari|pediatr|dentist|odontoiatr|psicoterapeut|sociolog|geolog|agronom|forestal|guardi|custod|portier|usciere|centralinist|magazzinier|manutentor|meccanic|conducent|macchinist|marinai|carpentier|muratore|fabbro|falegnam|pittor|restaurator|curator|musicist|orchestral|lettor|consulent)", re.I)

HEADCOUNT = re.compile(r"(?:^|\bn\.?\s*\d+\s*|\b(?:\d+|un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\s+)(?:\(\w+\)\s*)?(?=" + JOB_NOUN.pattern + ")", re.I)

TAIL = re.compile(r"(?:\s+(?:e|ed|di|del|della|dei|nel|nei|per|con|in|a|da|o)|[\s\-–/.,]+)+$", re.I)  # "Funzionario tecnico-", "…nell'Ambiente e"
ACRONYMS = {"AFAM", "ASL", "ASP", "ASST", "OSS", "ICT", "CED", "PNRR", "ATA", "SUAP", "URP", "ZTL"}


LIST_ONLY = re.compile(r"\b(?:graduatori[ae]|elenc[ohi]|alb[oi]|idone[io]|manifestazione|interesse|progressione|stabilizzazione|aggiornamento|categorie)\b", re.I)  # not a post
COUNTISH = re.compile(r"\b(?:posti?|posizion[ei]|unit[aà]|figur[ae]|incarich[oi]|collaborazion[ei]|risors[ae]|person[ae])\b", re.I)
PROFILO = re.compile(r"\bprofilo(?:\s+professionale)?(?:\s+di)?\s+(?=[“\"«]?" + JOB_NOUN.pattern + ")", re.I)
STARTS = re.compile(r"(?=[“\"«]?" + JOB_NOUN.pattern + ")", re.I)  # the title opens with the job itself


def finish(t, fallback=False, quoted=False):
    """From the text right after the job's introducer to a clean job title, or None; fallback: stricter, see FB_STARTS."""
    t = re.sub(r"^(?:un[oa]?|n\.?\s*\d+)\s+", "", t)
    for _ in range(5):
        p = ROLE_FILLER.match(t)
        if not p or not p.end():
            break
        t = t[p.end():]
    s = ROLE_END.search(t)
    if s and fallback and (FB_BAD.match(t, s.start()) or quoted and t[s.start()] in ",;" or not FB_DASH.match(t, s.start()) and t[s.start():].lstrip()[:1] in "–—-"):
        return None  # cut in the middle of the job's own name
    if s:
        t = t[:s.start()]
    s = fallback and FB_END.search(t)
    if s and quoted:
        return None
    t = t[:s.start()] if s else t
    t = TAIL.sub("", t).strip(" ,.\"'“”«»")
    if fallback and t and (t.lower() in GENERIC or " " not in t and t[-1].lower() not in "aeiouàèéìòù"):
        return None
    if not (4 <= len(t) <= 80) or not JOB_NOUN.match(t) or re.search(r"\b\w*(?:destinar|assegnar|inquadrar)", t, re.I):
        return None
    if fallback and (len(t) > 70 or re.search(r"\d|\bart\b|\bex\b", t, re.I)):
        return None
    words = t.split()
    shouting = sum(len(x) > 1 and x.isupper() for x in words) > 1  # "FUNZIONARIO TECNICO esperto", "Docenti DI PRIMA FASCIA"
    t = " ".join(x.lower() if x.isupper() and x.replace("-", "").isalpha() and x not in ACRONYMS and (len(x) > 4 or shouting) else x for x in words)
    return t[:1].upper() + t[1:]


# Second chance, when no count introduces the job: "... area degli istruttori, profilo professionale “istruttore tecnico”", "N.2 “agenti di polizia locale”".
FB_END = re.compile(r"\s+(?:ed?\s+)?(?:dell['’]\s*)?elevat|\s+pos\.|\s+in servizio|\s+\(?cat\b|\s+full|\s+con\s|\s+da\s|\s+ambito|\s+sino\s", re.I)
FB_BAD = re.compile(r"\s+(?:per|area|di cui|nell|nel|nei)\b", re.I)  # a cut here may have eaten part of the name: "specialista per la ricerca"
FB_DASH = re.compile(r"\s*[–—-]\s*(?:settore|area|ccnl|c\.c\.n\.l|da|presso|per|ex|cat|liv|mansione|a|con|tempo|sede|nel|ruolo|ai|riservat|comparto|famiglia|ambito|categoria|part|full|livello|codice|servizio|disciplina|direttore)\b", re.I)
GENERIC = {"tecnico", "assistente", "operator"}
FB_STARTS = [re.compile(p, re.I) for p in [
    r"\b(?:profilo(?:\s+professionale)?|qualifica|qualit[àa]|figura professionale)(?:\s+di)?\s+(?=[“\"«]?" + JOB_NOUN.pattern + ")",  # "con profilo professionale di istruttore tecnico"
    r"\b(?:posti?|unit[aà]|incarich[io]|figur[ae]|posizione)\b(?:\s+(?:in ruolo|a tempo|pieno|parziale|indeterminat\w+|determinat\w+|e|ed|/|part[- ]time|full[- ]time|\(\d+[^)]{0,25}\)|\d+ ore|a orario \w+|con (?:rapporto|contratto) di lavoro(?: subordinato)?))*"
    r"\s+(?:di|quale|come)\s+(?=(?:n\.?\s*\d+\s+)?[“\"«]?" + JOB_NOUN.pattern + ")",  # "n. 1 posto a tempo pieno (18 ore) di istruttore"
    r"\bincarich[io]\b.{0,150}?\b(?:s\.?m\.?i\.?|ss\.?\s?mm\.?\s?ii\.?|comma \d+),?\s+(?:di|quale)\s+(?=[“\"«]?" + JOB_NOUN.pattern + ")",  # "incarico ... ex art. 110, comma 1, di educatore"
    r"\bn\.?\s*\d+\s*(?=[“\"«]" + JOB_NOUN.pattern + ")",  # "N.2 “agenti di polizia locale”"
    r"^(?:avviso|selezione|concorso|bando)(?: pubblico)? per (?=" + JOB_NOUN.pattern + ")",  # "Avviso per fisioterapista"
]]


def role(t):
    """The job alone, for JobPosting.title ("Istruttore tecnico"), from a title already through what();
    None unless it starts with a known job noun."""
    t = re.sub(r"^(?:Concorso|Selezione|Avviso|Mobilità|Stabilizzazione|Interpello)(?: a tempo [a-z ]+)?: ", "", t)
    found = [m for m in (POSTS.search(t[:160]), HEADCOUNT.search(t[:160])) if m]
    m = min(found, key=lambda m: m.start()) if found else None  # the first count in the title
    if not m:
        m = None if LIST_ONLY.search(t[:200]) else (PROFILO.search(t[:200]) if COUNTISH.search(t[:200]) else None) or STARTS.match(t)  # "n. 2 posti area degli istruttori, profilo istruttore..." / "Funzionario tecnico a tempo parziale"
    job = m and finish(t[m.end():])
    if job or LIST_ONLY.search(t[:200]):
        return job
    for m in [m for rx in FB_STARTS for m in rx.finditer(t[:300])] + list(POSTS.finditer(t[:200])):
        if m and t[:m.start()].count("“") <= t[:m.start()].count("”"):  # not after an unclosed quote: "n. 2 “istruttori ... e n. 1 “istruttore"
            rest = t[m.end():]
            job = finish(rest[1:] if rest[:1] in "“\"«" else rest, True, rest[:1] in "“\"«")
            if job:
                return job
    return None
