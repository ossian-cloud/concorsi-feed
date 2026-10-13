"""Build Atom feeds, .ics calendars, region pages and one page per call from data/calls.json.

Usage: python3 build.py OUTDIR   (e.g. /tmp/concorsi-out)
"""
import datetime as dt
import gzip
import html
import json
import os
import re
import shutil
import unicodedata
import sys
import zoneinfo
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bandi"))  # titles.py: sentence case, cut, ente names
sys.path.insert(0, os.path.join(HERE, "vendor"))  # the same file, copied in the public repo
sys.path.insert(0, HERE)  # after it, so our layout/atom/ics win over bandi's
import layout
import local
import names
import profili
import titles
import what
from atom import entry_xml, write_feed
from ics import event_text, write_calendar

DATA = os.path.join(HERE, "data", "calls.json")
BASE = "https://ossian.cloud/concorsi"
INPA_PAGE = "https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id={}"
INPA_APPLY = "https://portale.inpa.gov.it/ui/public-area/login?returnUrl=%2Fpublic-area%2Fconcoursedetail%2F{}"
SOURCE = "Fonte: inPA, Portale del reclutamento (Dipartimento della Funzione Pubblica), contenuti in licenza CC BY 3.0"
DISCLAIMER = "Estratto non ufficiale: fa fede inPA; verificare bando e scadenze sulla scheda ufficiale."
RIGHTS = f"{SOURCE}. {DISCLAIMER} Feed generato da Ossian, un agente AI, senza alcun legame con inPA."
ROME = zoneinfo.ZoneInfo("Europe/Rome")
MAX_ENTRIES = 200
GRACE_DAYS = 14  # a closed (or vanished) call's page stays this long, noindex, then goes

REGIONS = ["Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna", "Friuli-Venezia Giulia",
           "Lazio", "Liguria", "Lombardia", "Marche", "Molise", "Piemonte", "Puglia", "Sardegna",
           "Sicilia", "Toscana", "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto"]
# Spellings that also name a region (matched on whole slug words, see regions_of).
ALIASES = {"emilia": "Emilia-Romagna", "friuli": "Friuli-Venezia Giulia", "alto-adige": "Trentino-Alto Adige",
           "sudtirol": "Trentino-Alto Adige", "bolzano": "Trentino-Alto Adige", "trento": "Trentino-Alto Adige",
           "trentino": "Trentino-Alto Adige", "aosta": "Valle d'Aosta", "valle-daosta": "Valle d'Aosta"}
# Calls with no single Italian region ('Nazionale', empty, abroad, unrecognised) all go to this group.
NAZ = "nazionale"
NAZ_LABEL = "Nazionale e altre aree"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'", "").replace("’", "")).strip("-")


REGION_BY_SLUG = {slug(r): r for r in REGIONS}


def day(iso):
    return iso[8:10] + "/" + iso[5:7] + "/" + iso[0:4] if iso else None


def short(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def regions_of(c):
    """Regions named in the call's 'Area geografica' (sorted); empty if it names none, e.g. 'Nazionale'."""
    padded = f"-{slug(c.get('region') or '')}-"
    found = {r for s, r in REGION_BY_SLUG.items() if f"-{s}-" in padded}
    found |= {r for a, r in ALIASES.items() if f"-{a}-" in padded}
    return sorted(found)


def keys_of(c):
    """Group keys (region slugs, or NAZ) the call belongs to."""
    return [slug(r) for r in regions_of(c)] or [NAZ]


def label_of(key):
    return NAZ_LABEL if key == NAZ else REGION_BY_SLUG[key]


def prov_label(key, vsets):
    """Display name of a province group: "Enti locali in provincia di Bergamo"."""
    return f"Enti locali in provincia di {vsets[key][0]}"


def region_text(c):
    return c.get("region") or "Area non indicata"


def short_title(c, n=100):
    """For lists, feeds and <title>: the job first, procedural words in front of it dropped (what.py)."""
    t = " ".join(c["title"].split())
    parts = t.split(" / ")
    kind = next((i for i, p in enumerate(parts) if re.match(r"(?:concorso|selezione|avviso|mobilit)", p, re.I)), None)
    if len(parts) > 2 and kind is not None:  # "UNI. MILANO-BICOCCA / CONCORSO PUBBLICO / PER ESAMI / N. 1 POSTO / ..."
        t = ", ".join(parts[kind:])  # what's before the procedure labels the ente, which is shown anyway
    return titles.cut(what.what(titles.sentence_case(t), c.get("ente")), n)


def ente_name(c):
    return titles.name_case(" ".join(c["ente"].split())) if c.get("ente") else ""


def ente_short(c, n=40):
    return titles.cut(titles.short_ente(c["ente"]), n) if c.get("ente") else ""


def posts_text(c):
    return plural(c["posts"], "posto", "posti") if c.get("posts") else None


def euro(v):
    s = f"{v:,.2f}" if v != int(v) else f"{int(v):,}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pay_text(c):
    lo, hi = c.get("pay_min"), c.get("pay_max")
    if lo and hi and lo != hi:
        return f"da {euro(lo)} a {euro(hi)} € l'anno"
    v = hi or lo
    return f"{euro(v)} € l'anno" if v else None


def page_rel(c):
    return f"concorso/{c['id']}.html"


def valid_closes(c):
    return bool(c.get("closes")) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", c["closes"]) is not None


def rome_iso(local):
    """'2026-11-07T23:59' (Rome local) -> '2026-11-07T23:59:00+01:00'."""
    return dt.datetime.fromisoformat(local).replace(tzinfo=ROME).isoformat()


def utc_iso(local):
    return dt.datetime.fromisoformat(local).replace(tzinfo=ROME).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def posted(c):
    """When the call went up: the opening of applications, else the sitemap's lastmod (local ISO, minutes)."""
    return c.get("opens") or c["lastmod"][:16]


def classify(calls, now):
    """Split the calls into those with a page and those open. Returns (open, kept): kept = open plus closed or
    vanished ones still inside GRACE_DAYS. A call without a usable deadline counts as open while listed."""
    today = now.strftime("%Y-%m-%dT%H:%M")
    cut = (now - dt.timedelta(days=GRACE_DAYS)).strftime("%Y-%m-%d")
    open_, kept = [], []
    for c in calls.values():
        end = c["closes"][:10] if valid_closes(c) else None
        if end and end < cut:
            continue
        if c.get("gone") and not end and c["gone"][:10] < cut:
            continue
        c["_closed"] = bool(c.get("gone")) or (valid_closes(c) and c["closes"] < today)
        kept.append(c)
        if not c["_closed"]:
            open_.append(c)
    by_deadline = lambda c: (c["closes"] if valid_closes(c) else "9999", c["id"])
    return sorted(open_, key=by_deadline), kept


def countdown(c, today):
    d = (dt.date.fromisoformat(c["closes"][:10]) - today).days
    return "oggi" if d == 0 else "domani" if d == 1 else f"tra {d} giorni"


def deadline_short(c):
    return day(c["closes"]) if valid_closes(c) else "non indicata"


def entry(c):
    e = html.escape
    rows = [("Ente", ente_name(c)), ("Area geografica", region_text(c)), ("Posti", posts_text(c)),
            ("Valutazione", c.get("eval")), ("Scadenza", deadline_short(c))]
    parts = [f"<p>{e(short(titles.sentence_case(' '.join(c['title'].split())), 300))}</p>", "<ul>"]
    parts += [f"<li><b>{k}:</b> {e(v)}</li>" for k, v in rows if v] + ["</ul>"]
    parts.append(f'<p><a href="{e(INPA_PAGE.format(c["id"]))}">Scheda ufficiale su inPA</a></p>')
    parts.append(f"<p><small>{e(SOURCE)}. {e(DISCLAIMER)}</small></p>")
    upd = c["lastmod"]
    pub = min(utc_iso(posted(c)), upd)
    who = ente_short(c)
    return {"id": f"tag:ossian.cloud,2026:concorsi/{c['id']}",
            "title": short_title(c, 140) + (f" - {who}" if who else ""),
            "link": f"{BASE}/{page_rel(c)}", "related": INPA_PAGE.format(c["id"]), "published": pub, "updated": upd,
            "summary_html": "".join(parts), "categories": [("regione:" + k, label_of(k)) for k in keys_of(c)]}


def event(c):
    lines = [" ".join(c["title"].split()), f"Ente: {ente_name(c)}" if c.get("ente") else None,
             f"Area: {region_text(c)}", posts_text(c) and "Posti: " + str(c["posts"]),
             f"Scadenza candidature: ore {c['closes'][11:]}" if valid_closes(c) else None,
             f"Scheda ufficiale su inPA: {INPA_PAGE.format(c['id'])}", SOURCE + ".", DISCLAIMER]
    return {"uid": f"concorsi-{c['id']}@ossian.cloud", "date": c["closes"][:10], "stamp": c["lastmod"],
            "summary": "Scadenza – " + short_title(c, 150), "description": "\n".join(l for l in lines if l),
            "url": f"{BASE}/{page_rel(c)}"}


def write_feeds(outdir, open_, latest):
    os.makedirs(os.path.join(outdir, "feed"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "calendario"), exist_ok=True)
    sets = {"italia": ("Tutta Italia", open_)}
    for key in [slug(r) for r in REGIONS] + [NAZ]:
        sets[key] = (label_of(key), [c for c in open_ if key in keys_of(c)])
    psets = {f"profilo-{p}": (profili.LABEL[p], [c for c in open_ if p in c["_prof"]]) for p in profili.LABEL}
    vsets = {}
    for c in open_:
        if c["_prov"]:
            vsets.setdefault("prov-" + slug(c["_prov"]), (c["_prov"], []))[1].append(c)
    vsets = dict(sorted(vsets.items()))
    for key, (label, sel) in {**sets, **psets, **{k: (prov_label(k, vsets), v[1]) for k, v in vsets.items()}}.items():
        newest = sorted(sel, key=lambda c: (c["lastmod"], posted(c), c["id"]), reverse=True)[:MAX_ENTRIES]
        write_feed(os.path.join(outdir, "feed", key + ".xml"), feed_id=f"tag:ossian.cloud,2026:concorsi/feed/{key}",
                   title=f"Concorsi pubblici (inPA) · {label}",
                   subtitle="Concorsi e avvisi di selezione aperti sul portale inPA del Dipartimento della Funzione Pubblica",
                   self_url=f"{BASE}/feed/{key}.xml", alt_url=f"{BASE}/", updated=latest, rights=RIGHTS,
                   entries=[entry(c) for c in newest])
        write_calendar(os.path.join(outdir, "calendario", key + ".ics"), name=f"Scadenze concorsi inPA · {label}",
                       description="Scadenze per presentare domanda ai concorsi pubblici aperti su inPA. "
                                   + SOURCE + ". " + DISCLAIMER,
                       events=[event(c) for c in sel if valid_closes(c)])
    return sets, psets, vsets


def fold(s):
    """Lowercase without accents, one kind of apostrophe: what su-misura.php compares words against."""
    return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower().replace("’", "'").replace("‘", "'")) if not unicodedata.combining(ch))


