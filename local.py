"""Province of a call, for local authorities only: an ente named "Comune di X", "Provincia di X" or
"Città metropolitana di X" is in a known place. Other entes (health authorities, universities, ministries)
may hire anywhere, so they get no province rather than a guess. Names are matched against ISTAT's list
of municipalities through bandi's geo.py, inside the call's own region."""
import csv
import os
import re

import geo

ENTE = re.compile(r"(comune|provincia|citt(?:[aà]|a['’]) metropolitana) (della |dell['’] ?|del |di )(.+)", re.I)
ARTICLE = {"della": "La ", "dell'": "L'"}  # "Comune della Spezia" is La Spezia, "Provincia dell'Aquila" L'Aquila
ALIAS = {"reggio emilia": "Reggio nell'Emilia", "capaccio": "Capaccio Paestum", "chiusano san domenico": "Chiusano di San Domenico"}
JUNK = re.compile(r"\s+invia la tua candidatura\b.*|\s*\([A-Za-z]{2}\)\s*$|\s+[-–—(,].*", re.I)


def place_of(ente, region):
    """-> (comune, province label) for a local authority, else (None, None). comune is None for a province's
    own calls. region: the call's single region name, or "" when it names several or none."""
    m = ENTE.fullmatch(" ".join((ente or "").split()))
    if not m:
        return None, None
    kind, name = m.group(1).lower(), JUNK.sub("", m.group(3)).replace("’", "'").strip()
    names = [name, ARTICLE.get(m.group(2).strip().lower().replace("’", "'"), "") + name]
    for name in dict.fromkeys(names):
        if kind == "comune":
            name = ALIAS.get(name.lower(), name)
            reg, prov = geo.place(name, region)
            if prov:
                return name, prov
            continue
        reg, prov = geo.place("", name)
        if prov and not (region and reg and geo.norm(reg) != geo.norm(region)):
            return None, prov
    return None, None


def _capitals():
    """{region: {normalized name: display name}} for provincial capitals, from the ISTAT flag column."""
    out = {}
    with open(geo.REF, encoding="latin-1", newline="") as f:
        rows = csv.reader(f, delimiter=";")
        next(rows)
        for r in rows:
            if len(r) > 13 and r[13].strip() == "1":
                out.setdefault(r[10].split("/")[0].strip(), {})[geo.norm(r[6])] = r[6].strip()
    return out


CAPITALS = _capitals()


def seat_of(ente, region):
    """The city in an ente's name, for JobPosting.addressLocality only (not for province pages): exactly one
    provincial capital of the call's own region, as whole words ("Università degli Studi di Palermo", "ASL Roma 2").
    None when the name has none or several ("Camera di commercio Milano Monza Brianza Lodi"), or names an area ("ASST Nord Milano")."""
    words = f" {geo.norm(ente)} "
    for r in CAPITALS:  # "Friuli Venezia Giulia" is not Venezia
        words = words.replace(f" {geo.norm(r)} ", " ")
    found = {d for n, d in CAPITALS.get(region, {}).items() if f" {n} " in words
             and not re.search(rf"\b(?:NORD|SUD|EST|OVEST|CENTRO) {n}\b|\b{n} (?:NORD|SUD|EST|OVEST|CENTRO)\b", words)}  # "Nord Milano": an area
    return found.pop() if len(found) == 1 else None


# Where the work is, for JobPosting.addressLocality and the page's "Sede di lavoro" row, when the ente's name gives no city:
# a place the call itself names ("sede di Lonigo", "Presidio ospedaliero di Orvieto"), or the seat of a body that works
# in one comune only (seats.tsv: checked one by one on the body's own site; multi-site bodies are not listed).
NAME = r"([A-ZÀ-Ý][\w'’À-ÿ]+(?:[ -](?:[A-ZÀ-Ý][\w'’À-ÿ]+|d[ei]l?|sul|in|di|al|nel))*)"
WHERE = [re.compile(p) for p in [
    r"\b[Ss]ed[ei](?: (?:di lavoro|di servizio|operativ[ae]|secondari[ae]|distaccat[ae]|di assegnazione))?\s*:?\s+(?:di|a|in|presso)\s+" + NAME,
    r"\b(?:[Oo]spedal[ei]|[Pp]resid(?:io|i) [Oo]spedalier[oi]|P\.\s?O\.|[Ss]tabiliment[oi](?: [Oo]spedalier[oi])?|[Ss]ezione|[Pp]olo|[Dd]istretto|[Cc]asa di [Cc]omunità"
    r"|[Oo]sservatorio|[Ii]stituto|[Ll]aboratori|[Cc]entro)\b[^,.;:()]{0,60}?\b(?:di|a)\s+" + NAME,
    r"\b(?:SEDE|OSPEDALE|PRESIDIO OSPEDALIERO|STABILIMENTO)(?: DI LAVORO| OSPEDALIERO)?\s+(?:DI|A|IN)\s+([A-ZÀ-Ý'’ ]{3,40}?)(?=[,.;:()–—-]|\s+(?:PER|E|DEL|DELLA|CON|A|IN|DA)\b|$)",
]]
SMALL = {"di", "del", "dei", "della", "in", "sul", "al", "nel", "e"}


def nice(name):
    """ "MONTE SAN SAVINO" -> "Monte San Savino"; mixed case stays as written."""
    if not name.isupper():
        return name
    return " ".join(w.lower() if i and w.lower() in SMALL else w.capitalize() for i, w in enumerate(name.split()))


def seat_in_text(text, region):
    """The one comune of the call's region that the call names as a place of work, else None (none or several)."""
    found = {}
    for rx in WHERE:
        for m in rx.finditer(text or ""):
            words = m.group(1).split()
            for k in range(len(words), 0, -1):  # the longest prefix that is a comune of this region: "Lodi del Centro di…" -> Lodi
                name = " ".join(words[:k])
                if any(h[0] == region for h in geo._BY_COMUNE.get(geo.norm(name), ())):
                    found.setdefault(geo.norm(name), nice(name))
                    break
    return found.popitem()[1] if len(found) == 1 else None


def _seats():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seats.tsv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {(geo.norm(r[0]), r[1]): r[2] for r in csv.reader(f, delimiter="\t") if len(r) >= 3 and not r[0].startswith("#")}


SEATS = _seats()


def seat_listed(ente, region):
    return SEATS.get((geo.norm(" ".join((ente or "").split())), region))
