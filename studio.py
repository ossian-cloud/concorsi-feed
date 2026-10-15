"""Minimum education a call asks for, guessed from the contract level named in its title (or, failing
that, in inPA's short description). inPA has no such field. Public contracts tie levels to education:
Area degli Operatori / categoria B = scuola dell'obbligo, Area degli Istruttori, Assistenti o Collaboratori /
categoria C = diploma, Area dei Funzionari / categoria D, dirigenti, medici, ricercatori = laurea. A call can
name several levels or none; a call with none is in no list. A guess, never a substitute for the bando.
Audited twice on 15 Oct 2026 data (notes/studio-audit-2026-10-15.md)."""
import re

import profili

# (slug, label, phrase after "Concorsi pubblici aperti", area pattern, word pattern).
# Area patterns name the contract level itself; when the text names one, word patterns are ignored
# ("Area dei Collaboratori, tecnico di laboratorio" is a diploma job, not a degree one).
LEVELS = [
    ("laureati", "Laureati", "per laureati",
     r"categori[ae]\s*[\"“«']?d\d?[\"”»']?(?![\w'’])|\bcat\.?\s*[\"“«']?d\d?\b|\bare[ae]\s+(?:(?:dei|degli|delle)\s+)?(?:(?:funzionari|istruttori|assistenti|collaboratori|operatori(?: esperti)?|elevat[ae] qualificazion[ei])(?:\s*,\s*|\s+ed?\s+)(?:(?:dei|degli|delle)\s+)?){0,4}funzionari\b|terza area|\barea iii\b|"
     r"elevat[ae] (?:qualificazion|professionalit)|\barea eq\b",
     r"\bfunzionari[oa]?\b|istruttor[ei] direttiv|collaborator[ei] (?:amministrativ[oi]|tecnic[oi]) professional|"
     r"collaborator[ei] professional[ei] sanitar|\blaure[ai]|\blaurea|(?<!non )\bdirigent[ei]\b|\bricercator|\btecnolog[oi]\b|"
     r"assegn[oi] di ricerca|bors[ae] di ricerca|incaric\w+ di ricerca|art\.? ?22[- ]?(?:bis|ter)|post[- ]?doc|"
     r"\bmedic[oi]\b|\binfermier|\bavvocat|\bpsicolog[oi]\b|\bfarmacist|\bbiolog[oi]\b|\bveterinari|assistent[ei] social|"
     r"\bostetric|fisioterapist|logopedist|tecnic[oi] (?:sanitari|di radiologia|della prevenzione|di laboratorio biomedic|della riabilitazione)|"
     r"segretari[oa]? (?:comunale|generale)|docent[ei] (?:della |di )?scuola secondaria|concorso (?:ordinario )?secondaria|"
     r"\bd\.?d\.?g?\.? ?(?:n\. ?)?2939\b"),
    ("diplomati", "Diplomati", "per diplomati",
     r"categori[ae]\s*[\"“«']?c\d?[\"”»']?(?![\w'’])|\bcat\.?\s*[\"“«']?c\d?\b|\bare[ae]\s+(?:(?:dei|degli|delle)\s+)?(?:(?:funzionari|istruttori|assistenti|collaboratori|operatori(?: esperti)?|elevat[ae] qualificazion[ei])(?:\s*,\s*|\s+ed?\s+)(?:(?:dei|degli|delle)\s+)?){0,4}(?:istruttori|assistenti|collaboratori)\b|"
     r"seconda area|\barea ii\b",
     r"\bistruttor[ei]\b(?! direttiv)|\bassistent[ei] (?:amministrativ|tecnic|informatic|contabil|di vigilanza|giudiziari)|"
     r"agent[ei] di polizia (?:locale|municipale)|\bagent[ei] (?:di )?p\.?\s?l\b|vigil[ei] urban|\bdiploma\b(?! accademic| di specializzazione)|"
     r"\bcter\b|collaborator[ei] tecnic[oi] (?:e\.?\s?r\b|enti di ricerca)|\bgeometr[ae]\b|\bperit[oi]\b"),
    ("scuola-obbligo", "Scuola dell'obbligo", "con la scuola dell'obbligo",
     r"categori[ae]\s*[\"“«']?[ab]\d?[\"”»']?(?![\w'’])|\bcat\.?\s*[\"“«']?[ab]\d?\b|\bare[ae]\s+(?:(?:dei|degli|delle)\s+)?(?:(?:funzionari|istruttori|assistenti|collaboratori|operatori(?: esperti)?|elevat[ae] qualificazion[ei])(?:\s*,\s*|\s+ed?\s+)(?:(?:dei|degli|delle)\s+)?){0,4}operatori\b|prima area|\barea i\b",
     r"\boperator[ei]\s+(?:esper(?:to|ti|ta)|tecnic[oi]|ecologic[oi])\b|\boperai|\besecutor[ei]\b|\bautist|\bcantonier|\bnecrofor|"
     r"\bcommess[oi]\b|\bcentralinist|\bausiliari|\bcoadiutor[ei]\b|scuola dell.obbligo|licenza (?:media|di scuola secondaria di primo grado)|"
     r"\bbidell|collaborator[ei] scolastic|collaborator[ei] (?:servizi|esperto tecnico)"),
]
# never in a list: OSS need a vocational qualification, exam boards and OIV are not jobs
HARD_EXCLUDE = re.compile(r"operator[ei] socio[- ]*sanitari|\bo\.?\s?s\.?\s?s\b|commissione|componenti? (?:esperto|della commissione)|"
                          r"\boiv\b|organismo (?:indipendente )?di valutazione", re.I)