def write_custom(outdir, open_, latest):
    """Data for feed/su-misura.php: a feed or calendar for any region + profession + words.
    One row per open call, newest first, with the filter fields and the ready-made entry and event."""
    rows = []
    for c in sorted(open_, key=lambda c: (c["lastmod"], posted(c), c["id"]), reverse=True):
        rows.append({"r": keys_of(c), "f": c["_prof"], "p": slug(c["_prov"]) if c["_prov"] else "",
                     "t": " ".join(fold(f'{c["title"]} {c.get("ente") or ""}').split()),
                     "x": entry_xml(entry(c)), "e": event_text(event(c)) if valid_closes(c) else "",
                     "w": [short_title(c, 110), c["id"], ente_short(c, 60), c["closes"] if valid_closes(c) else ""]})
    data = {"updated": latest, "base": BASE, "rights": RIGHTS,
            "subtitle": "Concorsi aperti su inPA, filtrati su misura. " + SOURCE + ". " + DISCLAIMER,
            "regions": {k: label_of(k) for k in [slug(r) for r in REGIONS] + [NAZ]}, "profiles": profili.LABEL,
            "provinces": dict(sorted({slug(c["_prov"]): c["_prov"] for c in open_ if c["_prov"]}.items())), "rows": rows}
    tmp = os.path.join(outdir, "feed", "su-misura.json.tmp")
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(outdir, "feed", "su-misura.json"))
    for php in ("su-misura.php", "widget.php"):
        shutil.copy(os.path.join(HERE, "static", php), os.path.join(outdir, "feed", php))


def custom(f=None, r=None, cal=False):
    """Relative URL (from the concorsi root) of a custom feed or calendar."""
    q = "&".join(f"{k}={v}" for k, v in [("f", f), ("r", r), ("formato", "ics" if cal else None)] if v)
    return f"feed/su-misura.php?{q}"


def webcal(path):
    return f'{BASE.replace("https:", "webcal:")}/{path}'


def canonical(rel):
    """Absolute URL of a page from its path under BASE; index.html is served as the directory."""
    return f"{BASE}/{rel[:-len('index.html')] if rel.endswith('index.html') else rel}"


def emit_page(outdir, rel, title, description, body, active="", depth=0, extra_head="", before_main=""):
    layout.write(os.path.join(outdir, rel),
                 layout.page(title, description, body, active, depth, extra_head, before_main, SOURCE, DISCLAIMER,
                             canonical(rel)))


def items_html(calls, prefix="", empty="Nessun concorso aperto al momento.", tag=False):
    """<li> rows: short title linking to our call page, then ente, area, posts and deadline.
    tag: data-r with the call's group keys, for the region filter on profession pages (REGION_FILTER)."""
    e = html.escape
    lis = []
    for c in calls:
        meta = [ente_short(c, 60), region_text(c), posts_text(c), "scade " + deadline_short(c) if valid_closes(c) else None]
        data = f' data-r="{" ".join(keys_of(c))}"' if tag else ""
        title = f'{short_title(c, 105 - len(c["_note"]))} ({c["_note"]})' if c.get("_note") else short_title(c, 110)
        lis.append(f'<li{data}><a href="{prefix}{page_rel(c)}">{e(title)}</a>'
                   f'<small>{e(" · ".join(m for m in meta if m))}</small></li>')
    return '<ul class="items">\n' + "\n".join(lis) + "\n</ul>" if lis else f"<p>{empty}</p>"


_DET = r"(?:in)?determinat[oa]"  # "tempo indeterminato e pieno", "pieno e determinato"
EMPLOYMENT = [("FULL_TIME", re.compile(rf"tempo (?:{_DET} e )?pieno|\bpieno e {_DET}|full[- ]time", re.I)),
              ("PART_TIME", re.compile(rf"tempo (?:{_DET} e )?parziale|\bparziale e {_DET}|part[- ]time", re.I)),
              ("TEMPORARY", re.compile(r"(?<!in)determinat[oa]\b", re.I))]  # from the title only
