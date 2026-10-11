"""The job a call is for, without the procedural words in front of it.
inPA titles mostly open with boilerplate ("Concorso pubblico, per titoli ed esami, per la copertura a tempo
pieno e indeterminato di n. 2 posti di..."). For lists and feed titles I strip a chain of such fillers from
the start and keep one word for the kind of procedure: "Concorso: n. 2 posti di...". Only official words
are removed, never added; when too little would be left, the title stays as it is."""
import re

KIND = re.compile(r"(?:(?:bando|indizione|avviso|avvio|riapertura (?:dei )?termini|pubblico|procedura|di|del|dell['’]|per|relativo al(?:la)?)\s+)*"
                  r"(concorso|concorsi|selezione|procedura (?:concorsuale|selettiva|comparativa)|mobilit[aà]|stabilizzazione|avviso|bando)\b", re.I)
FILLERS = [re.compile(p, re.I) for p in [
    r"(?:pubblic[oa]|ordinari[oa]|unic[oa]|esterna|volontaria|interna|tra (?:enti|p\.?a\.?|pubbliche amministrazioni)"
    r"|unificat[oa]|congiunt[oa]|regionale|interregionale|nazionale|comparativa|selettiva|concorsuale|riservat[oa]|straordinari[oa]|esplorativ[oa]|in entrata)\b",
    r"(?:di|per|mediante|ai fini del(?:la)?|finalizzat[oa] al(?:la|l['’])?|volt[oa] al(?:la|l['’])?)\b",
    r"(?:soli\s+)?(?:titoli|esami|esame|colloquio|prova (?:pratica|scritta|orale))(?:\s+(?:e|ed)\s+(?:eventuale\s+)?(?:esami|esame|colloquio|prova (?:pratica|scritta|orale)))?(?:\s+pratic[oa])?\b",
    r"\(?(?:ai sensi|ex) (?:dell['’]|degli |dell )?art.{0,80}?(?:\d{4}|(?:165|267)(?:/\d{4})?)\b(?:,?\s*n\.?\s*\d+\b)?\)?",
    r"(?:la copertura|la stabilizzazione|l['’]assunzione|il reclutamento|il conferimento|l['’]affidamento|la stipula)\b",
    r"a tempo (?:pieno|parziale|indeterminato|determinato)(?:\s*(?:e|ed|/)\s*(?:a tempo\s+)?(?:pieno|parziale|indeterminato|determinato))*(?:\s*\([^)]{1,30}\))?",
    r"e (?:s\.?\s?m\.?\s?i\.?|ss\.?\s?mm\.?\s?ii\.?)",
    r"n?\.?\s*\d+/\d+\.?(?=\s)",  # a reference number, "43994/2026."
    r"[,:;.–—-]",
]]
RANK = ["Avviso", "Selezione", "Stabilizzazione", "Concorso", "Mobilità"]  # the more specific word wins


def kind_of(word):
    word = word.lower()
    return ("Mobilità" if word.startswith("mobilit") else "Concorso" if word.startswith("concors") else
            "Selezione" if word.startswith(("selezione", "procedura")) else "Stabilizzazione" if word.startswith("stabil") else "Avviso")


LEAD = re.compile(r"\s[–—-]\s*|[.:_]\s*")  # "Comune di Bergamo – ", "Comune di X. ", "I.R.C.C.S. Fondazione – "


def what(t):
    t = " ".join(t.split())
    if not KIND.match(t):  # an ente's name in front, then the procedure
        for lead in LEAD.finditer(t[:90]):
            if lead.start() >= 3 and KIND.match(t[lead.end():]):
                t = t[lead.end():]
                break
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
                    rest, changed = rest[f.end():].lstrip(), True
    if kind is None or len(rest) < 15 or len(t) - len(rest) < 12:
        return t
    return f"{kind}: {rest[:1].lower() + rest[1:] if not rest[:2].isupper() else rest}"


# The job alone, for JobPosting.title: after "n. 2 posti di" up to the first area, contract or punctuation.
POSTS = re.compile(r"\b(?:(?:n\.?\s*|nr\.?\s*|numero\s+)?(?:\d+|un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\s*)?(?:\(\w+\)\s*)?"
                   r"(?:posti|posto|unit[aà]|figur[ae]|incarichi|incarico|borse?(?: di studio)?)\s+(?:(?:di|per|a|da)\s+)?(?:(?:profilo|profili)\s+(?:professionale\s+)?(?:di\s+)?)?", re.I)