# AFAM teaching asks for a diploma accademico, not a level; their staff areas still count
SOFT_EXCLUDE = re.compile(r"conservatori|accademi[ae]|\bafam\b", re.I)
# employer names: "Ordine dei Medici Chirurghi" hires clerks, not doctors
EMPLOYER = re.compile(r"\b(?:ordine|ordini|federazione|collegio)\b[^,;.:()–-]{0,80}", re.I)
# a progression "dall'Area degli Operatori all'Area dei Collaboratori" asks for the second one
PROGRESSION = re.compile(r"\bdall.\s?area\b.*?(?=\ball.\s?area\b|\bnell.\s?area\b|\bverso l.\s?area\b)", re.I)
# a level in inPA's description counts only next to a contract word (descriptions also say who to contact, etc.)
DESC_CONTEXT = re.compile(r"\barea\b|categori|\bcat\.|ccnl|profil|\bpost[oi]\b|laure|diploma", re.I)
_RX = [(s, re.compile(a, re.I), re.compile(w, re.I)) for s, _, _, a, w in LEVELS]
_AREAS = re.compile("|".join(a for _, _, _, a, _ in LEVELS), re.I)
LABEL = {s: label for s, label, _, _, _ in LEVELS}
PHRASE = {s: ph for s, _, ph, _, _ in LEVELS}
# professions whose access needs a degree in Italian law, used when the text names no level
DEGREE_PROFILES = {"medici", "infermieri", "avvocati", "assistenti-sociali"}


def _levels(t):
    t = PROGRESSION.sub(" ", EMPLOYER.sub(" ", t))
    if HARD_EXCLUDE.search(t) or profili.NOT_A_JOB.search(t):
        return None
    if SOFT_EXCLUDE.search(t) and not _AREAS.search(t):
        return None
    found = [s for s, a, _ in _RX if a.search(t)]
    return found or [s for s, _, w in _RX if w.search(t)]


def levels_of(c):
    found = _levels(" ".join(c["title"].split()))
    if found is None:
        return []
    if not found and c.get("desc"):
        d = " ".join(c["desc"].split())[:600]
        if DESC_CONTEXT.search(d):
            found = _levels(d) or []
    if not found and DEGREE_PROFILES & set(c.get("_prof") or ()):
        found = ["laureati"]
    return found
