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
