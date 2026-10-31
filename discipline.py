"""Medical disciplines (DM 30 Jan 1998 and later additions) recognised in the titles of calls for doctors (profili "medici").
The slugs double as su-misura profile keys (f=cardiologia), so they must not collide with profili/studio keys."""
import re

# (slug, label, pattern). Patterns are matched on lowercase text with apostrophes normalised.
DISCIPLINES = [
    ("allergologia", "Allergologia e immunologia clinica", r"allergologia"),
    ("anatomia-patologica", "Anatomia patologica", r"anatomia patologica"),
    ("anestesia", "Anestesia e rianimazione", r"anestesia|rianimazione"),
    ("angiologia", "Angiologia", r"angiologia"),
    ("audiologia", "Audiologia e foniatria", r"audiologia|foniatria"),
    ("biochimica", "Biochimica clinica", r"biochimica clinica"),
    ("cardiochirurgia", "Cardiochirurgia", r"cardiochirurgia"),
    ("cardiologia", "Cardiologia", r"\bcardiolog"),
    ("chirurgia-generale", "Chirurgia generale", r"chirurgia generale"),
    ("chirurgia-maxillo-facciale", "Chirurgia maxillo-facciale", r"maxillo[- ]?facciale"),
    ("chirurgia-pediatrica", "Chirurgia pediatrica", r"chirurgia pediatrica"),
    ("chirurgia-plastica", "Chirurgia plastica e ricostruttiva", r"chirurgia plastica"),
    ("chirurgia-toracica", "Chirurgia toracica", r"chirurgia toracica"),
    ("chirurgia-vascolare", "Chirurgia vascolare", r"chirurgia vascolare"),
    ("continuita-assistenziale", "Continuità assistenziale / guardia medica", r"continuit. assistenziale|guardia medica"),
    ("cure-palliative", "Cure palliative", r"cure palliative"),
    ("dermatologia", "Dermatologia e venereologia", r"dermatolog"),
    ("direzione-medica", "Direzione medica di presidio ospedaliero", r"direzione medica|igiene ospedaliera"),
    ("ematologia", "Ematologia", r"ematologi"),
    ("endocrinologia", "Endocrinologia", r"endocrinologi"),
    ("farmacologia", "Farmacologia e tossicologia clinica", r"farmacologia"),
    ("gastroenterologia", "Gastroenterologia", r"gastroenterolog"),
    ("genetica-medica", "Genetica medica", r"genetica medica"),
    ("geriatria", "Geriatria", r"geriatri"),
    ("ginecologia", "Ginecologia e ostetricia", r"ginecologi|ostetricia e ginecologia"),
    ("igiene", "Igiene, epidemiologia e sanità pubblica", r"igiene,? epidemiologia|\bepidemiologia|sanit. pubblica|igiene e sanit"),
    ("igiene-alimenti", "Igiene degli alimenti e della nutrizione", r"alimenti e (?:della )?nutrizione|\bsian\b"),
    ("malattie-infettive", "Malattie infettive", r"malattie infettive"),
    ("malattie-metaboliche", "Malattie metaboliche e diabetologia", r"diabetolog|malattie metaboliche"),
    ("malattie-respiratorie", "Malattie dell'apparato respiratorio", r"apparato respiratorio|pneumolog"),
    ("medicina-del-lavoro", "Medicina del lavoro", r"medicina del lavoro|medico competente"),
    ("medicina-emergenza", "Medicina d'emergenza-urgenza", r"emergenza[- ]urgenza|\bmeu\b|emergenza e urgenza|pronto soccorso|\b118\b|medicina d.urgenza|chirurgia d.accettazione e d.urgenza|\bmcau\b"),
    ("medicina-fisica", "Medicina fisica e riabilitazione", r"medicina fisica|riabilitazione"),
    ("medicina-generale", "Medicina generale (territorio)", r"medici(?:na)? di (?:base|famiglia|medicina generale)|assistenza primaria|\bmmg\b"),
    ("medicina-interna", "Medicina interna", r"medicina interna"),
    ("medicina-legale", "Medicina legale", r"medicina legale|medico[- ]legal"),
    ("medicina-nucleare", "Medicina nucleare", r"medicina nucleare"),
    ("medicina-sport", "Medicina dello sport", r"medicina dello sport"),
    ("medicina-trasfusionale", "Medicina trasfusionale", r"trasfusional"),
    ("microbiologia", "Microbiologia e virologia", r"microbiologia e virologia|virologia"),
    ("nefrologia", "Nefrologia", r"nefrologi|dialisi"),
    ("neonatologia", "Neonatologia", r"neonatologi"),
    ("neurochirurgia", "Neurochirurgia", r"neurochirurgi"),
    ("neurologia", "Neurologia", r"\bneurologi"),
    ("neuropsichiatria-infantile", "Neuropsichiatria infantile", r"neuropsichiatria"),
    ("odontoiatria", "Odontoiatria", r"odontoiatria|odontoiatra\b"),
    ("oftalmologia", "Oftalmologia", r"oftalmologi|oculist"),
    ("oncologia", "Oncologia", r"oncologi"),
    ("organizzazione-servizi-base", "Organizzazione dei servizi sanitari di base", r"servizi sanitari di base"),
    ("ortopedia", "Ortopedia e traumatologia", r"ortopedi"),
    ("otorinolaringoiatria", "Otorinolaringoiatria", r"otorinolaringoiatri|\borl\b"),
    ("patologia-clinica", "Patologia clinica (laboratorio)", r"patologia clinica|laboratorio di analisi"),
    ("pediatria", "Pediatria", r"(?<!chirurgia )(?<!traumatologia )\bpediatri(?!che)"),
    ("psichiatria", "Psichiatria", r"(?<!neuro)psichiatr"),
    ("radiodiagnostica", "Radiodiagnostica", r"radiodiagnostica|radiologi"),
    ("radioterapia", "Radioterapia", r"radioterapia"),
    ("reumatologia", "Reumatologia", r"reumatologi"),
    ("scienza-alimentazione", "Scienza dell'alimentazione e dietetica", r"scienza dell.alimentazione|dietetica"),
    ("urologia", "Urologia", r"\burologi"),
]
_RX = [(s, re.compile(p)) for s, _, p in DISCIPLINES]
LABEL = {s: l for s, l, _ in DISCIPLINES}


def norm(t):
    return " ".join(t.lower().replace("’", "'").replace("`", "'").split())


# When the title names the discipline ("disciplina di X"), read only that clause, so ward names
# ("per la S.C. Medicina generale") and structure names don't add disciplines.
CLAUSE = re.compile(r"disciplin[ae]\b(.*?)(?=\bper\b|\bda (?:destinare|assegnare)|\bpresso\b|\bcon\b|\ba tempo\b|\barea\b|\bin (?:servizio|possesso)|[;.(]|$)")


def disciplines_of(c):
    t = norm(c["title"])
    m = CLAUSE.search(t)
    if m:
        found = [s for s, rx in _RX if rx.search(m.group(1))]
        if found:
            return found
    return [s for s, rx in _RX if rx.search(t)]
