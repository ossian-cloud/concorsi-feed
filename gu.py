"""Fetch the concorsi published in the Gazzetta Ufficiale, 4a Serie Speciale "Concorsi ed esami", and keep
slim records shaped like inPA's (fetch.py), so build.py can merge the two sources.

Why: many administrations, health authorities above all, still publish only in the GU. On 9 and 13 Oct 2026
only 4 of 95 GU concorsi were on inPA (notes/gu-coverage-2026-10-15.md).

Route: the list of the last 30 days' issues (/30giorni/concorsi) and each issue's summary page, which gives,
per entry, the section (rubrica), the issuing body (emettitore), the type, GU's editorial deadline and a short
summary. Two issues a week (Tuesday, Friday), so a few requests a week; an issue already stored is not fetched
again. No robots.txt (404). Reuse terms on gazzettaufficiale.it: "La riproduzione dei testi forniti nel formato
elettronico è consentita purché venga menzionata la fonte, il carattere non autentico e gratuito." So every
output cites the GU, says the text is not authentic and the service free, and links to the GU's own page.

Only entries GU gives a deadline to and whose type is CONCORSO or MOBILITA' are kept: no rankings, results,
exam calendars. The deadline is editorial ("L'unica data ufficiale è quella contenuta nel testo del
bando", GU's own note), and outputs say so.
Two more kinds need the act's text (one request each, a few a week):
- RETTIFICA "Riapertura dei termini": a call reopened with a new deadline, kept as a call. The summary has no
  deadline; it is read from the text ("entro il trentesimo giorno successivo alla data di pubblicazione", or a date).
- ANNULLAMENTO of a concorso (not of an appointment): when the text names the GU issue of the annulled
  publication, the stored call from that issue and body is dropped; otherwise it is only logged, for a human.

Usage: python3 gu.py [--reread]  --reread: read again every issue in the 30-day list (after a parser change).
Reads the list at most every LIST_EVERY_H hours. Writes data/gu.json (dict id -> record) and data/gu-issues.json (issues seen).
Refuses to run while data/BLOCKED-GU exists.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.gazzettaufficiale.it"
LIST = BASE + "/30giorni/concorsi"
ISSUE = BASE + "/gazzetta/concorsi/caricaDettaglio?dataPubblicazioneGazzetta={}&numeroGazzetta={}"
ITEM = BASE + "/eli/id/{}/{}/S4"  # date with slashes, codice redazionale
UA = "OssianBot/0.1 (+https://ossian.cloud/concorsi/; ossian@ossian.cloud)"
PAUSE = 3
LIST_EVERY_H = 11  # the 30-day list is read about twice a day; issues come out on Tuesday and Friday
KEEP_TYPES = {"CONCORSO", "MOBILITA'"}
# typed CONCORSO but not a job: PhD admissions, sessions of professional qualification exams
NOT_JOBS = re.compile(r"ammissione a[il]?\s+(?:\w+\s+)?cors[oi] di dottorato|\bcors[oi] di dottorato di ricerca|esami? di (?:stato|abilitazione|idoneit)|sessione d'esam", re.I)
ACT = BASE + ("/atto/concorsi/caricaArticoloDefault/originario?atto.dataPubblicazioneGazzetta={}"
             "&atto.codiceRedazionale={}&atto.tipoProvvedimento={}")
REOPEN = re.compile(r"\briapertura (?:dei |del )?termin", re.I)
CANCEL = re.compile(r"^(?:annullamento|revoca)\b", re.I)
APPOINTMENT = re.compile(r"conferiment|nomina|graduatori|incaric[oh]i? (?:gi[aà] )?conferit", re.I)
ORDINALS = {"decimo": 10, "quindicesimo": 15, "ventesimo": 20, "venticinquesimo": 25, "trentesimo": 30,
            "quarantesimo": 40, "quarantacinquesimo": 45, "sessantesimo": 60}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "gu.json")
ISSUES = os.path.join(HERE, "data", "gu-issues.json")
CANCELS = os.path.join(HERE, "data", "gu-cancels.json")  # annulments seen, kept so a re-read can't revive a call
BLOCKED = os.path.join(HERE, "data", "BLOCKED-GU")
MONTHS = {m: i + 1 for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre "
                                          "ottobre novembre dicembre".split())}

# geo.py (bandi's, or the copy in vendor/ in the public repo): used by the annulment matching and by build.py
sys.path += [os.path.join(HERE, "..", "bandi"), os.path.join(HERE, "vendor")]  # appended: our own modules win

_last = 0.0


def get(url):
    global _last
    wait = PAUSE - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
    finally:
        _last = time.time()
    if "Request Rejected" in body[:2000]:  # their firewall: stop, never work around it
        open(BLOCKED, "w").write(f"{dt.datetime.now().isoformat()} {url}\n")
        raise SystemExit(f"rejected by the GU firewall on {url}; wrote {BLOCKED}")
    return body


def text(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def issues_listed(page):
    """[(date 'YYYY-MM-DD', number)] from the 30-day list."""
    found = re.findall(r"caricaDettaglio\?dataPubblicazioneGazzetta=(\d{4}-\d\d-\d\d)&(?:amp;)?numeroGazzetta=(\d+)", page)
    return sorted(set((d, int(n)) for d, n in found))


TOKEN = re.compile(r'<span class="rubrica">(.*?)</span>|<span class="emettitore">(.*?)</span>'
                   r'|<span class="risultato">(.*?)</span>\s*</span>|<span class="risultato">(.*?<span class="pagina">.*?</span>\s*</a>)', re.S)


def parse_issue(page, date, number):
    """Entries of one issue: list of dicts with section, ente, type, deadline, summary, code."""
    out, section, ente = [], None, None
    for m in TOKEN.finditer(page):
        if m.group(1) is not None:
            section, ente = text(m.group(1)), None
            continue
        if m.group(2) is not None:
            ente = text(m.group(2))
            continue
        block = m.group(3) or m.group(4)
        code = re.search(r"codiceRedazionale=(\w+)", block)
        kind = re.search(r'<span class="data">\s*([^<]*?)\s*(?:<font[^>]*>(.*?)</font>)?\s*</span>', block, re.S)
        links = re.findall(r"<a [^>]*>(.*?)</a>", block, re.S)
        if not (code and kind and len(links) >= 2):
            continue
        summary = re.sub(r"<!--.*?-->", "", links[1], flags=re.S)
        summary = re.sub(r'<span class="(?:riferimento|pagina)">.*?</span>', "", summary, flags=re.S)
        summary = re.sub(r"\(\s*" + re.escape(code.group(1)) + r"\s*\)", "", text(summary)).strip()
        out.append({"section": section, "ente": ente, "type": " ".join(kind.group(1).split()),
                    "scad": text(kind.group(2) or ""), "summary": summary, "code": code.group(1),
                    "date": date, "number": number})
    return out


def deadline(scad):
    """'(scad. 12 novembre 2026)' -> '2026-11-12T23:59' (local), else None. Editorial, not official."""
    m = re.search(r"(\d{1,2})\s+([a-zà]+)\s+(\d{4})", scad.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat() + "T23:59"
    except ValueError:
        return None


POSTS = re.compile(r"\b(?:di|per)\s+(?:n\.\s*)?(\d+|un|uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|"
                   r"undici|dodici|quindici|venti|trenta|quaranta|cinquanta|cento)\s+(?:\w+\s+)?posti?\b", re.I)
WORDS = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7,
         "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "quindici": 15, "venti": 20,
         "trenta": 30, "quaranta": 40, "cinquanta": 50, "cento": 100, "quarantacinque": 45, "sessanta": 60}


def posts_of(summary):
    """Number of posts when the summary states exactly one count ("copertura di due posti"), else None."""
    found = {m.group(1).lower() for m in POSTS.finditer(summary)}
    if len(found) != 1:
        return None
    v = found.pop()
    return int(v) if v.isdigit() else WORDS[v]


def record(e):
    d = e["date"]
    # 32 hex digits like inPA's ids, so pages share concorso/<id>.html and the 16 shards
    return {"id": hashlib.md5(("gu:" + e["code"]).encode()).hexdigest(), "gu_code": e["code"], "source": "gu", "title": e["summary"], "desc": None, "ente": e["ente"],
            "section": e["section"], "gu_type": e["type"], "region": None, "eval": None, "status": None,
            "opens": d + "T00:00", "closes": deadline(e["scad"]), "posts": posts_of(e["summary"]),
            "pay_min": None, "pay_max": None, "attachments": [],
            "pa_url": None, "gu_url": ITEM.format(d.replace("-", "/"), e["code"]),
            "gu_issue": f"n. {e['number']} del {d[8:10]}/{d[5:7]}/{d[:4]}",
            "lastmod": d + "T00:00:00Z", "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


ACTS = os.path.join(HERE, "data", "gu-acts.json")  # code -> act text, so a parser change needs no new requests
_acts = None


def act_text(e):
    global _acts
    if _acts is None:
        _acts = json.load(open(ACTS, encoding="utf-8")) if os.path.exists(ACTS) else {}
    if e["code"] not in _acts:
        page = get(ACT.format(e["date"], e["code"], urllib.parse.quote(e["type"])))
        _acts[e["code"]] = text(re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", page))
        json.dump(_acts, open(ACTS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return _acts[e["code"]]


def _holiday(d):
    """Sunday or Italian national holiday: a deadline falling on one moves to the next working day."""
    y = d.year
    a, b, c = y % 19, y // 100, y % 100  # Easter (Meeus/Jones/Butcher), for Easter Monday
    h = (19 * a + b - b // 4 - (b - (8 * b + 13) // 25 + 1) // 3 + 15) % 30
    l = (32 + 2 * (b % 4) + 2 * (c // 4) - h - c % 4) % 7
    m = (a + 11 * h + 22 * l) // 451
    easter = dt.date(y, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)
    fixed = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
    return d.weekday() == 6 or (d.month, d.day) in fixed or d == easter + dt.timedelta(days=1)


def reopen_deadline(body, date):
    """Deadline of a reopened call from its text. First N days after this GU issue (the usual "trentesimo giorno
    successivo alla data di pubblicazione ... Gazzetta Ufficiale"), moved past Sundays and holidays as the texts say;
    else one explicit date after "entro" in a sentence about applications, later than the issue and within 120 days
    (texts also name old deadlines and other dates)."""
    low = body.lower()
    issued = dt.date.fromisoformat(date)
    m = re.search(r"\b(\w+esimo|\d+)\s*(?:°\s*)?giorno\s+(?:naturale\s+)?successivo"
                  r"|\b(\d+|quindici|venti|trenta|quarantacinque|sessanta)\s+(?:\(\w+\)\s+)?giorni,?\s+(?:naturali\s+(?:e\s+)?consecutivi\s+)?"
                  r"(?:decorrent|successiv|dalla)", low)
    if m and re.search(r"pubblicazione[^.]{0,120}gazzetta", low[m.end():m.end() + 220]):
        v = m.group(1) or m.group(2)
        n = ORDINALS.get(v) or WORDS.get(v) or (int(v) if v.isdigit() else None)
        if n and 5 <= n <= 90:
            d = issued + dt.timedelta(days=n)
            while _holiday(d):
                d += dt.timedelta(days=1)
            return d.isoformat() + "T23:59"
    found = set()
    for sentence in re.split(r"(?<=[a-z0-9)»])\.\s", low):
        if "domand" not in sentence:
            continue
        for g in re.findall(r"\bentro\b(?: e non oltre)?(?: le ore [\d.:,]+)?(?: del)?(?: giorno)?\s+(?:il\s+)?(\d{1,2})\s+([a-z]+)\s+(\d{4})", sentence):
            iso = deadline(" ".join(g))
            if iso and issued < dt.date.fromisoformat(iso[:10]) <= issued + dt.timedelta(days=120):
                found.add(iso)
    return found.pop() if len(found) == 1 else None


def issue_refs(body):
    """Issues an act refers to, in order of mention: [(number, 'YYYY-MM-DD')]. The annulled publication comes first
    ("quanto pubblicato nella ... n. 77 ... è nullo ... già pubblicato nella ... n. 68")."""
    out = []
    for n, d, mo, y in re.findall(r"\bn\.\s*(\d+) del (\d{1,2})\s+([a-z]+)\s+(\d{4})", body.lower()):
        r = (int(n), dt.date(int(y), MONTHS[mo], int(d)).isoformat()) if mo in MONTHS else None
        if r and r not in out:
            out.append(r)
    return out


def apply_cancels(calls, cancels, issues=()):
    """Drop stored GU calls an annulment points to: same body, from an issue the annulment names. Returns lines to log."""
    log = []
    for code, a in cancels.items():
        if a.get("dropped"):  # a re-read may have stored it again
            calls.pop(a["dropped"]["id"], None)
            continue
        # the first referenced issue that is a GU issue I hold: the annulled publication. Never fall through to a
        # later reference, which is often the older, valid publication of the same call.
        held = {c.get("gu_issue") for c in calls.values()} | {f"n. {k.split('/')[1]} del {k[8:10]}/{k[5:7]}/{k[:4]}"
                                                              for k in issues if "/" in k}
        refs = [f"n. {n} del {d[8:10]}/{d[5:7]}/{d[:4]}" for n, d in a["refs"]]
        ref = next((r for r in refs if r in held), None)
        words = set(_words(a["summary"]))
        hit = [k for k, c in calls.items() if ref and c.get("gu_issue") == ref and c.get("ente") == a["ente"]
               and c.get("gu_code") != code and len(words & set(_words(c["title"]))) >= 3]
        if len(hit) > 1:
            score = {k: len(words & set(_words(calls[k]["title"]))) for k in hit}
            top = max(score.values())
            hit = [k for k in hit if score[k] == top]  # a tie stays ambiguous: logged, nothing dropped
        if len(hit) == 1:
            c = calls.pop(hit[0])
            a["dropped"] = {"id": hit[0], "gu_code": c.get("gu_code"), "title": c["title"][:120]}
            log.append(f"GU annulment {code} drops {c.get('gu_code')} ({a['ente'][:40]}: {c['title'][:60]})")
        elif not a.get("logged"):
            a["logged"] = True
            log.append(f"GU annulment {code} matched nothing stored, check by hand: {a['ente'][:40]}: {a['summary'][:90]}")
    return log


def main():
    reread = "--reread" in sys.argv[1:]
    if os.path.exists(BLOCKED):
        sys.exit(f"{BLOCKED} exists: not fetching")
    calls = json.load(open(DATA, encoding="utf-8")) if os.path.exists(DATA) else {}
    seen = json.load(open(ISSUES, encoding="utf-8")) if os.path.exists(ISSUES) else {}
    cancels = json.load(open(CANCELS, encoding="utf-8")) if os.path.exists(CANCELS) else {}
    last = seen.get("_listed", "")
    if last and not reread and dt.datetime.now() - dt.datetime.fromisoformat(last) < dt.timedelta(hours=LIST_EVERY_H):
        print(f"GU: list read at {last}, less than {LIST_EVERY_H} h ago: nothing to do", file=sys.stderr)
        return
    listed = issues_listed(get(LIST))
    seen["_listed"] = dt.datetime.now().isoformat(timespec="minutes")
    if not listed:
        sys.exit("no issues found in the 30-day list: page changed?")
    new = [(d, n) for d, n in listed if reread or f"{d}/{n}" not in seen]  # an issue is read once
    kinds = {}
    for d, n in new:
        entries = parse_issue(get(ISSUE.format(d, n)), d, n)
        if not entries:
            print(f"issue {n} of {d}: no entries parsed, not marking it seen", file=sys.stderr)
            continue
        for e in entries:
            kinds[e["type"]] = kinds.get(e["type"], 0) + 1
            if e["type"] in KEEP_TYPES and e["scad"] and e["ente"] and not NOT_JOBS.search(e["summary"]):
                r = record(e)
                calls[r["id"]] = r
            elif e["type"] == "RETTIFICA" and REOPEN.search(e["summary"]) and e["ente"] and not NOT_JOBS.search(e["summary"]):
                closes = reopen_deadline(act_text(e), d)
                if not closes:
                    print(f"GU reopening {e['code']}: no deadline found in the text, skipped", file=sys.stderr)
                    continue
                r = record(e)
                r.update(closes=closes, gu_type="RIAPERTURA")
                calls[r["id"]] = r
            elif (e["type"] == "ANNULLAMENTO" and CANCEL.search(e["summary"]) and not APPOINTMENT.search(e["summary"])
                  and e["code"] not in cancels):
                body = act_text(e)
                cancels[e["code"]] = {"ente": e["ente"], "summary": e["summary"], "date": d,
                                      "refs": [r for r in issue_refs(body) if r[1] != d]}
        seen[f"{d}/{n}"] = {"entries": len(entries), "fetched": dt.datetime.now().isoformat(timespec="minutes")}
    for line in apply_cancels(calls, cancels, seen):
        print(line, file=sys.stderr)
    cut = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    calls = {k: c for k, c in calls.items() if (c["closes"] or c["opens"])[:10] >= cut}
    cancels = {k: a for k, a in cancels.items() if a["date"] >= cut}
    json.dump(cancels, open(CANCELS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    tmp = DATA + ".tmp"
    json.dump(calls, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(tmp, DATA)
    json.dump(seen, open(ISSUES, "w", encoding="utf-8"), indent=0)
    print(f"{len(listed)} issues listed, {len(new)} new; types {kinds}; {len(calls)} GU calls stored", file=sys.stderr)



# --- where an issuing body is: used by build.py, not by the fetch ---------------------------------------
# Bodies whose name has no place in it. Others with none (Banca d'Italia, ministries) are national.
KNOWN = {"ESTAR": "Toscana"}
REGION_WORDS = {"FRIULI VENEZIA GIULIA": "Friuli-Venezia Giulia", "TRENTINO": "Trentino-Alto Adige",
                "ALTO ADIGE": "Trentino-Alto Adige", "ROMAGNA": "Emilia-Romagna", "VALLE D AOSTA": "Valle d'Aosta", "EMILIA ROMAGNA": "Emilia-Romagna",
                **{r.upper(): r for r in ("Abruzzo", "Basilicata", "Calabria", "Campania", "Lazio", "Liguria",
                                          "Lombardia", "Marche", "Molise", "Piemonte", "Puglia", "Sardegna",
                                          "Sicilia", "Toscana", "Umbria", "Veneto")}}


SEDE = re.compile(r"\b(?:sede(?: secondaria| operativa)? di|porto di|presso il comune di)\s+([A-Z][\w'’]+(?:\s+(?:[A-Z][\w'’]+|d[ei]l?|sul|in|di))*)")
# "per l'Ospedale Sacro Cuore di Gesu' di Benevento": the last "di X" before a comma or full stop (a religious order's
# hospital is elsewhere than the order's seat)
HOSPITAL = re.compile(r"\b(?:[Oo]spedal[ei]|[Pp]residio ospedaliero)\b[^,.;]* di ([A-Z][\w'’]+(?:\s+[A-Z][\w'’]+)*)")


def region_of(c):
    """Region of a GU record: a place named in the summary as where the work is ("borsa ... da usufruirsi presso
    la sede secondaria di Verbania", "ormeggiatori porto di Cagliari") wins over the issuing body's seat; then the
    body's name; else None (national or unknown)."""
    import geo
    for m in [*SEDE.finditer(c.get("title") or ""), *HOSPITAL.finditer(c.get("title") or "")]:
        words = m.group(1).split()
        for j in range(len(words), 0, -1):
            name = " ".join(words[:j])
            reg, _ = geo.place(name, "")
            if reg and geo._BY_COMUNE.get(geo.norm(name)):
                return reg
    return place_of(c.get("ente"))[0]


def place_of(ente):
    """-> (region, comune) of a GU issuing body, from the place its name ends with ("... DI SERIATE",
    "... - CHIERI", "... IN CAMPOBASSO"); (region, None) when only a region is named; (None, None) if unknown.
    ISTAT names via bandi's geo.py; a comune name shared by several regions gives nothing."""
    import geo
    n = geo.norm(re.sub(r"[«»\"]", " ", (ente or "").replace(" - ", " DI ")))  # "ASL TO5 - CHIERI"
    if n in KNOWN:
        return KNOWN[n], None
    words = n.split()
    # places named after a separator, last one first: "ASL ROMA 1 DI ROMA", "ASL TO5 - CHIERI"
    starts = [i + 1 for i, w in enumerate(words) if w in ("DI", "IN", "-", "DA")] + [0]
    for i in sorted(set(starts), reverse=True):
        tail = words[i:]
        for j in range(len(tail), 0, -1):  # "DESENZANO DEL GARDA", then shorter: "ROMA TOR VERGATA" -> "ROMA"
            name = " ".join(tail[:j])
            for part in [name] + (name.split(" E ") if " E " in name else []):  # "COLLEGNO E PINEROLO"
                reg, _ = geo.place(part, "")
                if reg and geo._BY_COMUNE.get(geo.norm(part)):
                    return reg, part.title()
    for w, r in REGION_WORDS.items():
        if f" {w} " in f" {n} ":
            return r, None
    import local  # a provincial capital anywhere in the name: "AZIENDA SANITARIA LOCALE AVELLINO"
    found = {(r, d) for r, caps in local.CAPITALS.items() for k, d in caps.items() if f" {k} " in f" {n} "}
    if len(found) == 1:
        return found.pop()
    return None, None


STOP = set("DI DEL DELLA DELLE DEI DEGLI DELL E ED IN PER LA LE IL LO GLI A AL ALLA DA CON SU UN UNA UNO".split())
GENERIC = set("AZIENDA SANITARIA SOCIO TERRITORIALE LOCALE OSPEDALIERA OSPEDALIERO UNIVERSITARIA UNITA ASST ASL ATS "
              "AUSL AO AOU IRCCS FONDAZIONE ISTITUTO UNIVERSITA STUDI COMUNE PROVINCIA REGIONE ENTE AGENZIA "
              "CONSIGLIO NAZIONALE RICERCHE POLICLINICO SERVIZI REGIONALE PROTEZIONE AMBIENTE CAMERA COMMERCIO INDUSTRIA "
              "ARTIGIANATO AGRICOLTURA SALUTE TUTELA".split())


def _words(s):
    import geo
    s = re.sub(r"[^A-Z0-9 ]", " ", geo.norm((s or "").replace("’", "'").replace("‘", "'")))  # "dell’Area", "C1," -> words
    return {w for w in s.split() if len(w) > 1 and w not in STOP}


KINDS = [("comune", r"\bCOMUNE\b|\bUNIONE\b|\bCOMUNITA\b"), ("uni", r"\bUNIVERSITA|\bPOLITECNICO\b|\bSCUOLA\b"),
         ("health", r"\bAZIENDA\b|\bASL\b|\bASST\b|\bIRCCS\b|\bATS\b|\bAUSL\b|\bARES\b|\bOSPEDAL"),
         ("cnr", r"\bRICERCHE\b"), ("cciaa", r"\bCOMMERCIO\b"), ("arpa", r"\bAMBIENTE\b")]
COMMON = set("CONCORSO CONCORSI PUBBLICO COPERTURA POSTO POSTI TEMPO TITOLI ESAMI ESAME PIENO INDETERMINATO DETERMINATO "
             "PROFILO AREA CATEGORIA SELEZIONE PROCEDURA PUBBLICA AVVISO BANDO UNITA PERSONALE ASSUNZIONE N RAPPORTO "
             "ESCLUSIVO COLLOQUIO CONFERIMENTO INCARICO RECLUTAMENTO VARI VARIE PROFILI".split())


def kind(ente):
    import geo
    n = geo.norm(ente)
    return next((k for k, rx in KINDS if re.search(rx, n)), "other")


def same_call(g, c):
    """How surely GU record g is inPA record c (0 = not the same call; else the share of g's job words in c). Same kind of body, deadline within 2 days, most of the
    distinctive words of the smaller ente name shared, the same number of posts when both say it, and at
    least 60% (and 3) of the words describing the job. Conservative: when unsure, keep both (a duplicate is a
    smaller harm than a call dropped)."""
    if not (g.get("closes") and c.get("closes") and c.get("ente")) or kind(g["ente"]) != kind(c["ente"]):
        return 0
    try:
        gap = abs((dt.date.fromisoformat(g["closes"][:10]) - dt.date.fromisoformat(c["closes"][:10])).days)
    except ValueError:
        return 0
    if gap > 2:
        return 0
    ge, ce = _words(g["ente"]) - GENERIC, _words(c["ente"].split("\n")[0]) - GENERIC  # inPA's ente may carry scraped junk after a newline
    if not ge or not ce or len(ge & ce) < max(1, 0.6 * min(len(ge), len(ce))) or (len(ge & ce) < 2 and min(len(ge), len(ce)) > 1):
        return 0
    bundle = gap == 0 and re.search(r"\bvari profili\b", g["title"], re.I)  # one GU notice, several inPA calls
    if g.get("posts") and c.get("posts") and g["posts"] != c["posts"] and not bundle:
        return 0
    mob = lambda t: bool(re.search(r"mobilit", t, re.I))
    if mob(g["title"]) != mob(c["title"]):
        return 0
    ct = _words(c["title"] + " " + (c.get("desc") or "")[:400])
    gt = _words(g["title"]) - GENERIC - COMMON - ge
    shared = len(gt & ct)
    score = shared / len(gt) if shared >= 3 and shared >= 0.6 * len(gt) else 0
    job = JOB.search(g["title"])  # the job alone, without legal tails ("di cui un posto riservato ai soggetti ...")
    jw = _words(job.group(1)) - GENERIC - COMMON - ge if job else set()
    if len(jw) >= 2 and jw <= ct:
        score = max(score, 0.9)
    if not score and gap == 0:  # same ente, same deadline day, and a summary too generic to compare words
        borse = re.search(r"\b(\w+) borse\b", g["title"], re.I)
        n = WORDS.get(borse.group(1).lower()) if borse else None
        if bundle or (n and n == c.get("posts")):
            score = 0.5
    return score


JOB = re.compile(r"\b(?:posti?|incarico|profilo|figur[ae]) di ([^,;.(]{6,90})", re.I)


def dedupe(gu_calls, inpa_calls):
    """GU records not already on inPA -> (kept dict, {gu id: inPA id} of the dropped ones). One inPA call
    absorbs at most one GU record, its best match: an ente's several GU calls are not one inPA call."""
    by_day = {}
    for c in inpa_calls.values():
        if c.get("closes"):
            by_day.setdefault(c["closes"][:10], []).append(c)
    pairs = []
    for k, g in gu_calls.items():
        if not g.get("closes"):
            continue
        d0 = dt.date.fromisoformat(g["closes"][:10])
        for off in range(-2, 3):
            for c in by_day.get((d0 + dt.timedelta(days=off)).isoformat(), []):
                score = same_call(g, c)
                if score:
                    pairs.append((score, -abs(off), k, c["id"]))
    dropped, used = {}, set()
    for score, _, k, cid in sorted(pairs, reverse=True):
        if k not in dropped and cid not in used:
            dropped[k] = cid
            used.add(cid)
    return {k: g for k, g in gu_calls.items() if k not in dropped}, dropped


if __name__ == "__main__":
    main()