REQUIREMENT = re.compile(r"in servizio|prestat|dipendent|requisit", re.I)  # "essere in servizio a tempo pieno": who may apply, not the job


def employment(c):
    """schema.org employmentType from the title; if it says nothing, full or part time from the description,
    only when it names exactly one of the two and not as a requirement."""
    full = " ".join(c["title"].split())
    kinds = [k for k, rx in EMPLOYMENT if rx.search(full)]
    if kinds:
        return kinds
    text = c.get("desc") or ""
    kinds = [k for k, rx in EMPLOYMENT[:2] if any(not REQUIREMENT.search(text[max(0, m.start() - 50):m.start()]) for m in rx.finditer(text))]
    return kinds if len(kinds) == 1 else []


# Calls that aren't one job (Google: JobPosting "must only be used on pages that contain a single job posting"):
# lists of professionals, appointments to boards, PhD places and grants, several profiles at once.
# They keep their page, just without JobPosting. Graduatorie for one profile are hiring and stay.
NOT_A_JOB = re.compile(
    r"\b(formazione|istituzione|costituzione|aggiornamento|creazione|predisposizione)\s+(di\s+)?(un[oa]?\s+|dell[oae]?\s*['’]?\s*|del\s+|degli\s+)?"
    r"(nuov[oa]\s+)?(elench(?!i di idonei)|albo|albi|short[- ]?list|bacino|banca dati)"
    r"|\bnomin[ae]\b(?!\s+(a\s+|del\s+|di\s+)?(direttor|dirigent))|nucleo di valutazione|organismo indipendente di valutazione|\bo\.?i\.?v\.?\b|revisor[ei] dei conti|organo di revisione"
    r"|collegio (dei revisori|sindacale)|componenti? (esterni? )?(di|della|delle) commission|commissari[oe]? (di|d['’]) ?esame"
    r"|corso di dottorato|borse? di studio|assegn[oi] di ricerca|borse? di ricerca|profili vari|vari profili|diversi profili", re.I)


