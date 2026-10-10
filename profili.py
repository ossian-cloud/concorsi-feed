"""Professions a call is for, guessed from its title with keyword patterns.
A call can belong to several professions or to none: inPA has no profession field, so these lists
are a convenience, never complete. Patterns are matched on the title only (descriptions repeat
boilerplate like "direttore" or "legale" that would mislead)."""
import re

# (slug, label, pattern, exclude): exclude removes calls that match the pattern for another reason
PROFILES = [
    ("amministrativi", "Amministrativi e contabili",
     r"amministrativ|contabil|istruttore direttivo|segreteria|ragionier|economic[oa][- ]finanziari|tributi|demografic", None),
    ("tecnici", "Tecnici, ingegneri, architetti e geometri",
     r"tecnic[oiahe]\b|ingegner|architett|geometr|urbanistic|lavori pubblici|edilizi|\bcter\b",
     r"tecnic[oi] (?:sanitari|di radiologia|della prevenzione|di laboratorio|della riabilitazione|audiometrist|di neurofisiopatologia)"
     r"|nucleo tecnico|comitato tecnico|dirigente"),
    ("polizia-locale", "Polizia locale",
     r"polizia (?:locale|municipale)|agent[ei] di p\.?\s?l\b|vigil[ei] urban|istruttor[ei] di vigilanza", None),
    ("forze-ordine", "Forze dell'ordine, militari e vigili del fuoco",
     r"carabinier|polizia di stato|guardia di finanza|vigili del fuoco|polizia penitenziaria|esercito|marina militare|aeronautica"
     r"|allievi (?:agenti|marescialli|ufficiali|carabinieri|finanzieri|vice ispettori)|marescialli|ferma iniziale|capitanerie di porto", None),
    # not "forze armate": most titles name them only for the legal reserve of posts for ex-volunteers
    ("medici", "Medici",
     r"dirigent[ei] medic|medic[oi] (?:chirurg|specialist|veterinar|di medicina|del|per|di)|disciplina di"
     r"|direzione (?:della |di )?(?:s\.?\s?c\.?|struttura complessa|u\.?o\.?c\.?)\b|specialist[ai] ambulatorial|guardia medica|continuit[aà] assistenziale",
     None),
    ("infermieri", "Infermieri", r"infermier", None),
    ("sanitari", "Professioni sanitarie e OSS",
     r"\boss\b|operator[ei] socio[- ]sanitari|tecnic[oi] (?:sanitari|di radiologia|della prevenzione|di laboratorio|della riabilitazione)"
     r"|fisioterapist|ostetric|logopedist|biolog|farmacist|psicolog|dietist|educatore professionale sanitario|veterinari|assistent[ei] sanitari",
     None),
    ("insegnanti-educatori", "Insegnanti, docenti ed educatori",
     r"educator|insegnant|docent[ei]|scuola dell.infanzia|asili? nido|maestr[ei]|conservatori[oe]? (?:statale )?di musica|\bafam\b"
     r"|concorso (?:ordinario )?(?:secondaria|infanzia|primaria)|\bd\.?m\.? 20[56]/2023",
     r"educatore professionale sanitario"),
    ("assistenti-sociali", "Assistenti sociali", r"assistent[ei] social|servizio sociale professionale", None),
    ("informatici", "Informatici", r"informatic|sistemi informativi|\bict\b|data scien|sviluppator|transizione digitale", None),
    ("ricerca", "Ricerca, assegni e borse di studio",
     r"assegn[oi] di ricerca|incaric[oh]i? di ricerca|22-ter|ricercator|borse? di studio|dottorat|tecnolog[oi]\b|post[- ]?doc|\bcnr\b", None),
    ("operai-autisti", "Operai, autisti e manutentori",
     r"\boperai|operator[ei] (?:tecnic|esperto|esperti)|autist|necrofor|manutent|giardinier|cantonier|esecutor[ei]|collaborator[ei] tecnic", None),
    ("dirigenti", "Dirigenti e segretari comunali",
     r"\bdirigent[ei]\b|incaric\w+ dirigenzial|direttore (?:generale|amministrativo|tecnico|di area)|segretari[oa]? (?:comunale|generale)",
     r"dirigent[ei] (?:medic|psicolog|sanitari|biolog|farmacist|veterinari|fisic|chimic|delle professioni)"),
    ("cultura", "Biblioteche, archivi e musei", r"bibliotec|archivist|muse[oi]\b|conservatore\b|beni culturali", None),
    ("incarichi-esterni", "Incarichi esterni, consulenze e OIV",
     r"organismo (?:indipendente )?di valutazione|\boiv\b|esperti esterni|incaric\w+ (?:di )?(?:collaborazione|consulenza|lavoro autonomo|professional)"
     r"|contratto di collaborazione|prestazione d.opera|art\.? ?7,? comma 6", None),
    ("avvocati", "Avvocati", r"avvocat", None),
]
_RX = [(s, re.compile(p, re.I), re.compile(x, re.I) if x else None) for s, _, p, x in PROFILES]
LABEL = {s: label for s, label, _, _ in PROFILES}


def profiles_of(c):
    t = " ".join(c["title"].split())
    return [s for s, rx, ex in _RX if rx.search(t) and not (ex and ex.search(t))]
