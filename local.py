"""Province of a call, for local authorities only: an ente named "Comune di X", "Provincia di X" or
"Città metropolitana di X" is in a known place. Other entes (health authorities, universities, ministries)
may hire anywhere, so they get no province rather than a guess. Names are matched against ISTAT's list
of municipalities through bandi's geo.py, inside the call's own region."""
import re

import geo

ENTE = re.compile(r"(comune|provincia|citt[aà] metropolitana) di (.+)", re.I)
ALIAS = {"reggio emilia": "Reggio nell'Emilia", "capaccio": "Capaccio Paestum", "chiusano san domenico": "Chiusano di San Domenico"}
JUNK = re.compile(r"\s+invia la tua candidatura\b.*|\s*\([A-Za-z]{2}\)\s*$|\s+[-–—(,].*", re.I)


def place_of(ente, region):
    """-> (comune, province label) for a local authority, else (None, None). comune is None for a province's
    own calls. region: the call's single region name, or "" when it names several or none."""
    m = ENTE.fullmatch(" ".join((ente or "").split()))
    if not m:
        return None, None
    kind, name = m.group(1).lower(), JUNK.sub("", m.group(2)).replace("’", "'").strip()
    if kind == "comune":
        name = ALIAS.get(name.lower(), name)
        reg, prov = geo.place(name, region)
        return (name, prov) if prov else (None, None)
    reg, prov = geo.place("", name)
    if region and reg and geo.norm(reg) != geo.norm(region):
        return None, None
    return None, prov