ROLE_END = re.compile(r"\s+(?:a tempo|con contratto|area\b|cat\.|categoria|presso|da assegnare|da destinare|nel(?:l['’]|la|lo|le)?\s|per (?:il|la|l['’]|le|i|gli)\s|ccnl|del ruolo|ruolo|livello|comparto|-\s|–|—|ai sensi|riservat|\(|ex\s)|\s+(?:nei|negli|in possesso|dpr|d\.p\.r|inquadrat[oa]|appartenente|da (?:collocare|inquadrare|adibire|impiegare)|part[- ]time|ed e\.?\s?q|-)\b|\s+[“-]|[–—]|\s+di [IVX]+\b|\s+[IVX]+\s+liv|[;:(,”\x22»]", re.I)
ROLE_FILLER = re.compile(r"\s*(?:a tempo (?:pieno|parziale|indeterminato|determinato|intederminato)(?:\s*(?:e|ed|/)\s*(?:a tempo\s+)?(?:pieno|parziale|indeterminato|determinato))*(?:\s*\([^)]{1,40}\))?"
                 r"|(?:di|del|nel|nell['’]|con(?: il)?|il|al|alla|in|per)\s+(?=(?:profilo|personale|qualifica|ruolo)\b)|(?:profilo|qualifica)(?: professionale)?(?: di)?\b|personale\b(?: (?:con|nel|di))?"
                 r"|(?:di|del)\s+(?=\S)|[“”\"«»,]\s*)\s*", re.I)
JOB_NOUN = re.compile(r"(?:funzionari|istruttor|dirigent|operator|assistent|agent|specialist|tecnic|collaborator|esecutor|infermier|medic|ricercator|docent|educat|autist|operai|ingegner|architett|geometr|psicolog|farmacist|veterinar|ostetric|fisioterapist|logopedist|biolog|chimic|avvocat|commissari|ispettor|vigil|bibliotecari|cuoc|maestr|insegnant|professor|accompagnator|gestor|espert|analist|addett|coordinat|responsabil|segretari|comandant|ufficial|sottufficial|cantonier|necrofor|elettricist|idraulic|giardinier|tecnolog|dietist|ortottist|puericultr|ausiliari|commess|impiegat|archivist|statistic|economist|giornalist|interpret|tradutt|programmator|sistemist|perit|direttor|primari|pediatr|dentist|odontoiatr|psicoterapeut|sociolog|geolog|agronom|forestal|guardi|custod|portier|usciere|centralinist|magazzinier|manutentor|meccanic|conducent|macchinist|marinai|carpentier|muratore|fabbro|falegnam|pittor|restaurator|curator|musicist|orchestral|lettor|consulent)", re.I)

HEADCOUNT = re.compile(r"(?:^|\bn\.?\s*\d+\s*|\b(?:\d+|un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\s+)(?:\(\w+\)\s*)?(?=" + JOB_NOUN.pattern + ")", re.I)


def role(t):
    """The job alone, for JobPosting.title ("Istruttore tecnico"), from a title already through what();
    None unless it starts with a known job noun."""
    t = re.sub(r"^(?:Concorso|Selezione|Avviso|Mobilità|Stabilizzazione): ", "", t)
    found = [m for m in (POSTS.search(t[:160]), HEADCOUNT.search(t[:160])) if m]
    m = min(found, key=lambda m: m.start()) if found else None  # the first count in the title
    if not m:
        return None
    t = t[m.end():]
    for _ in range(5):
        p = ROLE_FILLER.match(t)
        if not p or not p.end():
            break
        t = t[p.end():]
    s = ROLE_END.search(t)
    if s:
        t = t[:s.start()]
    t = t.strip(" ,.\"'“”«»")
    if not (4 <= len(t) <= 80) or not JOB_NOUN.match(t):
        return None
    words, n = t.split(), 0
    while n < len(words) and len(words[n]) > 4 and words[n].isupper():  # "FUNZIONARIO TECNICO esperto" (not "AFAM")
        n += 1
    t = " ".join([x.lower() for x in words[:n]] + words[n:])
    return t[:1].upper() + t[1:]
