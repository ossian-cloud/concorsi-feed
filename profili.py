"""Professions a call is for, guessed from its title with keyword patterns.
A call can belong to several professions or to none: inPA has no profession field, so these lists
are a convenience, never complete. Patterns are matched on the title only (descriptions repeat
boilerplate like "direttore" or "legale" that would mislead)."""
import re

# (slug, label, pattern, exclude): exclude removes calls that match the pattern for another reason.
# Tuned on 10 Oct 2026 data after an audit (notes/profili-audit-2026-10-10.md). Not "forze armate" in forze-ordine:
# most titles name them only for the legal reserve of posts for ex-volunteers.
PROFILES = [
    ("amministrativi", "Amministrativi e contabili",
     r"amministrativ|contabil|istruttore direttivo(?![\s/–-]+(?:tecnic|informatic|(?:funzionario )?(?:di )?(?:polizia|vigilanza)|socio|bibliotec|cultural|agrar|ambient|educator|socio))|segreteria|ragionier|economic[oa][- ]finanziari|\btribut[io]|demografic|(?:funzionario|collaboratore) di amministrazione",
     r"(?<!non )\bdirigent[ei]\b|incarico dirigenziale|\bchiave contabile"),
    ("tecnici", "Tecnici, ingegneri, architetti e geometri",
     r"tecnic(?:o|i|a)\b(?!,?\s*scientific)|ingegner(?!ia\b)|architett(?!ura\b)|geometr|urbanistic|lavori pubblici|edilizi|\bcter\b|settore scientifico[- ]tecnologico|attivit\S{1,2}\s+tecnich[ae]",
     r"tecnic[oi] (?:sanitari|di radiologia|della prevenzione|di laboratorio|della riabilitazione|audiometrist|di neurofisiopatologia)|nucleo tecnico|comitato tecnico|dirigente|ordine (?:degli |dei )?(?:architett|ingegner)|operator[ei] esperti?\b|operai"),
    ("polizia-locale", "Polizia locale",
     r"polizia (?:locale|municipale)|agent[ei] di p\.?\s?l\b|vigil[ei] urban|istruttor[ei] (?:direttivo )?di vigilanza|funzionario di (?:vigilanza|p\.?\s?l\b)|agente di vigilanza|assistente di vigilanza|agente di polizia\b|polizia provinciale|ufficiale di polizia",
     r"operator[ei] esperto"),
    ("forze-ordine", "Forze dell'ordine, militari e vigili del fuoco",
     r"carabinier|polizia di stato|guardia di finanza|vigili del fuoco|polizia penitenziaria|esercito|marina militare|aeronautica|allievi (?:agenti|marescialli|ufficiali|carabinieri|finanzieri|vice ispettori)|marescialli|ferma iniziale|capitanerie di porto",
     r"banda musicale"),
    ("medici", "Medici",
     r"dirigent[ei] medic|medic[oi] (?:chirurg|specialist|veterinar|di medicina|del|per|di)|disciplina di|direzione (?:della |di )?(?:s\.?\s?c\.?|struttura complessa|u\.?o\.?c\.?)\b|specialist[ai] ambulatorial|guardia medica|continuit[aà] assistenziale|direttore (?:della |di )?(?:s\.?\s?c\.?|struttura complessa|u\.?o\.?c\.?)\b|\bpsichiatr[ai]\b|\banestesist[ai]\b|\bpediatr[ai]\b|\bcardiolog[oi]\b|\bradiolog[oi]\b",
     r"professioni sanitarie|dirigente (?:psicolog|biolog|farmacist|chimic|fisic|veterinari|ingegner|sanitari|delle professioni)"),
    ("infermieri", "Infermieri",
     r"infermier",
     None),
    ("sanitari", "Professioni sanitarie e OSS",
     r"\boss\b|operator[ei] socio[- ]*sanitari|tecnic[oi] (?:sanitari|di radiologia|della prevenzione|di laboratorio|della riabilitazione)|fisioterapist|ostetric|logopedist|biolog(?:o|a|i|he)\b|farmacist|psicolog(?:o|a|i|he)\b|(?:consulenza|supporto|sportello)[\s_]psicologic|dietist|educatore professionale sanitario|veterinari|assistent[ei] sanitari|ortottist|podolog|audiometrist|odontoiatr|igienist[ai] dentali|terapist[ai] occupazional|perfusionist|tecnic[oi] di neurofisiopatologia|tecnic[oi] ortopedic",
     r"accademia|belle arti|arti visive|scenografia|conservatorio|\bafam"),
    ("insegnanti-educatori", "Insegnanti, docenti ed educatori",
     r"educator|insegnant|docent[ei]|scuol[ae] dell.infanzia|asili? nido|maestr[ei]|conservatori[oe]? (?:statale )?di musica|\bafam\s?\d{3}|concorso (?:ordinario )?(?:secondaria|infanzia|primaria)|\bd\.?m\.? 20[56]/2023|incarich\w+ di (?:insegnamento|docenza)|\bd\.?m\.? (?:n\. ?)?10[34](?:/| del )|\bdocenza\b|\birc\b|collaboratori? (?:esperti? )?linguistic|istruttori educativi|\bcel\b",
     r"educatore professionale sanitario|dottorato|operatore \(ex|coadiutor"),
    ("assistenti-sociali", "Assistenti sociali",
     r"assistent[ei] social|servizio sociale professionale|(?:funzionario|specialista)(?: dei)? (?:servizi )?socio[- ]assistenzial",
     None),
    ("informatici", "Informatici",
     r"(?<!tecnologico,)(?<!tecnologico, )(?<!tecnologico )informatic(?:o|a|i|he)\b(?! e dei servizi generali)(?! servizi generali)|sistemi informativi|\bict\b|data scien|sviluppator|transizione digitale",
     r"\bA\d{3}\b|classe di concorso|\bafam|\bisia\b|dirigente medico|riabilitativ|istruttore amministrativo|funzionario amministrativo"),
    ("ricerca", "Ricerca, assegni e borse di studio",
     r"assegn[oi] di ricerca|incaric[oh]i? di ricerca|22-ter|ricercator|bors[ae] di (?:studio|ricerca)|dottorat(?!o,)|tecnolog[oi]\b|post[- ]?doc|\bcnr\b"
     r"|professor[ei] (?:di (?:prima|seconda) fascia(?! afam)|universitar|associat|ordinar)",  # GU: "chiamata di due professori di seconda fascia"
     None),
    ("operai-autisti", "Operai, autisti e manutentori",
     r"\boperai|operator[ei] tecnic|operatore esperto|autist|necrofor|manutent|giardinier|cantonier|esecutor[ei]|collaborator[ei] tecnic(?:o|i)(?! professional)|cuoc[oh]|collaboratore esperto tecnico|messo comunale|collaboratore servizi di supporto",
     r"enti di ricerca|professionisti della salute|socio[- ]*sanitari|\boss\b|amministrativ|amm\.?vo|art\.? ?90|commissione|istruttore direttivo|funzionario tecnico|collaboratore tecnico e\.?\s?r\b"),
    ("dirigenti", "Dirigenti e segretari comunali",
     r"(?<!non )\bdirigent[ei]\b|incaric\w+ dirigenzial|direttore (?:generale|amministrativo|tecnico|di area)|segretari[oa]? (?:comunale|generale)",
     r"dirigent[ei] (?:medic|psicolog|sanitari|biolog|farmacist|veterinari|fisic|chimic|delle professioni)|odontoiatr|pubblica sicurezza|gruppi sportivi"),
    ("cultura", "Biblioteche, archivi e musei",
     r"bibliotec|archivist|muse[oi]\b|conservatore\b|beni culturali",
     r"insegnamento|docent|museo orto botanico"),
    ("incarichi-esterni", "Incarichi esterni, consulenze e OIV",
     r"organismo (?:indipendente )?di valutazione|\boiv\b|esperti esterni|incaric\w+ (?:di )?(?:collaborazione|consulenza|lavoro autonomo|professional)|contratto di collaborazione|prestazione d.opera|art\.? ?7,? comma 6|contratti di collaborazione|lavoro autonomo|collaborazione coordinata e continuativa",
     r"art\.? ?90\b"),
    ("avvocati", "Avvocati",
     r"avvocat",
     r"commissione esaminatrice|componente esperto|ordine degli avvocati"),
]
# calls for exam-board members name the profession they examine; they are not jobs in it
NOT_A_JOB = re.compile(r"commissione esaminatrice|componenti? (?:esperto|della commissione)", re.I)
_RX = [(s, re.compile(p, re.I), re.compile(x, re.I) if x else None) for s, _, p, x in PROFILES]
LABEL = {s: label for s, label, _, _ in PROFILES}


def profiles_of(c):
    t = " ".join(c["title"].split())
    if NOT_A_JOB.search(t):
        return []
    return [s for s, rx, ex in _RX if rx.search(t) and not (ex and ex.search(t))]