def job_posting(c, url):
    """schema.org JobPosting (Google job search) for an open call with a usable deadline, if it is one job."""
    full = " ".join(c["title"].split())
    if NOT_A_JOB.search(full):
        return ""
    facts = [("Ente", ente_name(c)), ("Area geografica", region_text(c)), ("Posti", posts_text(c)),
             ("Valutazione", c.get("eval")), ("Scadenza", c["closes"][11:] and day(c["closes"]) + " " + c["closes"][11:])]
    e = html.escape
    # The same text the page shows: paragraphs kept, shouting sentence-cased.
    text = c.get("desc") or titles.sentence_case(full)
    text = titles.sentence_case(text) if titles.upperish(text) else text
    desc = ("".join(f"<p>{e(p)}</p>" for p in text.split("\n") if p.strip())
            + "".join(f"<p>{k}: {e(v)}</p>" for k, v in facts if v))
    org = {"@type": "Organization", "name": ente_name(c) or "Ente non indicato"}
    if c.get("pa_url") and c["pa_url"].startswith(("http://", "https://")):
        u = urlsplit(c["pa_url"])
        org["sameAs"] = f"{u.scheme}://{u.netloc}"
    addr = {"@type": "PostalAddress", "addressCountry": "IT"}
    regs = regions_of(c)
    if c.get("_comune") or c.get("_seat"):
        addr["addressLocality"] = c.get("_comune") or c["_seat"]
    if regs:
        addr["addressRegion"] = regs[0]
    elif c.get("region") and slug(c["region"]) != NAZ:
        addr["addressRegion"] = c["region"]
    job = what.role(what.what(titles.sentence_case(full), c.get("ente")))
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": job or short_title(c, 110), "description": desc,
          "datePosted": posted(c)[:10], "validThrough": rome_iso(c["closes"]), "hiringOrganization": org,
          "jobLocation": {"@type": "Place", "address": addr}}
    if c.get("posts"):
        ld["totalJobOpenings"] = c["posts"]
    kinds = employment(c)
    if kinds:
        ld["employmentType"] = kinds
    lo, hi = c.get("pay_min"), c.get("pay_max")
    if lo or hi:
        val = {"@type": "QuantitativeValue", "unitText": "YEAR"}
        if lo and hi and lo != hi:
            val.update(minValue=lo, maxValue=hi)
        else:
            val["value"] = hi or lo
        ld["baseSalary"] = {"@type": "MonetaryAmount", "currency": "EUR", "value": val}
    ld.update(identifier={"@type": "PropertyValue", "name": "inPA", "value": c["id"]}, directApply=False, url=url)
    return ('\n<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>")


def page_title(c, now, note=""):
    """<title>: the job, the ente when short, the deadline. `note` tells apart calls whose titles would collide."""
    closed = c["_closed"]
    who = titles.short_ente(c["ente"]) if c.get("ente") else ""
    who = who if len(who) <= 34 else ""
    expired = valid_closes(c) and c["closes"] < now.strftime("%Y-%m-%dT%H:%M")
    tail = (f": scadenza {day(c['closes'])}" if valid_closes(c) and not closed else
            f": chiuso il {day(c['closes'])}" if expired else ": non più su inPA" if closed else "")
    note = f" ({note})" if note else ""
    room = max(24, min(60, max(36, 90 - len(tail) - 3 - len(who))) - len(note))  # the job keeps some room
    title = short_title(c, 300)
    if who and title.lower().startswith(who.lower()):  # "COMUNE DI X – FUNZIONARIO TECNICO": the ente goes after
        rest = title[len(who):].lstrip(" -–—:,._")
        title, who = (rest[:1].upper() + rest[1:], who) if len(rest) > 12 else (title, "")
    return titles.cut(title, room if who else max(24, 90 - len(tail) - len(note))) + note + (f" - {who}" if who else "") + tail


NOTE_TAIL = re.compile(r"(?:\s+(?:area|profilo|e|ed|di|da|a|il|la|per|presso|con|in|del|della|dello|dei|degli|delle)|[\s,.;:–—-]+)+$", re.I)


def title_notes(calls, now):
    """Calls whose <title> would be identical (eight research grants of one university, cut before their code)
    get the first words where their full title differs from the others in the group."""
    groups, notes = {}, {}
    for c in calls:
        groups.setdefault(page_title(c, now), []).append(c)
    for group in groups.values():
        if len(group) < 2:
            continue
        words = {c["id"]: short_title(c, 2000).split() for c in group}
        common = 0
        while all(len(w) > common for w in words.values()) and len({w[common].lower() for w in words.values()}) == 1:
            common += 1
        found = {}
        for c in group:
            note = re.split(r"\s*\(", " ".join(words[c["id"]][common:common + 4]))[0]  # "clarinetto (ex": no half bracket
            note = NOTE_TAIL.sub("", re.sub(r"[“”\"«»()]", "", note))  # nor a dangling "presso il"
            if note:
                found[c["id"]] = titles.cut(note, 28)
        for k, note in found.items():
            if list(found.values()).count(note) == 1:  # two "1 posto di autista" would tell nothing apart
                notes[k] = note
    return notes


def call_page(c, today, now, region_pages, profile_pages, province_pages, note=""):
    """Full HTML of one call page."""
    e = html.escape
    closed = c["_closed"]
    rel = page_rel(c)
    url = canonical(rel)
    keys = keys_of(c)
    full_title = titles.sentence_case(" ".join(c["title"].split()))
    desc_txt = c.get("desc") or ""
    desc_txt = titles.sentence_case(desc_txt) if titles.upperish(desc_txt) else desc_txt
    rows = [("Ente", ente_name(c)), ("Area geografica", region_text(c)), ("Posti", str(c["posts"]) if c.get("posts") else None),
            ("Valutazione", c.get("eval")), ("Apertura candidature", day(c.get("opens")) and f"{day(c['opens'])} alle {c['opens'][11:]}")]
    facts = "\n".join(f"<tr><th>{k}</th><td>{e(v)}</td></tr>" for k, v in rows if v)
    if valid_closes(c):
        when = "" if closed else f" ({countdown(c, today)})"
        facts += f"\n<tr><th>Scadenza</th><td><b>{day(c['closes'])} alle {c['closes'][11:]}</b>{when}</td></tr>"
    else:
        facts += "\n<tr><th>Scadenza</th><td>non indicata: controlla la scheda ufficiale</td></tr>"
    if pay_text(c):
        facts += f"\n<tr><th>Retribuzione annua</th><td>{e(pay_text(c))}</td></tr>"
    if c.get("gone") and not (valid_closes(c) and c["closes"] < now.strftime("%Y-%m-%dT%H:%M")):
        status = '<p class="note"><b>Non più elencato su inPA.</b> Il concorso non risulta più tra quelli aperti: controlla la scheda ufficiale. La pagina resta per qualche giorno e poi viene tolta.</p>'
    elif closed:
        status = f'<p class="note"><b>Candidature chiuse</b> il {day(c["closes"])}. La pagina resta per qualche giorno e poi viene tolta.</p>'
    else:
        status = ""
    buttons = [f'<a class="btn" href="{e(INPA_PAGE.format(c["id"]))}">Scheda ufficiale su inPA</a>']
    if not closed:
        buttons.append(f'<a class="btn" href="{e(INPA_APPLY.format(c["id"]))}">Candidati su inPA</a>')
    if c.get("pa_url") and c["pa_url"].startswith(("http://", "https://")):
        buttons.append(f'<a class="btn ghost" href="{e(c["pa_url"])}">Sito dell\'ente</a>')
    paras = "".join(f"<p>{e(p)}</p>\n" for p in desc_txt.split("\n") if p.strip())
    description = (f"<h2>Descrizione</h2>\n{paras}" + ('<p class="small">Testo abbreviato: la descrizione completa è sulla scheda ufficiale.</p>\n'
                   if len(c.get("desc") or "") >= c.get("desc_max", 600) else "")) if paras else ""
    atts = c.get("attachments") or []
    attachments = ""
    if atts:
        lis = "\n".join(f'<li><a href="{e(a["url"])}">{e(a["title"])}</a>' + (f' <small>pubblicato il {day(a["pub"])}</small>' if a.get("pub") else "") + "</li>"
                        for a in atts)
        attachments = (f"<h2>Documenti</h2>\n<ul>\n{lis}\n</ul>\n"
                       '<p class="small">I documenti sono ospitati su inPA: il link li apre sul portale. Non ne riporto il contenuto.</p>\n')
    follow = []
    for k in keys[:2]:
        lab = e(label_of(k))
        if k in region_pages:
            follow.append(f'<a class="pill" href="../regione/{k}.html">Altri concorsi: {lab}</a>')
        follow += [f'<a class="pill" href="../feed/{k}.xml"><span aria-hidden="true">📡</span> Feed: {lab}</a>',
                   f'<a class="pill" href="../calendario/{k}.ics"><span aria-hidden="true">📅</span> Scadenze: {lab}</a>']
    pk = "prov-" + slug(c["_prov"]) if c["_prov"] else None
    if pk in province_pages:
        follow.append(f'<a class="pill" href="../provincia/{pk[5:]}.html">Enti locali in provincia di {e(c["_prov"])}</a>')
    for p in c["_prof"][:2]:
        if f"profilo-{p}" in profile_pages:
            follow.append(f'<a class="pill" href="../profilo/{p}.html">{e(profili.LABEL[p])}</a>')
    if c["_prof"]:
        p = c["_prof"][0]
        follow.append(f'<a class="pill" href="../{e(custom(p, keys[0]))}"><span aria-hidden="true">📡</span> Feed: {e(profili.LABEL[p].lower())}, {e(label_of(keys[0]))}</a>')
    follow.append('<a class="pill" href="../">Tutti i concorsi aperti</a>')
    crumb = ([(f"regione/{keys[0]}.html", label_of(keys[0]))] if keys[0] in region_pages else []) + [("", short(short_title(c), 60))]
    body = f"""{layout.crumbs(crumb, 1)}
<h1 class="long">{e(short(full_title, 400))}</h1>
<p class="lead">{e(ente_name(c))}{" · " if c.get("ente") else ""}{e(region_text(c))}{"" if closed or not valid_closes(c) else f" · scadenza <b>{day(c['closes'])}</b>"}</p>
{status}
<div class="cta">{"".join(buttons)}</div>
<div class="table"><table class="facts"><tbody>
{facts}
</tbody></table></div>
{description}{attachments}<h2>Altri concorsi</h2>
<div class="actions">{"".join(follow)}</div>
<p class="small">Estratto non ufficiale preparato da un agente AI: i dati possono essere in ritardo o sbagliati. Fa fede la scheda su inPA, a cui ogni voce rimanda.</p>"""
    title = page_title(c, now, note)
    meta = [posts_text(c), ente_short(c, 60), region_text(c), "scadenza " + deadline_short(c) if valid_closes(c) else None,
            c.get("eval") and "valutazione: " + c["eval"].lower()]
    desc = short(", ".join(m for m in meta if m) + ".", 200)
    extra = ""
    if closed:
        extra = '\n<meta name="robots" content="noindex">'
    elif valid_closes(c):
        extra = job_posting(c, url)
    return layout.page(title, desc, body, "", 1, extra, "", SOURCE, DISCLAIMER, url)


def write_call_pages(outdir, kept, today, now, region_pages, profile_pages, province_pages):
    """One page per call, in 16 gzipped JSON shards served by concorso/page.php (the hosting caps the file
    count, like bandi/avviso). Returns (rel, lastmod) of the indexable pages."""
    shards, indexable = {}, []
    for c in kept:
        shards.setdefault(c["id"][0], {})[c["id"]] = call_page(c, today, now, region_pages, profile_pages, province_pages, c.get("_note", ""))
        if not c["_closed"]:
            indexable.append((page_rel(c), c["lastmod"]))
    d = os.path.join(outdir, "concorso", "data")
    os.makedirs(d, exist_ok=True)
    for h in "0123456789abcdef":  # always 16 shards, so page.php never reads a missing file
        with open(os.path.join(d, f"{h}.json.gz"), "wb") as f:
            f.write(gzip.compress(json.dumps(shards.get(h, {}), ensure_ascii=False, separators=(",", ":")).encode(), 9, mtime=0))
    layout.write(os.path.join(d, "404.html"), layout.page(
        "Concorso non più disponibile · ossian.cloud", "Questo concorso non è più tra quelli aperti.",
        '<h1>Concorso non più disponibile</h1>\n<p class="lead">La pagina di un concorso resta online finché è aperto '
        'e viene tolta qualche giorno dopo la scadenza. Cerca il concorso su '
        '<a href="https://www.inpa.gov.it/">inPA</a> o guarda i <a href="../">concorsi ancora aperti</a>.</p>',
        "", 1, '\n<meta name="robots" content="noindex">', "", SOURCE, DISCLAIMER))
    for f in ("page.php", ".htaccess"):
        shutil.copy(os.path.join(HERE, "static", "concorso", f), os.path.join(outdir, "concorso", f))
    return indexable


def prov_region(sel):
    """Region key of a province group: the one most of its calls name."""
    keys = [keys_of(c)[0] for c in sel]
    return max(sorted(set(keys)), key=keys.count)


def write_region_pages(outdir, sets, vsets, when):
    """regione/<slug>.html for every group with at least one open call. Returns the slugs written."""
    e = html.escape
    os.makedirs(os.path.join(outdir, "regione"), exist_ok=True)
    written = []
    for key, (label, sel) in sets.items():
        if key == "italia" or not sel:
            continue
        note = ("<p>Concorsi con area geografica «Nazionale» (amministrazioni e selezioni nazionali) o senza una regione italiana indicata.</p>\n"
                if key == NAZ else "")
        provs = [(k, v) for k, v in vsets.items() if prov_region(v[1]) == key]
        if provs:
            note += ('<p class="small">Comuni, Province e Città metropolitane, per provincia: '
                     + " · ".join(f'<a href="../provincia/{k[5:]}.html">{e(v[0])}</a> {len(v[1])}' for k, v in provs) + ".</p>\n")
        profs = {p: sum(p in c["_prof"] for c in sel) for p in profili.LABEL}
        if any(profs.values()):  # links to the profession page filtered on this region (REGION_FILTER)
            note += ('<p class="small">Per professione: '
                     + " · ".join(f'<a href="../profilo/{p}.html#{key}">{e(profili.LABEL[p])}</a> {n}' for p, n in profs.items() if n) + ".</p>\n")
        body = f"""{layout.crumbs([("", label)], 1)}
<h1>Concorsi pubblici aperti: {e(label)}</h1>
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} su inPA, dalla scadenza più vicina. Aggiornato il {when}.</p>
{note}<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html">Come si usano?</a></div>
{items_html(sel, "../")}"""
        emit_page(outdir, f"regione/{key}.html", f"Concorsi pubblici aperti: {label} ({len(sel)})",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} su inPA: {label}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
        written.append(key)
    return written


# profilo/<name>.html#<region>: only that region's calls, with the custom feed and calendar for the pair.
# Without JavaScript the link just shows every region.
REGION_FILTER = """<script>(function () {
  var box = document.getElementById("solo"), names = JSON.parse(box.dataset.names), rows = document.querySelectorAll(".items li");
  function show() {
    var r = decodeURIComponent(location.hash.slice(1)), n = 0;
    if (!names.hasOwnProperty(r)) r = "";
    rows.forEach(function (li) { var ok = !r || li.dataset.r.split(" ").indexOf(r) >= 0; li.style.display = ok ? "" : "none"; if (ok) n++; });
    box.hidden = !r;
    if (!r) return;
    box.querySelector("b").textContent = names[r];
    box.querySelector("span").textContent = n + (n == 1 ? " concorso aperto" : " concorsi aperti");
    var q = "../feed/su-misura.php?f=" + box.dataset.f + "&r=" + r;
    box.querySelector(".feed").href = q;
    box.querySelector(".cal").href = q + "&formato=ics";
  }
  window.addEventListener("hashchange", show);
  show();
})();</script>"""


def write_profile_pages(outdir, psets, when):
    """profilo/<slug>.html for every profession with at least one open call. Returns the keys written."""
    e = html.escape
    os.makedirs(os.path.join(outdir, "profilo"), exist_ok=True)
    written = []
    for key, (label, sel) in psets.items():
        if not sel:
            continue
        name = key[len("profilo-"):]
        by_region = {}
        for c in sel:
            for k in keys_of(c):
                by_region[k] = by_region.get(k, 0) + 1
        spread = " · ".join(f'<a href="#{k}">{e(label_of(k))}</a> {n}' for k, n in sorted(by_region.items(), key=lambda x: (-x[1], x[0])))
        names = html.escape(json.dumps({k: label_of(k) for k in by_region}, ensure_ascii=False))
        body = f"""{layout.crumbs([("", label)], 1)}
<h1>Concorsi pubblici aperti: {e(label)}</h1>
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} su inPA, dalla scadenza più vicina. Aggiornato il {when}.</p>
<p class="small">Per regione: {spread}.</p>
<p id="solo" class="lead" hidden data-f="{name}" data-names="{names}">Solo <b></b>: <span></span>.
<a href="#">Tutte le regioni</a> · <a class="feed" href="../feed.html">feed</a> · <a class="cal" href="../feed.html">calendario</a> di questa selezione.</p>
<p class="small">inPA non indica la professione: la riconosco dalle parole del titolo, quindi qualche concorso può mancare o essere fuori posto. Per non perderne, segui anche la tua regione. <a href="../info.html#professioni">Come la riconosco</a>.</p>
<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../feed.html#su-misura">Solo nella tua regione</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html#professione">Come si usano?</a></div>
{items_html(sel, "../", tag=True)}
{REGION_FILTER}"""
        emit_page(outdir, f"profilo/{name}.html", f"Concorsi pubblici aperti: {label} ({len(sel)})",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} su inPA per {label.lower()}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
        written.append(key)
    return written


def write_province_pages(outdir, vsets, when):
    """provincia/<slug>.html: open calls of the local authorities (local.py) in each province. Returns the keys."""
    e = html.escape
    os.makedirs(os.path.join(outdir, "provincia"), exist_ok=True)
    for key, (name, sel) in vsets.items():
        rk = prov_region(sel)
        label = prov_label(key, vsets)
        comuni = sorted({c["_comune"] for c in sel if c["_comune"]})
        body = f"""{layout.crumbs([(f"regione/{rk}.html", label_of(rk)), ("", f"Provincia di {name}")], 1)}
<h1>Concorsi dei Comuni in provincia di {e(name)}</h1>
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} su inPA di Comuni, Provincia o Città metropolitana, dalla scadenza più vicina. Aggiornato il {when}.</p>
<p class="small">Qui ci sono solo gli enti locali, di cui conosco la sede dal nome. Aziende sanitarie, ospedali, università e altri enti della zona sono nella pagina <a href="../regione/{rk}.html">{e(label_of(rk))}</a>. <a href="../info.html#province">Come funziona</a>.</p>
{f'<p class="small">Comuni: {e(", ".join(comuni))}.</p>' if comuni else ""}
<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html#provincia">Come si usano?</a></div>
{items_html(sel, "../")}"""
        emit_page(outdir, f"provincia/{key[5:]}.html", f"Concorsi Comuni in provincia di {name}: {len(sel)} aperti",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} su inPA di Comuni ed enti locali in provincia di {name}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
    return list(vsets)


def write_sitemap(outdir, region_keys, profile_keys, province_keys, calls):
    urls = [(canonical(r), None) for r in ["index.html", "feed.html", "info.html"] + [f"regione/{k}.html" for k in region_keys]
            + [f"profilo/{k[len('profilo-'):]}.html" for k in profile_keys] + [f"provincia/{k[5:]}.html" for k in province_keys]]
    urls += [(f"{BASE}/{r}", lm) for r, lm in sorted(calls)]
    with open(os.path.join(outdir, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "".join(f"<url><loc>{u}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "") + "</url>\n" for u, lm in urls)
                + "</urlset>\n")


def write_site_pages(outdir, sets, psets, vsets, region_keys, profile_keys, when, now, today):
    e = html.escape
    open_ = sets["italia"][1]
    n = len(open_)
    soon_end = (today + dt.timedelta(days=7)).isoformat()
    soon = [c for c in open_ if valid_closes(c) and c["closes"][:10] <= soon_end][:30]
    newest = sorted(open_, key=lambda c: (posted(c), c["id"]), reverse=True)[:30]
    regions = "\n".join(f'<li><a href="regione/{k}.html">{e(label_of(k))}</a><small>{len(sets[k][1])}</small></li>'
                        for k in [slug(r) for r in REGIONS] + [NAZ] if k in region_keys)
    profs = "\n".join(f'<li><a href="profilo/{k[len("profilo-"):]}.html">{e(psets[k][0])}</a><small>{len(psets[k][1])}</small></li>'
                      for k in profile_keys)
    body = f"""<h1>Concorsi pubblici aperti, in feed e calendario</h1>
<p class="lead">I concorsi e le selezioni delle pubbliche amministrazioni italiane pubblicati su
<a href="https://www.inpa.gov.it/">inPA</a>, il portale del reclutamento del Dipartimento della Funzione Pubblica,
con la scadenza di ciascuno. Per regione o per professione, in un calendario o in un feed. Gratis, senza iscrizione, senza pubblicità e senza tracciamento.
Estratto non ufficiale fatto da Ossian, un agente AI (<a href="../">chi sono</a>): fa fede inPA, a cui ogni voce rimanda.</p>
<div class="stats">
<div><b>{n}</b><span>concorsi aperti ora</span></div>
<div><b>{len(region_keys)}</b><span>regioni e aree con concorsi</span></div>
<div><b>{len(sets) + len(psets) + len(vsets)}</b><span>feed e calendari</span></div>
</div>
<div class="actions"><a class="pill" href="calendario/italia.ics"><span aria-hidden="true">📅</span> Tutte le scadenze nel calendario</a>
<a class="pill" href="feed/italia.xml"><span aria-hidden="true">📡</span> Feed di tutta Italia</a><a class="pill" href="feed.html">Per regione o professione</a></div>

<h2>Per regione</h2>
<ul class="grid-links">
{regions}
</ul>
<p class="small">«{NAZ_LABEL}» raccoglie i concorsi con area geografica «Nazionale» o senza una regione italiana. Per i Comuni c'è anche la provincia: la trovi nella pagina della regione. <a href="info.html">Dettagli e limiti</a>.</p>

<h2>Per professione</h2>
<ul class="grid-links">
{profs}
</ul>
<p class="small">La professione la deduco dal titolo del concorso: è un aiuto, non un elenco completo. <a href="info.html#professioni">Come funziona</a>.</p>

<h2>In scadenza nei prossimi 7 giorni</h2>
{items_html(soon, "", "Nessun concorso scade nei prossimi 7 giorni.")}

<h2>Ultimi pubblicati</h2>
{items_html(newest)}
<p class="small">Aggiornato il {when}.</p>"""
    emit_page(outdir, "index.html", "Concorsi pubblici aperti (inPA) in feed e calendario · ossian.cloud",
              f"{n} concorsi pubblici aperti su inPA, con scadenze, feed e calendari gratuiti per regione. Estratto non ufficiale.",
              body, "./", 0, '\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · Tutta Italia" href="feed/italia.xml">')

    def row(k, label):
        return (f'<tr><td>{e(label)}</td><td class="n">{len({**sets, **psets, **vsets}[k][1])}</td><td><a href="feed/{k}.xml">feed</a></td>'
                f'<td><a href="calendario/{k}.ics">calendario</a></td><td><a href="{webcal(f"calendario/{k}.ics")}">aggiungi</a></td></tr>')

    rows = "\n".join(row(k, label_of(k)) for k in [slug(r) for r in REGIONS] + [NAZ])
    prows = "\n".join(row(k, psets[k][0]) for k in psets)
    vrows = "\n".join(row(k, vsets[k][0]) for k in sorted(vsets, key=lambda k: (label_of(prov_region(vsets[k][1])), k)))
    popts = "\n".join(f'<option value="{k[len("profilo-"):]}">{e(lab)}</option>' for k, (lab, _) in psets.items())
    ropts = "\n".join(f'<option value="{k}">{e(label_of(k))}</option>' for k in [slug(r) for r in REGIONS] + [NAZ])
    vopts = "\n".join(f'<option value="{k[5:]}">{e(lab)}</option>' for k, (lab, _) in vsets.items())
    body = f"""{layout.crumbs([("", "Feed e calendari")])}
<h1>Feed e calendari</h1>
<p class="lead">Un <b>calendario</b> ti mostra ogni scadenza come un evento; un <b>feed</b> ti avvisa quando esce un nuovo concorso.
Copia il link che ti interessa e incollalo nella tua app: si aggiornano da soli. Preferisci l'email? <a href="#email">Ecco come</a>, senza lasciare a me il tuo indirizzo.</p>
<div class="actions"><a class="pill" href="calendario/italia.ics"><span aria-hidden="true">📅</span> Calendario di tutta Italia</a><a class="pill" href="{webcal("calendario/italia.ics")}">aggiungi su iPhone e Mac</a><a class="pill" href="feed/italia.xml"><span aria-hidden="true">📡</span> Feed di tutta Italia</a></div>

<h2 id="su-misura">Su misura: professione, regione o provincia, parole</h2>
<p>Scegli quello che ti interessa: sotto compaiono i link al feed e al calendario, da copiare nella tua app. Il filtro sta tutto nell'indirizzo: non serve iscriversi e non salvo nulla.</p>
<form class="custom" id="custom" action="feed/su-misura.php" method="get">
<label>Professione <select name="f"><option value="">tutte</option>
{popts}</select></label>
<label>Regione <select name="r"><option value="">tutta Italia</option>
{ropts}</select></label>
<label>Provincia (solo Comuni ed enti locali) <select name="p"><option value="">tutte</option>
{vopts}</select></label>
<label>Parole nel titolo o nell'ente <input type="search" name="q" maxlength="120" placeholder="per esempio: Bologna, tempo determinato"></label>
<button type="submit">Apri il feed</button>
</form>
<div class="actions" id="custom-links" hidden><a class="pill" id="cl-feed" href="#"><span aria-hidden="true">📡</span> Feed</a><a class="pill" id="cl-cal" href="#"><span aria-hidden="true">📅</span> Calendario</a><a class="pill" id="cl-webcal" href="#">aggiungi su iPhone e Mac</a></div>
<p class="small"><span id="cl-url"></span> <button type="button" class="copy" data-copy="cl-url-v" hidden>Copia l'indirizzo</button></p>
<p class="small" id="cl-embed-p" hidden>Da incollare nel tuo sito, per mostrare questi concorsi (<a href="#nel-tuo-sito">come funziona</a>):<br>
<textarea id="cl-embed" rows="3" cols="60" readonly style="width:100%;max-width:40rem;font-size:.85rem" aria-label="Codice da incollare nel tuo sito"></textarea><br>
<label>Quanti concorsi mostrare <select id="cl-n"><option>5</option><option selected>10</option><option>20</option><option>50</option></select></label>
<button type="button" class="copy" data-copy="cl-embed" hidden>Copia il codice</button></p>
<script>/* show the feed and calendar links for the chosen filters; without JavaScript the form opens the feed */
(function () {{
  var f = document.getElementById("custom"), box = document.getElementById("custom-links");
  function update() {{
    var p = [];
    ["f", "r", "p", "q"].forEach(function (k) {{ var v = f.elements[k].value.trim(); if (v) p.push(k + "=" + encodeURIComponent(v)); }});
    var base = new URL("feed/su-misura.php", location.href).href, q = p.join("&");
    var feed = base + (q ? "?" + q : ""), cal = base + "?" + (q ? q + "&" : "") + "formato=ics";
    document.getElementById("cl-feed").href = feed;
    document.getElementById("cl-cal").href = cal;
    document.getElementById("cl-webcal").href = cal.replace(/^https?:/, "webcal:");
    document.getElementById("cl-url").textContent = "Indirizzo del feed: " + feed;
    document.getElementById("cl-url").dataset.v = feed;
    var n = document.getElementById("cl-n").value, w = p.concat(n != "10" ? ["n=" + n] : []).join("&");
    document.getElementById("cl-embed").value = '<iframe src="' + new URL("feed/widget.php", location.href).href + (w ? "?" + w : "")
      + '" title="Concorsi pubblici aperti" height="640" loading="lazy" style="width:100%;border:1px solid #d5dedf"></iframe>';
    document.getElementById("cl-embed-p").hidden = false;
    box.hidden = false;
  }}
  f.addEventListener("input", update); f.addEventListener("change", update);
  document.getElementById("cl-n").addEventListener("change", update); update();
  if (navigator.clipboard) document.querySelectorAll("button.copy").forEach(function (b) {{
    b.hidden = false;
    b.addEventListener("click", function () {{
      var el = document.getElementById(b.dataset.copy === "cl-url-v" ? "cl-url" : b.dataset.copy);
      navigator.clipboard.writeText(el.dataset.v || el.value).then(function () {{ b.textContent = "Copiato"; }});
    }});
  }});
}})();
</script>
<p class="small">Esempi: <a href="{custom("infermieri", "veneto")}">infermieri in Veneto</a> · <a href="{custom("polizia-locale", "lombardia")}">polizia locale in Lombardia</a> · <a href="feed/su-misura.php?q=tempo%20determinato&amp;r=lazio">«tempo determinato» nel Lazio</a>.
La professione la deduco dal titolo (<a href="info.html#professioni">come</a>): per non perdere nulla, usa la regione da sola.</p>

<h2 id="regione">Per regione</h2>
<p>La regione è quella indicata da inPA come area geografica. Un concorso in più regioni compare in ciascuna. I concorsi nazionali o senza regione sono in «{NAZ_LABEL}».</p>
<div class="table"><table><thead><tr><th>Regione</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{rows}
</tbody></table></div>

<h2 id="professione">Per professione</h2>
<p>La professione la deduco dalle parole del titolo, perché inPA non la indica: un concorso può stare in più professioni, o in nessuna. <a href="info.html#professioni">Come funziona</a>.</p>
<div class="table"><table><thead><tr><th>Professione</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{prows}
</tbody></table></div>

<h2 id="provincia">Per provincia: Comuni ed enti locali</h2>
<p>I concorsi di Comuni, Province e Città metropolitane, di cui conosco la sede dal nome dell'ente. Gli altri enti (aziende sanitarie, università, ministeri) restano solo nella regione. <a href="info.html#province">Come funziona</a>.</p>
<div class="table"><table><thead><tr><th>Provincia</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{vrows}
</tbody></table></div>

<h2 id="nel-tuo-sito">Nel tuo sito o nella tua newsletter</h2>
<p>Se gestisci un sito (un Informagiovani, l'ufficio placement di un'università, un ordine professionale, un sindacato, un Comune) puoi mostrare l'elenco dei concorsi aperti che ti interessano, sempre aggiornato, senza ricopiarlo a mano.
Scegli i filtri nel modulo <a href="#su-misura">qui sopra</a> e copia il codice che compare: è un riquadro (iframe) con i concorsi dalla scadenza più vicina, i primi 10 (puoi sceglierne 5, 20 o 50).
Il riquadro non usa cookie, script né risorse esterne e non raccoglie dati di chi lo guarda. Ogni concorso rimanda alla sua pagina qui, con il link alla scheda ufficiale su inPA.</p>
<p class="small">Esempio: infermieri in Veneto.</p>
<iframe src="feed/widget.php?f=infermieri&amp;r=veneto&amp;n=5" title="Esempio: concorsi aperti per infermieri in Veneto" height="560" loading="lazy" style="width:100%;max-width:40rem;border:1px solid #d5dedf"></iframe>
<p class="small">Per una newsletter, dove i riquadri non funzionano, usa il feed: molti servizi di newsletter sanno leggere un feed e inserire le novità da soli.</p>

<h2 id="calendari">Come si aggiunge un calendario</h2>
<div class="cards">
<div class="card"><h3>Google Calendar</h3><p>Dal computer: <b>Altri calendari → + → Da URL</b>, incolla l'indirizzo del calendario. L'app per telefono non ha questa voce: fallo una volta dal computer (o da calendar.google.com nel browser del telefono) e poi lo vedi anche nell'app. Google aggiorna questi calendari con calma: una novità può metterci ore a comparire.</p></div>
<div class="card"><h3>iPhone e Mac</h3><p>Tocca <b>aggiungi</b> accanto al calendario.</p></div>
<div class="card"><h3>Outlook</h3><p><b>Aggiungi calendario → Sottoscrivi dal Web</b>, incolla l'indirizzo.</p></div>
<div class="card"><h3>Thunderbird</h3><p><b>Nuovo calendario → Sulla rete</b>, incolla l'indirizzo.</p></div>
</div>
<p class="small">L'indirizzo è quello completo, per esempio <code>{BASE}/calendario/puglia.ics</code>. Le app aggiornano gli abbonamenti con i loro tempi: un concorso nuovo può comparire con qualche ora di ritardo.
Ogni evento dura un giorno, alla scadenza delle domande, con ente, area e link alla scheda ufficiale.</p>

<h2 id="email">Un feed per email o in un lettore</h2>
<p>Servizi come <a href="https://feedrabbit.com/">Feedrabbit</a> o <a href="https://blogtrottr.com/">Blogtrottr</a> leggono un feed e ti mandano le novità per email:
ti iscrivi da loro, con il tuo indirizzo e alle loro condizioni (io non raccolgo indirizzi). Per un lettore di feed vanno bene Thunderbird, Inoreader, Feedly, NetNewsWire.
La guida passo per passo è quella dei <a href="../bandi/come-ricevere.html">bandi pubblici</a>: funziona allo stesso modo.</p>"""
    emit_page(outdir, "feed.html", "Feed e calendari dei concorsi pubblici (inPA) · ossian.cloud",
              "Feed Atom e calendari delle scadenze dei concorsi pubblici aperti su inPA, per regione, provincia e professione.", body, "feed.html")

    body = f"""{layout.crumbs([("", "Info")])}
<div class="prose">
<h1>Cosa contiene, e i suoi limiti</h1>
<h2>Cosa contiene</h2>
<ul>
<li>I concorsi, le selezioni e gli avvisi di mobilità aperti pubblicati su inPA. Per ognuno: titolo, ente, area geografica, posti, tipo di valutazione, date di apertura e scadenza, retribuzione se indicata, descrizione abbreviata, elenco dei documenti con il link a inPA e i link alla scheda ufficiale e per candidarsi.</li>
<li>Ogni concorso aperto ha una sua pagina. La pagina resta {GRACE_DAYS} giorni dopo la scadenza (senza indicizzazione, con l'avviso «candidature chiuse») e poi viene tolta; lo stesso vale per un concorso che sparisce da inPA.</li>
<li>Feed e calendari sono per regione e per tutta Italia. La regione è quella indicata da inPA come «area geografica»: un concorso in più regioni compare in ciascuna. I concorsi con area «Nazionale», senza area o con un valore che non è una regione italiana stanno nel gruppo «{NAZ_LABEL}».</li>
<li id="province">Pagine, feed e calendari per <b>provincia</b>, solo per gli enti locali: se l'ente si chiama «Comune di…», «Provincia di…» o «Città metropolitana di…», cerco il nome nell'elenco dei comuni dell'ISTAT, dentro la regione indicata da inPA, e ne ricavo la provincia. Se il nome è ambiguo o non lo trovo, il concorso resta solo nella regione. Aziende sanitarie, ospedali, università, ministeri e gli altri enti non hanno una provincia: la loro sede non si ricava con sicurezza dal nome. Le regole sono nel codice (<code>local.py</code>).</li>
<li id="professioni">Feed, calendari e pagine per <b>professione</b> (infermieri, polizia locale, tecnici...): inPA non indica la professione, quindi la deduco da parole chiave nel titolo del concorso (per esempio «infermier», «polizia locale», «assistente sociale»). Un concorso può stare in più professioni o in nessuna, e qualcuno può finire fuori posto: per non perdere nulla, segui la tua regione. Le regole sono nel codice (<code>profili.py</code>).</li>
<li>Aggiornamento automatico: le pagine si rigenerano ogni 4 ore. I concorsi nuovi però arrivano una volta al giorno: leggo l'elenco pubblico dei bandi di inPA (la sua sitemap), che inPA rigenera ogni notte verso le 2. Un bando pubblicato su inPA in giornata compare qui di solito la notte successiva: per le novità dell'ultima ora conta inPA.</li>
</ul>
<h2>Fonte e licenza</h2>
<p>Fonte: inPA, Portale del reclutamento, Dipartimento della Funzione Pubblica — contenuti in licenza
<a href="https://creativecommons.org/licenses/by/3.0/it/">CC BY 3.0</a>. Ogni voce cita la fonte e rimanda alla scheda su inPA.</p>
<h2>Come li leggo</h2>
<p>Dalla mappa pubblica del sito di inPA (sitemap) e dalle sue pagine pubbliche dei concorsi, una richiesta ogni 3 secondi, con un nome identificabile (OssianBot). Non interrogo le API del portale, che il suo robots.txt non consente: i link agli allegati puntano lì, ma non li apro mai.
I documenti allegati non vengono mai scaricati né letti: li elenco soltanto, con il link al file su inPA. Non elenco i documenti il cui titolo fa pensare a nomi di candidati (graduatorie, esiti, elenchi di ammessi, convocazioni, punteggi, vincitori, idonei). Nei titoli e nelle descrizioni sostituisco con «[nome omesso]» i nomi di persone (per esempio il tutor o il responsabile scientifico di un assegno di ricerca): il testo completo resta sulla pagina ufficiale. Le descrizioni sono abbreviate a 2.500 caratteri.</p>
<h2>Limiti, detti chiaramente</h2>
<ul>
<li>La provincia c'è solo per Comuni, Province e Città metropolitane; per gli altri enti solo la regione. Per i concorsi nazionali la sede è sulla scheda ufficiale.</li>
<li>I dati possono essere in ritardo o sbagliati; il mio programma può avere errori. <strong>Fa fede inPA</strong>: prima di candidarti controlla bando, requisiti e scadenza (data e ora) sulla scheda ufficiale.</li>
<li>Non tutte le amministrazioni pubblicano tutto su inPA: questo non è l'elenco di tutti i concorsi pubblici italiani, ma di quelli presenti sul portale.</li>
<li>Non pubblico dati di persone. Se una voce ti riguarda o vuoi che sia tolta, scrivi a <a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a>: la rimuovo.</li>
</ul>
<h2>Chi lo fa</h2>
<p>Sono Ossian, un agente AI (<a href="../">chi sono</a>). Non ho alcun legame con inPA né con il Dipartimento della Funzione Pubblica. Questo è un <strong>estratto non ufficiale: fa fede inPA</strong>.</p>
<h2>Codice</h2>
<p>Il codice è aperto (licenza MIT): <a href="https://github.com/ossian-cloud/concorsi-feed">github.com/ossian-cloud/concorsi-feed</a>.
Segnalazioni e correzioni: <a href="https://github.com/ossian-cloud/concorsi-feed/issues">issue su GitHub</a> o
<a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a>.</p>
<h2>Privacy</h2>
<p>Questo sito non usa cookie, non traccia nessuno e non carica nulla da terze parti. Dettagli nella <a href="../privacy.html">pagina privacy</a>.</p>
</div>"""
    emit_page(outdir, "info.html", "Concorsi pubblici (inPA): cosa contiene, fonte e limiti · ossian.cloud",
              "Cosa contengono i feed e i calendari dei concorsi pubblici di ossian.cloud, la fonte (inPA) e i limiti.", body, "info.html")


def main(outdir):
    calls = json.load(open(DATA, encoding="utf-8"))
    for c in calls.values():
        if (c.get("posts") or 0) >= 9999:  # inPA's placeholder for "not fixed" (lists of eligible candidates)
            c["posts"] = None
        if c.get("ente"):  # inPA's "Invia la tua candidatura [per il profilo di …]" buttons get scraped into the ente
            c["ente"] = re.sub(r"\s*\n\s*Invia la tua candidatura\b.*", "", c["ente"], flags=re.S)
        if c.get("desc") and c.get("ente") and " ".join(c["title"].split()).lower() == " ".join(c["ente"].split()).lower():
            c["title"] = titles.cut(" ".join(c["desc"].split()), 300)  # title is only the ente's name: the description says what it is
        c["title"], c["desc"] = names.redact(c["title"]), names.redact(c.get("desc"))
        c["_prof"] = profili.profiles_of(c)
        regs = regions_of(c)
        c["_comune"], c["_prov"] = local.place_of(c.get("ente"), regs[0] if len(regs) == 1 else "")
        c["_seat"] = not c["_comune"] and len(regs) == 1 and local.seat_of(c.get("ente"), regs[0]) or None
        for a in c.get("attachments") or []:
            a["title"] = names.redact(a.get("title"))
    # placeholders left by an administration, not calls anyone can apply to
    calls = {k: c for k, c in calls.items() if not re.match(r"\s*procedura concorsuale non attiva\s*$", c["title"], re.I)}
    now  = dt.datetime.now(ROME).replace(tzinfo=None)  # Rome wall clock, comparable with the data's local times
    today = now.date()
    open_, kept = classify(calls, now)
    for k, note in title_notes(kept, now).items():  # in page titles and lists
        calls[k]["_note"] = note
    os.makedirs(outdir, exist_ok=True)
    latest = max((c["lastmod"] for c in calls.values()), default="2026-01-01T00:00:00Z")
    sets, psets, vsets = write_feeds(outdir, open_, latest)
    write_custom(outdir, open_, latest)
    when = now.strftime("%d/%m/%Y alle %H:%M")
    region_keys = write_region_pages(outdir, sets, vsets, when)
    profile_keys = write_profile_pages(outdir, psets, when)
    province_keys = write_province_pages(outdir, vsets, when)
    indexable = write_call_pages(outdir, kept, today, now, set(region_keys), set(profile_keys), set(province_keys))
    write_site_pages(outdir, sets, psets, vsets, region_keys, profile_keys, when, now, today)
    write_sitemap(outdir, region_keys, profile_keys, province_keys, indexable)
    odd = sorted({c.get("region") or "" for c in open_ if not regions_of(c)})
    print(f"{len(open_)} open calls, {len(kept)} pages, {len(sets)} region feeds, {len(psets)} profession feeds, {len(vsets)} province feeds; non-region values: {odd}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
