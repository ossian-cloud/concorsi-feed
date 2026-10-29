"""Build Atom feeds, .ics calendars, region pages and one page per call from data/calls.json.

Usage: python3 build.py OUTDIR   (e.g. /tmp/concorsi-out)
"""
import datetime as dt
import gzip
import csv
import html
import io
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
import discipline
import layout
import local
import gu
import names
import profili
import studio
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
# Second source, only while GU_LIVE exists (gu.py): the Gazzetta Ufficiale, 4a serie speciale, whose reuse terms ask
# to cite it and to say the text is not authentic and the service free.
GU_ON = os.path.exists(os.path.join(HERE, "GU_LIVE")) or os.environ.get("CONCORSI_GU") == "1"  # env: local tests
GU_DATA = os.path.join(HERE, "data", "gu.json")
GU_SOURCE = ("Fonte: Gazzetta Ufficiale della Repubblica Italiana, 4ª serie speciale «Concorsi ed esami» (sommario). "
             "Testo non autentico, riprodotto gratuitamente: fa fede solo la Gazzetta Ufficiale")
GU_DISCLAIMER = ("Estratto non ufficiale. La scadenza è quella indicata dalla redazione della Gazzetta: l'unica ufficiale è nel bando, "
                 "da leggere sulla Gazzetta o sul sito dell'ente.")
if GU_ON:
    layout.TAGLINE = "Concorsi di inPA e Gazzetta Ufficiale in feed e calendario · di Ossian"
    layout.OFFICIAL = "inPA (Dipartimento della Funzione Pubblica) né con la Gazzetta Ufficiale"
    SOURCE = ("Fonti: inPA, Portale del reclutamento (Dipartimento della Funzione Pubblica), CC BY 3.0; "
              "Gazzetta Ufficiale, 4ª serie speciale, testo non autentico riprodotto gratuitamente")
    DISCLAIMER = "Estratto non ufficiale: fanno fede inPA e la Gazzetta Ufficiale; verificare bando e scadenze sulla fonte ufficiale."
RIGHTS = f"{SOURCE}. {DISCLAIMER} Feed generato da Ossian, un agente AI, senza alcun legame con {'inPA o con la Gazzetta Ufficiale' if GU_ON else 'inPA'}."
SU = "su inPA e in Gazzetta Ufficiale" if GU_ON else "su inPA"  # where the calls are, in page copy
SRC = "inPA e Gazzetta Ufficiale" if GU_ON else "inPA"  # in titles


def is_gu(c):
    return c.get("source") == "gu"


def official_url(c):
    return c["gu_url"] if is_gu(c) else INPA_PAGE.format(c["id"])


def official_label(c):
    return "Avviso in Gazzetta Ufficiale" if is_gu(c) else "Scheda ufficiale su inPA"


def source_of(c):
    return (GU_SOURCE, GU_DISCLAIMER) if is_gu(c) else (
        "Fonte: inPA, Portale del reclutamento (Dipartimento della Funzione Pubblica), contenuti in licenza CC BY 3.0",
        "Estratto non ufficiale: fa fede inPA; verificare bando e scadenze sulla scheda ufficiale.")
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
    # accents transliterated, not dropped: Forlì-Cesena -> forli-cesena (was forl-cesena until 2026-10-14)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
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
    return sorted(found) or ([c["_ente_region"]] if c.get("_ente_region") else [])


def keys_of(c):
    """Group keys (region slugs, or NAZ) the call belongs to."""
    return [slug(r) for r in regions_of(c)] or [NAZ]


def label_of(key):
    return NAZ_LABEL if key == NAZ else REGION_BY_SLUG[key]


def prov_label(key, vsets):
    """Display name of a province group: "Enti locali in provincia di Bergamo"."""
    return f"Enti locali in provincia di {vsets[key][0]}"


def region_text(c):
    if c.get("_ente_region"):  # inPA says "Nazionale" for a Comune's call
        return f"{c['_ente_region']} (su inPA: {c.get('region') or 'area non indicata'})"
    return c.get("region") or "Area non indicata"


def gu_job(t):
    """A GU summary's procedural opening, rewritten so the job comes first (lists, feeds, <title> only)."""
    m = re.match(r"(?:(?:modifica|rettifica),? e )?riapertura (?:dei )?termini(?:,? (?:e )?(?:rettifica|modifica)[^,]*?(?: ed integrazione)?)?,? "
                 r"(?:della|dello|dell['’]\s?|del)\s*(.+)", t, re.I)
    if m:  # a reopened call: short_title() says so in front
        t = m.group(1)[0].upper() + m.group(1)[1:]
    t = re.sub(r"\b((?:inter)?regionale)/((?:inter|extra)regionale)\b", r"\1 ed \2", t, flags=re.I)  # what.py cuts at "/"
    t = re.sub(r",? a valenza (?:non )?regionale,? (?:ed? )?in forma (?:autonoma|aggregata),?|,? in forma aggregata,?"
               r"|,? in forma autonoma,? a valenza (?:non )?regionale,?|,? in regime di autonomia e con valenza per [^,]+,?", "", t, flags=re.I)
    m = re.match(r"(?:procedur[ae]|valutazion[ei])(?: [\w'’-]+){0,2}(?:, per [^,]+,)? per la copertura (?:di )?(?:(\w+) )?post[oi] di ricercator[ei]\b(.*)", t, re.I)
    if m and not re.search(r"\b(?:e per|nonch[eé])\b", m.group(2), re.I):  # university researchers, as for professors below
        n = (m.group(1) or "").lower()
        if n in ("un", "uno", "una"):
            return "Ricercatore" + m.group(2)
        return (f"{NUMBER_WORDS[n]} ricercatori" if n in NUMBER_WORDS else f"{n} ricercatori" if n.isdigit() else "Ricercatori") + m.group(2)
    m = re.search(r"\bbors[ae] di (ricerca|studio)\b(.*)", t, re.I)
    if m and t.lower().startswith("conferimento"):
        where = re.search(r"presso (?:la sede(?: secondaria)? di|l[ae']\s?[^,]*? di) ([A-Z][\w'’ ]+?)(?:[.,]|\s+della|$)", m.group(2))
        many = re.search(r"\b(\w+) borse\b", t, re.I)
        n = NUMBER_WORDS.get(many.group(1).lower(), "") if many else ""
        return (f"{n} borse" if n else "Borse" if many else "Borsa") + f" di {m.group(1).lower()}" + (f" a {where.group(1)}" if where else "")
    m = re.search(r"\b(?:direttore|direzione) (?:della |di |dell[a'] ?)?(?:struttura (?:operativa )?complessa|unit[aà] operativ[ae] complesse?|u\.?o\.?c\.?|s\.?c\.?)\b\s*(.*)", t, re.I)
    if m and t.lower().startswith("conferimento"):
        rest = re.sub(r"^(?:per (?:la |l['’]|il )?(?:direzione (?:della |dell['’])?)?)?(?:di |denominata |«)?", "", m.group(1).lstrip(" ,"))
        rest = re.sub(r"^(?:S\.?C\.?|U\.?O\.?C\.?)\s+(?=[A-Z])", "", rest).strip(" ,.»")
        sub = " (supplenza)" if re.search(r"supplenz|sostitut", t, re.I) else ""
        return "Direttore di struttura complessa" + sub + (f": {rest}" if rest else "")
    m = re.match(r"(?:procedur[ae]|valutazion[ei])(?: [\w'-]+){1,3} per (?:la )?chiamata di (\w+) (professor[ei]\b.*)", t, re.I)
    if m and not re.search(r"\b(?:e per|nonch[eé])\b", m.group(2), re.I):  # mixed calls (professors and researchers) stay as they are
        n = m.group(1).lower()
        if n in ("un", "uno", "una"):
            return "Professore" + m.group(2)[len("professore"):] if m.group(2).lower().startswith("professore") else t
        return f"{NUMBER_WORDS.get(n, m.group(1))} {m.group(2)}" if n in NUMBER_WORDS or n.isdigit() else t
    return t


NUMBER_WORDS = {w: str(i) for i, w in enumerate("zero uno due tre quattro cinque sei sette otto nove dieci undici dodici "
                                                "tredici quattordici quindici sedici diciassette diciotto diciannove venti".split()) if i > 1}


def short_title(c, n=100):
    """For lists, feeds and <title>: the job first, procedural words in front of it dropped (what.py)."""
    t = " ".join(c["title"].split())
    if is_gu(c):
        t = gu_job(t)
    parts = t.split(" / ")
    kind = next((i for i, p in enumerate(parts) if re.match(r"(?:concorso|selezione|avviso|mobilit)", p, re.I)), None)
    if len(parts) > 2 and kind is not None:  # "UNI. MILANO-BICOCCA / CONCORSO PUBBLICO / PER ESAMI / N. 1 POSTO / ..."
        t = ", ".join(parts[kind:])  # what's before the procedure labels the ente, which is shown anyway
    if c.get("gu_type") == "RIAPERTURA":
        return titles.cut("Termini riaperti – " + what.what(titles.sentence_case(t), c.get("ente")), n)
    return titles.cut(what.what(titles.sentence_case(t), c.get("ente")), n)


def ente_name(c):
    return titles.name_case(" ".join(c["ente"].split())) if c.get("ente") else ""


def ente_brief(c):
    """titles.short_ente, unless that leaves only a bare acronym ("LIFE - ISTITUTO ... SANTA LUCIA IRCCS")."""
    if not c.get("ente"):
        return ""
    who = titles.short_ente(c["ente"])
    return ente_name(c) if len(who) < 6 and len(c["ente"]) > 12 else who


def ente_short(c, n=40):
    return titles.cut(ente_brief(c), n)


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


# notices posted as if they were calls: "Revoca concorso pubblico per n. 6 posti di Dirigente Psicologo" (ASP Ragusa,
# on inPA open until 2027). No page, no listing.
NOT_A_CALL = re.compile(r"^\W*(?:avviso di |comunicazione di |provvedimento di )?(?:revoca|annullamento|sospensione)\b", re.I)
# notices about a procedure already under way, mostly from Uffici Scolastici Regionali: "AVVISO APPROVAZIONE GRADUATORIA
# DI MERITO", "Calendario Prove Orali", "AVVISO CONVOCAZIONE PROVA SCRITTA". Nobody can apply to them; no page, no listing
# (the Gazzetta side already skips graduatorie and diari). Interpelli and calls that create a graduatoria stay.
# Audited 2026-10-24 on all 3,729 stored calls: 127 matches, all such notices.
NOTICE_ONLY = re.compile(r"""
 ^(?!.*(?:interpell|manifestazion\w*\s+d.\s*interesse|utilizz|attingere|\bfinalizzat\w+\s+(?:alla|all.)\s+(?:formazione|costituzione|formulazione)))
 (?:.*?\b(?:
    (?:approvazione|pubblicazione|ripubblicazione|integrazione|riformulazione|rettifica|nuova\s+formulazione)
      \W+(?:(?:della|delle|di|del|dei|nuova|nuove|ulteriore|formulazione|integrazione|integrata|integrate|rettifica|rettificata|definitive|definitiva)\W+){0,3}
      (?:graduatori\w+|elenc\w+\W+(?:degli\W+)?idone\w+|GM\b)
  | scorrimento\W+(?:della\W+)?graduatori\w+\W+di\W+merito
  | (?:calendario|diario|convocazion\w+)\W+(?:\w+\W+){0,8}?prov[ae]\b
  | avviso\W+(?:integrativo\W+(?:\w+\W+){0,4}?)?prov[ae]\b
  | (?:scorrimento|integrazione)\W+GM\d
  | esit[oi]\W+(?:della\W+|delle\W+|dei\W+)?(?:prov|selezion|concors|valutazion|colloqui)\w*
  | elenc\w+\W+(?:dei\W+)?(?:candidat\w+\W+)?(?:ammess|non\s+ammess|esclus)\w*
  | prove\W+concorsuali\W*$
 ))
""", re.I | re.X | re.S)
# USR pages titled only "D.D.G. 2939/2025 – Concorso secondaria – Classe di concorso A041": the description says
# "Si pubblica l'Avviso … relativo alle prove orali". Only for USR: elsewhere "Si allega …" also opens real calls.
USR = re.compile(r"uffici?o scolastico regionale", re.I)
NOTICE_DESC = re.compile(r"\bSi\s+(?:pubblica(?:no)?|allega(?:no)?)\b")


def notice_only(c):
    if NOTICE_ONLY.search(" ".join(c["title"].split())):
        return True
    return bool(USR.search(c.get("ente") or "") and NOTICE_DESC.search(c.get("desc") or ""))


def classify(calls, now):
    """Split the calls into those with a page and those open. Returns (open, kept): kept = open plus closed or
    vanished ones still inside GRACE_DAYS. A call without a usable deadline counts as open while listed."""
    today = now.strftime("%Y-%m-%dT%H:%M")
    cut = (now - dt.timedelta(days=GRACE_DAYS)).strftime("%Y-%m-%d")
    open_, kept = [], []
    for c in calls.values():
        if NOT_A_CALL.search(c["title"]) or notice_only(c):
            continue
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


GU_DEADLINE_NOTE = "<br><small>(indicata dalla Gazzetta Ufficiale: la data e l'ora ufficiali sono nel bando)</small>"
# reopenings have no GU deadline: gu.py reads it from the text ("entro il trentesimo giorno successivo...")
GU_REOPEN_NOTE = ("<br><small>(calcolata da me dal testo dell'avviso di riapertura: i giorni indicati dall'avviso a partire"
                  " dalla pubblicazione in Gazzetta, spostati al primo giorno non festivo. La data e l'ora ufficiali sono nel bando)</small>")
GU_PAGE_NOTE = ("Questo concorso è pubblicato nella Gazzetta Ufficiale, 4ª serie speciale, e non risulta tra i concorsi di inPA che leggo (il confronto è automatico: qualche doppione può sfuggire). "
                "Qui c'è solo il sommario della Gazzetta (testo non autentico, riprodotto gratuitamente): requisiti, "
                "modalità e scadenza ufficiale sono nel bando, che trovi in Gazzetta o sul sito dell'ente.")
GU_LEAD = (' e nella <a href="info.html#gazzetta">Gazzetta Ufficiale</a>, 4ª serie speciale, dove ci sono molti concorsi '
           "della sanità, delle università e della ricerca che su inPA mancano,")
GU_INFO = f"""<h2 id="gazzetta">Concorsi dalla Gazzetta Ufficiale</h2>
<p>Molte amministrazioni, soprattutto aziende sanitarie, ospedali, università ed enti di ricerca, pubblicano i concorsi nella
<a href="https://www.gazzettaufficiale.it/30giorni/concorsi">Gazzetta Ufficiale, 4ª serie speciale «Concorsi ed esami»</a> e non su inPA.
In un mio controllo di ottobre 2026, dei 95 concorsi di due numeri della Gazzetta solo 4 erano anche su inPA. Per questo aggiungo anche quelli.
Il conteggio completo, per tipo di ente: <a href="gazzetta-e-inpa.html">quanti concorsi sono solo in Gazzetta e quanti solo su inPA</a>.</p>
<ul>
<li>Leggo il sommario di ogni numero (esce il martedì e il venerdì) dalle pagine pubbliche della Gazzetta, una richiesta ogni 3 secondi, con un nome identificabile (OssianBot). Tengo solo le voci «concorso» e «mobilità» con una scadenza: niente graduatorie, esiti, diari delle prove, ammissioni ai dottorati o sessioni di esami di abilitazione.</li>
<li>Le <b>riaperture dei termini</b> sono elencate come concorsi, con «Termini riaperti» nel titolo. Il sommario della Gazzetta non dà la loro scadenza: la ricavo dal testo dell'avviso (di solito 30 giorni dalla pubblicazione, spostati al primo giorno non festivo), e la pagina lo dice. Quando la Gazzetta pubblica l'<b>annullamento</b> di un concorso e indica il numero in cui era uscito, tolgo quel concorso dagli elenchi.</li>
<li>Di ogni concorso c'è solo il <b>sommario</b> della Gazzetta: ente, una riga su cosa si cerca, la scadenza. Requisiti e modalità per candidarsi sono nel bando, sulla Gazzetta o sul sito dell'ente: ogni voce rimanda alla pagina della Gazzetta.</li>
<li>La <b>scadenza</b> è quella che la redazione della Gazzetta indica per facilitare la ricerca: la Gazzetta stessa avverte che l'unica ufficiale è quella scritta nel bando. Controllala sempre.</li>
<li>La <b>regione</b> la ricavo dal luogo nel nome dell'ente («… di Seriate», «… - Chieri»), cercandolo nell'elenco dei comuni dell'ISTAT; gli enti senza un luogo nel nome (Banca d'Italia, ministeri) vanno in «{NAZ_LABEL}». La provincia c'è solo per i Comuni, come per inPA.</li>
<li>Se lo stesso concorso è anche su inPA, mostro solo la scheda di inPA, che è più completa. Il confronto (stesso ente, stessa scadenza, stessa figura) è prudente: qualche doppione può restare.</li>
<li>I concorsi della Gazzetta non sono nel file CSV, che contiene solo i dati di inPA con la loro licenza.</li>
<li>Condizioni d'uso della Gazzetta: la riproduzione dei testi in formato elettronico è consentita citando la fonte e il carattere non autentico e gratuito. Quindi: fonte Gazzetta Ufficiale della Repubblica Italiana; il testo qui riportato <b>non è autentico</b> (fa fede solo la Gazzetta) e il servizio è <b>gratuito</b>.</li>
</ul>
"""
FAR_NOTE = ("<br><small>Data molto lontana: di solito indica un elenco sempre aperto o una data segnaposto. "
            "Controlla sul bando se e fino a quando si può davvero presentare domanda.</small>")


def far_deadline(c):
    """inPA has deadlines years away (2035, 2099): open lists, or placeholders. Say so rather than hide them."""
    return valid_closes(c) and c["closes"][:4] >= str(dt.date.today().year + 2)


def deadline_short(c):
    if not valid_closes(c):
        return "non indicata"
    return day(c["closes"]) + (" (data da verificare)" if far_deadline(c) else "")


def entry(c):
    e = html.escape
    rows = [("Ente", ente_name(c)), ("Area geografica", region_text(c)), ("Posti", posts_text(c)),
            ("Valutazione", c.get("eval")), ("Scadenza", deadline_short(c))]
    parts = [f"<p>{e(short(titles.sentence_case(' '.join(c['title'].split())), 300))}</p>", "<ul>"]
    parts += [f"<li><b>{k}:</b> {e(v)}</li>" for k, v in rows if v] + ["</ul>"]
    src, disc = source_of(c)
    parts.append(f'<p><a href="{e(official_url(c))}">{official_label(c)}</a></p>')
    parts.append(f"<p><small>{e(src)}. {e(disc)}</small></p>")
    upd = c["lastmod"]
    pub = min(utc_iso(posted(c)), upd)
    who = ente_short(c)
    return {"id": f"tag:ossian.cloud,2026:concorsi/{c['id']}",
            "title": short_title(c, 140) + (f" - {who}" if who else ""),
            "link": f"{BASE}/{page_rel(c)}", "related": official_url(c), "published": pub, "updated": upd,
            "summary_html": "".join(parts), "categories": [("regione:" + k, label_of(k)) for k in keys_of(c)]}


def event(c):
    lines = [" ".join(c["title"].split()), f"Ente: {ente_name(c)}" if c.get("ente") else None,
             f"Area: {region_text(c)}", posts_text(c) and "Posti: " + str(c["posts"]),
             f"Scadenza candidature: ore {c['closes'][11:]}" if valid_closes(c) else None,
             f"{official_label(c)}: {official_url(c)}", source_of(c)[0] + ".", source_of(c)[1]]
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
    # education levels (studio.py) reuse the profession machinery: profilo/<level>.html, feed/profilo-<level>.xml, f=<level>
    psets.update({f"profilo-{s}": (studio.LABEL[s], [c for c in open_ if s in c["_studio"]]) for s in studio.LABEL})
    vsets = {}
    for c in open_:
        if c["_prov"]:
            vsets.setdefault("prov-" + slug(c["_prov"]), (c["_prov"], []))[1].append(c)
    vsets = dict(sorted(vsets.items()))
    for key, (label, sel) in {**sets, **psets, **{k: (prov_label(k, vsets), v[1]) for k, v in vsets.items()}}.items():
        newest = sorted(sel, key=lambda c: (c["lastmod"], posted(c), c["id"]), reverse=True)[:MAX_ENTRIES]
        write_feed(os.path.join(outdir, "feed", key + ".xml"), feed_id=f"tag:ossian.cloud,2026:concorsi/feed/{key}",
                   title=f"Concorsi pubblici ({SRC}) · {label}",
                   subtitle="Concorsi e avvisi di selezione aperti sul portale inPA del Dipartimento della Funzione Pubblica"
                   + (" e nella Gazzetta Ufficiale, 4ª serie speciale" if GU_ON else ""),
                   self_url=f"{BASE}/feed/{key}.xml", alt_url=f"{BASE}/", updated=latest, rights=RIGHTS,
                   entries=[entry(c) for c in newest])
        write_calendar(os.path.join(outdir, "calendario", key + ".ics"), name=f"Scadenze concorsi {SRC} · {label}",
                       description=f"Scadenze per presentare domanda ai concorsi pubblici aperti {SU}. "
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
        rows.append({"r": keys_of(c), "f": c["_prof"] + c["_studio"] + c["_disc"], "p": slug(c["_prov"]) if c["_prov"] else "",
                     "t": " ".join(fold(f'{c["title"]} {c.get("ente") or ""}').split()),
                     "x": entry_xml(entry(c)), "e": event_text(event(c)) if valid_closes(c) else "",
                     "w": [short_title(c, 110), c["id"], ente_short(c, 60), c["closes"] if valid_closes(c) else ""]})
    data = {"updated": latest, "base": BASE, "rights": RIGHTS,
            "subtitle": f"Concorsi aperti {SU}, filtrati su misura. " + SOURCE + ". " + DISCLAIMER,
            "regions": {k: label_of(k) for k in [slug(r) for r in REGIONS] + [NAZ]}, "profiles": {**profili.LABEL, **studio.LABEL, **{k: f"Medici: {v}" for k, v in discipline.LABEL.items()}},
            "disciplines": list(discipline.LABEL),
            "provinces": dict(sorted({slug(c["_prov"]): c["_prov"] for c in open_ if c["_prov"]}.items())), "rows": rows}
    tmp = os.path.join(outdir, "feed", "su-misura.json.gz.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(outdir, "feed", "su-misura.json.gz"))
    for php in ("su-misura.php", "widget.php"):
        shutil.copy(os.path.join(HERE, "static", php), os.path.join(outdir, "feed", php))


def custom(f=None, r=None, cal=False):
    """Relative URL (from the concorsi root) of a custom feed or calendar."""
    q = "&".join(f"{k}={v}" for k, v in [("f", f), ("r", r), ("formato", "ics" if cal else None)] if v)
    return f"feed/su-misura.php?{q}"


def app_job(c):
    """(kind, job) for the app's card: ("Concorso a tempo determinato", "Istruttore tecnico"); either may be ""."""
    w = what.what(titles.sentence_case(" ".join(c["title"].split())), c.get("ente"))
    m = re.match(r"(Concorso|Selezione|Avviso|Mobilità|Stabilizzazione|Interpello)(?: a tempo [a-z ]+)?(?=: )", w)
    return (m.group(0) if m else ""), (what.role(w) or what.other_job(" ".join(c["title"].split())) or desc_job(c))


DESC_TAIL = re.compile(r"(?:\s+|-)(?:[PF]\.T\.?|C\.C\.N\.L\.?|liv\b.*|area\b.*|cat\b.*|codice\b.*)$", re.I)


def desc_job(c):
    """The job named in the call's description, for titles that are only a code or an ente ("BANDO CNR N. 367.641 TEC UPE",
    "COMUNE DI NOVE"); "" when unsure. role() only: other_job() on a description finds requirements ("dottorato di ricerca")."""
    desc = " ".join((c.get("desc") or "").split("\n", 1)[-1].split())
    if not desc or desc == " ".join(c["title"].split()) or what.LIST_ONLY.search(c["title"]) or re.search(r"commission", c["title"], re.I):
        return ""  # like role(): a list, a progression or a commission seat is not the job the description names
    m = what.POSTS.search(desc[:1000])  # skip the legal preamble: "Selezione ai sensi dell'art. 8 del ... di una unità ... di ricercatore"
    desc = desc[m.start():] if m and m.start() > 150 else desc
    j = DESC_TAIL.sub("", what.role(what.what(titles.sentence_case(desc[:600]), c.get("ente"))) or "").strip(" -")
    first = j.split(" ")[0].lower() if j else ""
    if not what.STARTS.match(j) or re.search(r"[()]", j) or re.search(r"(?:ia|che)$", first) or len(j) < 4:
        return ""  # "Statistiche assegnate…", "Ingegneria civile…": a subject, not a job
    return j


def write_app_data(outdir, open_, latest):
    """app/v1.json: every open call in a compact form for the Android app, which filters and notifies on the phone.
    Keys are short on purpose (served gzipped); the app knows them. Add keys freely, never change one's meaning."""
    rows = []
    for c in sorted(open_, key=lambda c: (c["lastmod"], posted(c), c["id"]), reverse=True):
        kind, job = app_job(c)
        rows.append({"id": c["id"], "t": short_title(c, 110), "k": kind, "w": job, "tt": " ".join(c["title"].split()),
                     "e": " ".join((c.get("ente") or "").split()), "r": keys_of(c),
                     "p": slug(c["_prov"]) if c["_prov"] else "", "c": c["_comune"] or "",
                     "f": c["_prof"] + c["_studio"] + c["_disc"], "n": c.get("posts") or None,
                     "o": c.get("opens") or "", "s": c["closes"] if valid_closes(c) else "",
                     "m": c["lastmod"], "u": page_rel(c),
                     "x": c.get("gu_url") if is_gu(c) else INPA_PAGE.format(c["id"])})
    data = {"v": 1, "updated": latest, "base": BASE + "/", "rights": RIGHTS,
            "regions": {k: label_of(k) for k in [slug(r) for r in REGIONS] + [NAZ]},
            "profiles": {**profili.LABEL, **studio.LABEL, **{k: f"Medici: {v}" for k, v in discipline.LABEL.items()}},
            "provinces": dict(sorted({slug(c["_prov"]): c["_prov"] for c in open_ if c["_prov"]}.items())), "calls": rows}
    os.makedirs(os.path.join(outdir, "app"), exist_ok=True)
    path = os.path.join(outdir, "app", "v1.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)


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
    tag: data-r with the call's group keys, for the region filter on profession pages (REGION_FILTER),
    and data-d with its medical disciplines (discipline.py), for the discipline filter on medici.html."""
    e = html.escape
    lis = []
    for c in calls:
        meta = [ente_short(c, 60), region_text(c), posts_text(c), "scade " + deadline_short(c) if valid_closes(c) else None]
        data = f' data-r="{" ".join(keys_of(c))}"' if tag else ""
        if tag and c["_disc"]:
            data += f' data-d="{" ".join(c["_disc"])}"'
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
    sc = what.other_job(full) or ""  # of other_job's headlines only the director's is one job
    job = what.role(what.what(titles.sentence_case(full), c.get("ente"))) or (sc if sc.startswith("Direttore") else "") or desc_job(c)
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


# <title> only (lists and feeds keep them): the default contract, and "disciplina di" in front of a medical discipline
TITLE_FILLER = re.compile(r",?\s*[–-]?\s*\ba tempo (?:pieno )?(?:ed? )?indeterminato(?:,? (?:e |ed )?(?:a tempo )?pieno)?\b", re.I)
TITLE_DISCIPLINE = re.compile(r",?\s*[–-]?\s*\b(?:(?:per|nella|della|in) (?:la )?)?disciplina\b:?\s*(?:di\s+|in\s+)?", re.I)
# one post: the count is in the description; plural counts stay
TITLE_ONE_POST = re.compile(r"(?<=: )(?:n\.\s?1|un|uno|una|1)\s+(?:\(uno\)\s+)?posto\s+(?:(?:nel|con) (?:il )?profilo(?: professionale)? )?(?:di|da)\s+", re.I)


def page_title(c, now, note=""):
    """<title>: the job first (Google shows about 60 characters), the ente when there is room, the deadline.
    `note` tells apart calls whose titles would collide."""
    closed = c["_closed"]
    who = ente_brief(c)
    who = who if len(who) <= 34 else ""
    expired = valid_closes(c) and c["closes"] < now.strftime("%Y-%m-%dT%H:%M")
    tail = (f": scadenza {day(c['closes'])}" if valid_closes(c) and not closed else
            f": chiuso il {day(c['closes'])}" if expired else ": non più su inPA" if closed else "")
    note = f" ({note})" if note else ""
    title = TITLE_DISCIPLINE.sub(" di ", TITLE_FILLER.sub("", TITLE_ONE_POST.sub("", short_title(c, 300)))).replace(" di di ", " di ").strip(" ,")
    if who and title.lower().startswith(who.lower()):  # "COMUNE DI X – FUNZIONARIO TECNICO": the ente goes after
        rest = title[len(who):].lstrip(" -–—:,._")
        title, who = (rest[:1].upper() + rest[1:], who) if len(rest) > 12 else (title, "")
    title = titles.cut(title, max(36, 64 - len(note)))
    if len(title) + len(note) + len(who) > 84:  # the ente is in the description and the h1 anyway
        who = ""
    return title + note + (f" - {who}" if who else "") + tail


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


def call_page(c, today, now, region_pages, profile_pages, province_pages, note="", near=(), pair_pages=()):
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
            ("Pubblicato in", is_gu(c) and f"Gazzetta Ufficiale, 4ª serie speciale, {c['gu_issue']}"),
            ("Valutazione", c.get("eval")), ("Apertura candidature", not is_gu(c) and day(c.get("opens")) and f"{day(c['opens'])} alle {c['opens'][11:]}")]
    facts = "\n".join(f"<tr><th>{k}</th><td>{e(v)}</td></tr>" for k, v in rows if v)
    if valid_closes(c):
        when = "" if closed else f" ({countdown(c, today)})"
        at = f"<b>{day(c['closes'])}</b>{when}{GU_REOPEN_NOTE if c.get('gu_type') == 'RIAPERTURA' else GU_DEADLINE_NOTE}" if is_gu(c) else f"<b>{day(c['closes'])} alle {c['closes'][11:]}</b>{when}"
        facts += f"\n<tr><th>Scadenza</th><td>{at}{FAR_NOTE if far_deadline(c) else ""}</td></tr>"
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
    buttons = [f'<a class="btn" href="{e(official_url(c))}">{official_label(c)}</a>']
    if not closed and not is_gu(c):
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
    for p in c["_prof"][:2]:  # the profession×region page when there is one: closer to what the reader searched
        if f"{p}/{keys[0]}" in pair_pages:
            follow.append(f'<a class="pill" href="../profilo/{p}/{keys[0]}.html">{e(PAIR_HEAD[p])} {e(in_region(keys[0]))}</a>')
        elif f"profilo-{p}" in profile_pages:
            follow.append(f'<a class="pill" href="../profilo/{p}.html">{e(profili.LABEL[p])}</a>')
    for s in c["_studio"]:
        if f"{s}/{keys[0]}" in pair_pages:
            follow.append(f'<a class="pill" href="../profilo/{s}/{keys[0]}.html">Concorsi {e(studio.PHRASE[s])} {e(in_region(keys[0]))}</a>')
        elif f"profilo-{s}" in profile_pages:
            follow.append(f'<a class="pill" href="../profilo/{s}.html">Concorsi {e(studio.PHRASE[s])}</a>')
    if c["_prof"]:
        p = c["_prof"][0]
        follow.append(f'<a class="pill" href="../{e(custom(p, keys[0]))}"><span aria-hidden="true">📡</span> Feed: {e(profili.LABEL[p].lower())}, {e(label_of(keys[0]))}</a>')
    follow.append('<a class="pill" href="../">Tutti i concorsi aperti</a>')
    near_html = "".join(f"<h3>{e(h)}</h3>\n{items_html(sel, '../')}\n" for h, sel in near)
    crumb = ([(f"regione/{keys[0]}.html", label_of(keys[0]))] if keys[0] in region_pages else []) + [("", short(short_title(c), 60))]
    body = f"""{layout.crumbs(crumb, 1)}
<h1 class="long">{e(short(full_title, 400))}</h1>
<p class="lead">{e(ente_name(c))}{" · " if c.get("ente") else ""}{e(region_text(c))}{"" if closed or not valid_closes(c) else f" · scadenza <b>{day(c['closes'])}</b>"}</p>
{status}
<div class="cta">{"".join(buttons)}</div>
{'<p class="small">Per accedere a inPA servono SPID, CIE, CNS o eIDAS.</p>' if not closed and not is_gu(c) else ""}
<div class="table"><table class="facts"><tbody>
{facts}
</tbody></table></div>
{description}{attachments}<h2>Altri concorsi</h2>
{near_html}<div class="actions">{"".join(follow)}</div>
<p class="small">Estratto non ufficiale preparato da un agente AI: i dati possono essere in ritardo o sbagliati. {GU_PAGE_NOTE if is_gu(c) else "Fa fede la scheda su inPA, a cui ogni voce rimanda."}</p>"""
    title = page_title(c, now, note)
    meta = [posts_text(c), ente_short(c, 60), region_text(c), "scadenza " + deadline_short(c) if valid_closes(c) else None,
            c.get("eval") and "valutazione: " + c["eval"].lower()]
    desc = short(", ".join(m for m in meta if m) + ".", 200)
    extra = ""
    if closed:
        extra = '\n<meta name="robots" content="noindex">'
    elif valid_closes(c) and not is_gu(c):  # a GU summary is too thin for a JobPosting
        extra = job_posting(c, url)
    return layout.page(title, desc, body, "", 1, extra, "", *source_of(c), url)


NEAR_MAX = 6  # open calls listed on each call page, for visitors who arrive from a search for work in one town


def near_index(open_):
    """{("p", province) | ("s", city) | ("r", group key): open calls} for nearby(); open_ comes sorted by deadline."""
    idx = {}
    for c in open_:
        if c["_prov"]:
            idx.setdefault(("p", c["_prov"]), []).append(c)
        for city in {c["_comune"], c["_seat"]} - {None}:
            idx.setdefault(("s", city), []).append(c)
        for k in keys_of(c)[:1]:
            idx.setdefault(("r", k), []).append(c)
    for k, v in idx.items():
        if k[0] == "r":  # a whole region: the newest calls, not the hundreds closing first
            v.sort(key=lambda c: (c.get("opens") or "", c["id"]), reverse=True)
    return idx


def nearby(c, idx):
    """[(heading, calls)] of other open calls near c: in its city (an ente named after it) or, for a local
    authority, its province; then the newest in its region, up to NEAR_MAX in all. Each list says what it is."""
    out, seen = [], {c["id"]}
    def take(key, heading):
        sel = [o for o in idx.get(key, []) if o["id"] not in seen][:NEAR_MAX - len(seen) + 1]
        seen.update(o["id"] for o in sel)
        if sel:
            out.append((heading, sel))
    city = c["_comune"] or c["_seat"]
    if city:
        take(("s", city), f"Concorsi aperti a {city}")
    if c["_prov"]:
        take(("p", c["_prov"]), f"Concorsi aperti di enti locali in provincia di {c['_prov']}")
    k = keys_of(c)[0]
    take(("r", k), f"I più recenti in {label_of(k)}" if k != NAZ else f"I più recenti: {label_of(k)}")
    return out


def write_call_pages(outdir, kept, open_, today, now, region_pages, profile_pages, province_pages, pair_pages=()):
    """One page per call, in 16 gzipped JSON shards served by concorso/page.php (the hosting caps the file
    count, like bandi/avviso). Returns (rel, lastmod) of the indexable pages."""
    shards, indexable = {}, []
    idx = near_index(open_)
    for c in kept:
        shards.setdefault(c["id"][0], {})[c["id"]] = call_page(c, today, now, region_pages, profile_pages, province_pages, c.get("_note", ""), nearby(c, idx), pair_pages)
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


def write_region_pages(outdir, sets, vsets, when, pair_keys=()):
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
        if any(profs.values()):  # links to the profession×region page, or to the profession page filtered on this region (REGION_FILTER)
            note += ('<p class="small">Per professione: '
                     + " · ".join(f'<a href="{pair_link(p, key, pair_keys, "../")}">{e(profili.LABEL[p])}</a> {n}' for p, n in profs.items() if n) + ".</p>\n")
        levels = {s: sum(s in c["_studio"] for c in sel) for s in studio.LABEL}
        if any(levels.values()):
            note += ('<p class="small">Per titolo di studio: '
                     + " · ".join(f'<a href="{pair_link(s, key, pair_keys, "../")}">{e(studio.LABEL[s])}</a> {n}' for s, n in levels.items() if n) + ".</p>\n")
        where = "Concorsi pubblici nazionali e di altre aree" if key == NAZ else f"Concorsi pubblici {in_region(key)}"
        body = f"""{layout.crumbs([("", label)], 1)}
<h1>{e(where)}</h1>
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} {SU}, dalla scadenza più vicina. Aggiornato il {when}.</p>
{note}<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../nuovi.html#{key}">Nuovi della settimana</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html">Come si usano?</a></div>
{items_html(sel, "../")}"""
        emit_page(outdir, f"regione/{key}.html", f"{where}: {plural(len(sel), 'aperto', 'aperti')}",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} {SU}: {label}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
        written.append(key)
    return written


# profilo/<name>.html#<region>: only that region's calls, with the custom feed and calendar for the pair.
# Without JavaScript the link just shows every region.
REGION_FILTER = """<script>(function () {
  var box = document.getElementById("solo"), names = JSON.parse(box.dataset.names), disc = JSON.parse(box.dataset.disc || "{}"),
      rows = document.querySelectorAll(".items li"), live = document.createElement("p");
  live.className = "sr-only"; live.setAttribute("role", "status"); box.parentNode.insertBefore(live, box);
  function show(e) {
    var r = decodeURIComponent(location.hash.slice(1)), n = 0, d = disc.hasOwnProperty(r);
    if (!d && !names.hasOwnProperty(r)) r = "";
    rows.forEach(function (li) { var ok = !r || ((d ? li.dataset.d : li.dataset.r) || "").split(" ").indexOf(r) >= 0; li.style.display = ok ? "" : "none"; if (ok) n++; });
    var sel = document.getElementById("disc");
    if (sel) sel.value = d ? r : "";
    box.hidden = !r;
    if (e) live.textContent = (r ? (d ? disc[r] : names[r]) + ": " : "Tutti: ") + n + (n == 1 ? " concorso aperto" : " concorsi aperti");
    if (!r) return;
    box.querySelector("b").textContent = d ? disc[r] : names[r];
    box.querySelector("span").textContent = n + (n == 1 ? " concorso aperto" : " concorsi aperti");
    var q = "../feed/su-misura.php?f=" + (d ? r : box.dataset.f + "&r=" + r);
    box.querySelector(".feed").href = q;
    box.querySelector(".cal").href = q + "&formato=ics";
  }
  window.addEventListener("hashchange", show);
  show();
})();</script>"""


# nuovi.html#<region>: only that region's new calls; day headings with nothing left are hidden.
NEW_FILTER = """<script>(function () {
  var box = document.getElementById("solo"), names = JSON.parse(box.dataset.names), days = document.querySelectorAll(".day"),
      live = document.createElement("p");
  live.className = "sr-only"; live.setAttribute("role", "status"); box.parentNode.insertBefore(live, box);
  function show(e) {
    var r = decodeURIComponent(location.hash.slice(1)), n = 0;
    if (!names.hasOwnProperty(r)) r = "";
    days.forEach(function (d) {
      var k = 0;
      d.querySelectorAll(".items li").forEach(function (li) { var ok = !r || li.dataset.r.split(" ").indexOf(r) >= 0; li.style.display = ok ? "" : "none"; if (ok) k++; });
      d.hidden = !k; n += k;
      d.querySelector("h2 small").textContent = "(" + k + ")";
    });
    box.hidden = !r;
    if (e) live.textContent = (r ? names[r] + ": " : "Tutte le regioni: ") + n + (n == 1 ? " concorso nuovo" : " concorsi nuovi");
    if (!r) return;
    box.querySelector("b").textContent = names[r];
    box.querySelector("span").textContent = n + (n == 1 ? " concorso nuovo" : " concorsi nuovi");
    box.querySelector(".all").href = "regione/" + r + ".html";
    box.querySelector(".feed").href = "feed/" + r + ".xml";
  }
  window.addEventListener("hashchange", show);
  show();
})();</script>"""
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
NEW_DAYS = 7


def write_new_page(outdir, open_, when, today):
    """nuovi.html: open calls whose applications opened in the last NEW_DAYS days, newest day first."""
    e = html.escape
    first = (today - dt.timedelta(days=NEW_DAYS - 1)).isoformat()
    sel = [c for c in open_ if first <= posted(c)[:10] <= today.isoformat()]
    by_day = {}
    for c in sorted(sel, key=lambda c: (posted(c), c["id"]), reverse=True):
        by_day.setdefault(posted(c)[:10], []).append(c)
    by_region = {}
    for c in sel:
        for k in keys_of(c):
            by_region[k] = by_region.get(k, 0) + 1
    order = [slug(r) for r in REGIONS] + [NAZ]
    spread = " · ".join(f'<a href="#{k}">{e(label_of(k))}</a> {by_region[k]}' for k in order if k in by_region)
    names = html.escape(json.dumps({k: label_of(k) for k in by_region}, ensure_ascii=False))
    sections = []
    for d, cs in by_day.items():
        dd = dt.date.fromisoformat(d)
        name = "Oggi" if dd == today else "Ieri" if dd == today - dt.timedelta(days=1) else WEEKDAYS[dd.weekday()].capitalize()
        sections.append(f'<section class="day">\n<h2>{name}, {dd.day} {MONTHS[dd.month - 1]} <small>({len(cs)})</small></h2>\n{items_html(cs, tag=True)}\n</section>')
    body = f"""{layout.crumbs([("", "Nuovi")], 0)}
<h1>Concorsi pubblici nuovi, ultimi {NEW_DAYS} giorni</h1>
<p class="lead">{plural(len(sel), "concorso", "concorsi")} {SU} aperti negli ultimi {NEW_DAYS} giorni e non ancora scaduti, dal più recente. Aggiornato il {when}.</p>
<p class="small">Per regione: {spread}.</p>
<p id="solo" class="lead" hidden data-names="{names}">Solo <b></b>: <span></span>.
<a href="#">Tutte le regioni</a> · <a class="all" href="index.html">tutti i concorsi aperti</a> · <a class="feed" href="feed.html">feed</a> della regione.</p>
<p class="small">Conta il giorno di apertura delle candidature indicato da inPA{" o, per la Gazzetta Ufficiale, il giorno di uscita del numero" if GU_ON else ""}. I concorsi di un giorno arrivano qui di solito la notte successiva, quando inPA aggiorna il suo elenco, quindi «Oggi» è spesso quasi vuoto. Per non controllare a mano, usa il <a href="feed.html">feed</a> della tua regione: ti porta solo i nuovi.</p>
{"".join(sections) or "<p>Nessun concorso nuovo negli ultimi giorni.</p>"}
{NEW_FILTER}"""
    emit_page(outdir, "nuovi.html", f"Concorsi pubblici nuovi, ultimi {NEW_DAYS} giorni ({len(sel)})",
              f"{plural(len(sel), 'concorso pubblico', 'concorsi pubblici')} {SU} con candidature aperte negli ultimi {NEW_DAYS} giorni, giorno per giorno e per regione.",
              body, "./", 0, '\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · Tutta Italia" href="feed/italia.xml">')


LEVEL_NOTE = "inPA non indica il titolo di studio richiesto: lo stimo dal livello del contratto nel titolo o nella descrizione (per esempio «Area degli Istruttori» o «categoria C» = diploma), quindi qualche concorso può mancare o essere fuori posto. I requisiti veri sono nel bando: controllali sempre."


def write_profile_pages(outdir, psets, when, pair_keys=()):
    """profilo/<slug>.html for every profession with at least one open call. Returns the keys written."""
    e = html.escape
    os.makedirs(os.path.join(outdir, "profilo"), exist_ok=True)
    written = []
    for key, (label, sel) in psets.items():
        if not sel:
            continue
        name = key[len("profilo-"):]
        level = name in studio.LABEL
        head = f"{PAIR_HEAD[name]} in tutta Italia"
        also = ' Chi ha il diploma può partecipare anche ai concorsi <a href="scuola-obbligo.html">con la scuola dell\'obbligo</a>.' if name == "diplomati" else ""
        note = (f'{LEVEL_NOTE}{also} <a href="../info.html#titolo-di-studio">Come lo stimo</a>.'
                if level else 'inPA non indica la professione: la riconosco dalle parole del titolo, quindi qualche concorso può mancare o essere fuori posto. Per non perderne, segui anche la tua regione. <a href="../info.html#professioni">Come la riconosco</a>.')
        by_region = {}
        for c in sel:
            for k in keys_of(c):
                by_region[k] = by_region.get(k, 0) + 1
        spread = " · ".join(f'<a href="{f"{name}/{k}.html" if f"{name}/{k}" in pair_keys else "#" + k}">{e(label_of(k))}</a> {n}'
                            for k, n in sorted(by_region.items(), key=lambda x: (-x[1], x[0])))
        names = html.escape(json.dumps({k: label_of(k) for k in by_region}, ensure_ascii=False))
        by_disc, disc_line, disc_attr = {}, "", ""
        if name == "medici":
            for c in sel:
                for d in c["_disc"]:
                    by_disc[d] = by_disc.get(d, 0) + 1
            untagged = sum(not c["_disc"] for c in sel)
            opts = "".join(f'<option value="{d}">{e(discipline.LABEL[d])} ({n})</option>' for d, n in sorted(by_disc.items(), key=lambda x: discipline.LABEL[x[0]]))
            disc_line = (f'<p class="small" id="discipline"><label for="disc">Per disciplina:</label> <select id="disc" onchange="location.hash = this.value">'
                         f'<option value="">tutte ({len(sel)})</option>{opts}</select> '
                         f'Senza una disciplina riconoscibile nel titolo (direzioni di dipartimento o distretto, elenchi per più discipline…): {untagged}, solo nell\'elenco completo. '
                         '<a href="../info.html#discipline">Come la riconosco</a>.</p>\n')
            disc_attr = f' data-disc="{html.escape(json.dumps({d: discipline.LABEL[d] for d in by_disc}, ensure_ascii=False))}"'
        body = f"""{layout.crumbs([("", label)], 1)}
<h1>{e(head)}</h1>
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} {SU}, dalla scadenza più vicina. Aggiornato il {when}.</p>
<p class="small">Per regione: {spread}.</p>
{disc_line}<p id="solo" class="lead" hidden data-f="{name}" data-names="{names}"{disc_attr}>Solo <b></b>: <span></span>.
<a href="#">Mostra tutti</a> · <a class="feed" href="../feed.html">feed</a> · <a class="cal" href="../feed.html">calendario</a> di questa selezione.</p>
<p class="small">{note}</p>
<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../feed.html#su-misura">Solo nella tua regione</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html#professione">Come si usano?</a></div>
{items_html(sel, "../", tag=True)}
{REGION_FILTER}"""
        emit_page(outdir, f"profilo/{name}.html", f"{PAIR_HEAD[name]}: {plural(len(sel), 'aperto', 'aperti')} in tutta Italia",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} {SU} {studio.PHRASE[name] if level else 'per ' + label.lower()}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
        written.append(key)
    return written


# profilo/<name>/<region>.html: the same list as profilo/<name>.html#<region>, as a page of its own that search engines
# can index (people search "concorsi infermieri campania", "concorsi per diplomati palermo"). Only with PAIR_MIN open calls.
PAIR_MIN = 3
PAIR_HEAD = {"amministrativi": "Concorsi per amministrativi e contabili", "tecnici": "Concorsi per tecnici, ingegneri, architetti e geometri",
             "polizia-locale": "Concorsi di polizia locale", "forze-ordine": "Concorsi per forze dell'ordine, militari e vigili del fuoco",
             "medici": "Concorsi per medici", "infermieri": "Concorsi per infermieri", "sanitari": "Concorsi per professioni sanitarie e OSS",
             "insegnanti-educatori": "Concorsi per insegnanti, docenti ed educatori", "assistenti-sociali": "Concorsi per assistenti sociali",
             "informatici": "Concorsi per informatici", "ricerca": "Posti, assegni e borse di ricerca",
             "operai-autisti": "Concorsi per operai, autisti e manutentori", "dirigenti": "Concorsi per dirigenti e segretari comunali",
             "cultura": "Concorsi in biblioteche, archivi e musei", "incarichi-esterni": "Incarichi esterni, consulenze e OIV",
             "avvocati": "Concorsi per avvocati", **{s: f"Concorsi {studio.PHRASE[s]}" for s in studio.LABEL}}


IN_REGION = {"lazio": "nel Lazio", "marche": "nelle Marche"}  # "in" for the others


def in_region(key):
    return IN_REGION.get(key, f"in {label_of(key)}")


def pair_link(name, key, pair_pages, prefix):
    """The profession×region page if it exists, otherwise the profession page filtered by hash."""
    return f"{prefix}profilo/{name}/{key}.html" if f"{name}/{key}" in pair_pages else f"{prefix}profilo/{name}.html#{key}"


def write_pair_pages(outdir, psets, when):
    """profilo/<name>/<region>.html for every profession or education level with PAIR_MIN open calls in a region
    (not the national group: nobody searches for it by place). Returns the "<name>/<region>" keys written."""
    e = html.escape
    written = []
    for key, (label, sel) in psets.items():
        name = key[len("profilo-"):]
        level = name in studio.LABEL
        for r in [slug(x) for x in REGIONS]:
            rsel = [c for c in sel if r in keys_of(c)]
            if len(rsel) < PAIR_MIN:
                continue
            rlab = label_of(r)
            head = f"{PAIR_HEAD[name]} {in_region(r)}"
            note = (f'{LEVEL_NOTE} <a href="../../info.html#titolo-di-studio">Come lo stimo</a>.' if level else
                    'inPA non indica la professione: la riconosco dalle parole del titolo, quindi qualche concorso può mancare o essere fuori posto. '
                    f'Per non perderne, guarda anche <a href="../../regione/{r}.html">tutti i concorsi {e(in_region(r))}</a>. <a href="../../info.html#professioni">Come la riconosco</a>.')
            q = custom(name, r)
            os.makedirs(os.path.join(outdir, "profilo", name), exist_ok=True)
            body = f"""{layout.crumbs([(f"profilo/{name}.html", label), ("", rlab)], 2)}
<h1>{e(head)}</h1>
<p class="lead">{plural(len(rsel), "concorso aperto", "concorsi aperti")} {SU}, dalla scadenza più vicina. Aggiornato il {when}.</p>
<p class="small">{note}</p>
<div class="actions"><a class="pill" href="../../{e(custom(name, r, cal=True))}"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../../{e(q)}"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../{name}.html">{e(label)}: tutta Italia</a><a class="pill" href="../../regione/{r}.html">Tutti i concorsi: {e(rlab)}</a><a class="pill" href="../../feed.html#email">Avvisi per email</a></div>
{items_html(rsel, "../../")}"""
            emit_page(outdir, f"profilo/{name}/{r}.html", f"{head}: {plural(len(rsel), 'aperto', 'aperti')}",
                      f"{plural(len(rsel), 'concorso aperto', 'concorsi aperti')} {SU} {studio.PHRASE[name] if level else 'per ' + label.lower()} {in_region(r)}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                      body, "./", 2, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)} · {e(rlab)}" href="../../{e(q)}">')
            written.append(f"{name}/{r}")
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
<p class="lead">{plural(len(sel), "concorso aperto", "concorsi aperti")} {SU} di Comuni, Provincia o Città metropolitana, dalla scadenza più vicina. Aggiornato il {when}.</p>
<p class="small">Qui ci sono solo gli enti locali, di cui conosco la sede dal nome. Aziende sanitarie, ospedali, università e altri enti della zona sono nella pagina <a href="../regione/{rk}.html">{e(label_of(rk))}</a>. <a href="../info.html#province">Come funziona</a>.</p>
{f'<p class="small">Comuni: {e(", ".join(comuni))}.</p>' if comuni else ""}
<div class="actions"><a class="pill" href="../calendario/{key}.ics"><span aria-hidden="true">📅</span> Calendario delle scadenze</a>
<a class="pill" href="../feed/{key}.xml"><span aria-hidden="true">📡</span> Feed</a><a class="pill" href="../feed.html#email">Avvisi per email</a><a class="pill" href="../feed.html#provincia">Come si usano?</a></div>
{items_html(sel, "../")}"""
        emit_page(outdir, f"provincia/{key[5:]}.html", f"Concorsi Comuni in provincia di {name}: {len(sel)} aperti",
                  f"{plural(len(sel), 'concorso aperto', 'concorsi aperti')} {SU} di Comuni ed enti locali in provincia di {name}. Scadenze, feed e calendario, nuovi bandi ogni giorno.",
                  body, "./", 1, f'\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · {e(label)}" href="../feed/{key}.xml">')
    return list(vsets)


FIELDS = [  # (column, description) for dati/concorsi-aperti.csv, documented on dati.html
    ("id", "Identificativo del concorso su inPA"),
    ("titolo", "Titolo come su inPA (spazi normalizzati, eventuali nomi di persone sostituiti da «[nome omesso]»)"),
    ("ente", "Amministrazione che bandisce"),
    ("area_inpa", "Area geografica come la indica inPA"),
    ("regioni", "Regioni ricavate dall'area geografica, separate da «|»; «Nazionale e altre aree» se nessuna"),
    ("provincia", "Provincia, solo per Comuni, Province e Città metropolitane (dal nome dell'ente e dall'elenco ISTAT)"),
    ("comune", "Comune, solo per gli enti locali di cui sopra"),
    ("professioni", "Professioni dedotte da parole chiave nel titolo, separate da «|»: una stima, non un dato di inPA"),
    ("titolo_studio_stimato", "Titolo di studio minimo stimato dal livello del contratto (Laureati, Diplomati, Scuola dell'obbligo), separati da «|»: una stima, non un dato di inPA; vuoto se non riconosciuto"),
    ("posti", "Numero di posti, se indicato (i segnaposto come 999 o 9999 sono lasciati vuoti)"),
    ("valutazione", "Tipo di valutazione (per esami, per titoli…)"),
    ("apertura", "Apertura delle candidature, ora di Roma (AAAA-MM-GGTHH:MM)"),
    ("scadenza", "Scadenza delle candidature, ora di Roma (AAAA-MM-GGTHH:MM)"),
    ("retribuzione_min", "Retribuzione annua lorda minima in euro, se indicata"),
    ("retribuzione_max", "Retribuzione annua lorda massima in euro, se indicata"),
    ("aggiornato_inpa", "Data di ultima modifica nella sitemap di inPA (UTC)"),
    ("url_inpa", "Scheda ufficiale su inPA: fa fede questa"),
    ("url_pagina", "Pagina del concorso su ossian.cloud"),
    ("sito_ente", "Sito dell'amministrazione, come indicato su inPA"),
    ("discipline_mediche", "Solo per i medici: discipline dedotte dal titolo (nomi del D.M. 30 gennaio 1998), separate da «|»: una stima, non un dato di inPA; vuoto se non riconosciuta"),
]


GU_FIELDS = [  # (column, description) for dati/concorsi-gazzetta.csv: calls only in the Gazzetta Ufficiale
    ("id", "Identificativo interno (stabile da un aggiornamento all'altro)"),
    ("codice_gu", "Codice redazionale dell'avviso nella Gazzetta Ufficiale (per esempio 26E05030)"),
    ("tipo", "Tipo di avviso secondo la Gazzetta: CONCORSO, MOBILITA', oppure RIAPERTURA se riapre i termini di un concorso"),
    ("titolo", "Titolo del sommario della Gazzetta (spazi normalizzati, eventuali nomi di persone sostituiti da «[nome omesso]»)"),
    ("ente", "Amministrazione che bandisce, come nella Gazzetta"),
    ("sezione_gu", "Sezione del sommario (per esempio ENTI DI RICERCA, AZIENDE SANITARIE LOCALI ED ALTRE ISTITUZIONI SANITARIE)"),
    ("regioni", "Regioni ricavate dall'ente, separate da «|»; «Nazionale e altre aree» se nessuna"),
    ("provincia", "Provincia, solo per Comuni, Province e Città metropolitane"),
    ("comune", "Comune, solo per gli enti locali di cui sopra"),
    ("professioni", "Professioni dedotte da parole chiave nel titolo, separate da «|»: una stima"),
    ("titolo_studio_stimato", "Titolo di studio minimo stimato, separati da «|»: una stima; vuoto se non riconosciuto"),
    ("posti", "Numero di posti, se il sommario lo indica"),
    ("pubblicazione", "Data del numero della Gazzetta (AAAA-MM-GG)"),
    ("scadenza", "Scadenza indicata dalla redazione della Gazzetta (AAAA-MM-GG): quella ufficiale, con l'ora, è nel bando"),
    ("numero_gu", "Numero della 4ª serie speciale (per esempio «n. 72 del 18/09/2026»)"),
    ("url_gu", "Avviso nella Gazzetta Ufficiale: fa fede questo"),
    ("url_pagina", "Pagina del concorso su ossian.cloud"),
    ("discipline_mediche", "Solo per i medici: discipline dedotte dal titolo, separate da «|»: una stima"),
]

# Changes to the CSV columns, newest first, shown on dati.html. Rule: never rename or remove a column; add new ones at the end.
CSV_CHANGES = [
    ("2026-10-25", "<code>datapackage.json</code>: <code>apertura</code>, <code>scadenza</code> e <code>aggiornato_inpa</code> hanno ora il tipo data e ora (le prime due ora di Roma, formato <code>%Y-%m-%dT%H:%M</code>). Nessuna colonna cambiata."),
    ("2026-10-24", "Tolte circa 110 righe che non erano bandi ma avvisi su procedure già in corso (approvazione di graduatorie, calendari e convocazioni delle prove, quasi tutte degli Uffici Scolastici Regionali). Le colonne non cambiano."),
    ("2026-10-21", "Nuovo file <code>concorsi-gazzetta.csv</code> con i concorsi che sono solo nella Gazzetta Ufficiale. <code>concorsi-aperti.csv</code> non cambia."),
    ("2026-10-17", "Aggiunta in fondo la colonna <code>discipline_mediche</code>."),
    ("2026-10-15", "Aggiunta la colonna <code>titolo_studio_stimato</code>, dopo <code>professioni</code> (l'unica volta che una colonna è stata inserita in mezzo: non succederà più)."),
    ("2026-10-14", "Prima pubblicazione."),
]


# Frictionless types for dati/datapackage.json; any column not listed is a string.
# A (type, format) pair sets a format; apertura/scadenza are Rome time with no offset.
FIELD_TYPES = {"posti": "integer", "retribuzione_min": "number", "retribuzione_max": "number",
               "apertura": ("datetime", "%Y-%m-%dT%H:%M"), "scadenza": ("datetime", "%Y-%m-%dT%H:%M"),
               "aggiornato_inpa": "datetime"}
GU_FIELD_TYPES = {"posti": "integer", "pubblicazione": "date", "scadenza": "date"}
RESOURCES = {  # name -> (title, licence, source)
    "concorsi-aperti.csv": ("Concorsi aperti su inPA",
                            {"name": "CC-BY-3.0-IT", "path": "https://creativecommons.org/licenses/by/3.0/it/", "title": "CC BY 3.0 IT"},
                            {"title": "inPA, Portale del reclutamento (Dipartimento della Funzione Pubblica)", "path": "https://www.inpa.gov.it/"}),
    "concorsi-gazzetta.csv": ("Concorsi aperti solo nella Gazzetta Ufficiale, 4ª serie speciale", None,
                              {"title": "Gazzetta Ufficiale della Repubblica Italiana, 4ª serie speciale (testo non autentico, riprodotto gratuitamente)",
                               "path": "https://www.gazzettaufficiale.it/"}),
}


def field_schema(name, t, description):
    t, fmt = t if isinstance(t, tuple) else (t, None)
    return {"name": name, "type": t, **({"format": fmt} if fmt else {}), "description": description}


def write_datapackage(outdir, files, latest):
    """dati/datapackage.json: a Frictionless Data Package describing the CSVs, so tools can read them with types."""
    resources = []
    for name, fields_ in files:
        title, licence, source = RESOURCES[name]
        types = GU_FIELD_TYPES if name == "concorsi-gazzetta.csv" else FIELD_TYPES
        r = {"name": name[:-4], "path": f"{BASE}/dati/{name}", "title": title, "format": "csv", "mediatype": "text/csv",
             "encoding": "utf-8", "sources": [source],
             "schema": {"fields": [field_schema(k, types.get(k, "string"), d) for k, d in fields_],
                        "missingValues": [""]}}
        if licence:
            r["licenses"] = [licence]
        resources.append(r)
    pkg = {"name": "ossian-concorsi", "title": "Concorsi pubblici aperti (inPA e Gazzetta Ufficiale)",
           "description": "Estratto non ufficiale, aggiornato ogni 4 ore: fanno fede inPA e la Gazzetta Ufficiale. Campi e limiti: " + f"{BASE}/dati.html",
           "homepage": f"{BASE}/dati.html", "version": CSV_CHANGES[0][0], "created": latest,
           "contributors": [{"title": "Ossian (agente AI)", "path": "https://ossian.cloud/", "role": "author"}],
           "resources": resources}
    path = os.path.join(outdir, "dati", "datapackage.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def gu_dataset_row(c):
    return {"id": c["id"], "codice_gu": c.get("gu_code") or "", "tipo": c.get("gu_type") or "",
            "titolo": " ".join(c["title"].split()), "ente": " ".join((c.get("ente") or "").split()),
            "sezione_gu": c.get("section") or "", "regioni": "|".join(label_of(k) for k in keys_of(c)),
            "provincia": c["_prov"] or "", "comune": c["_comune"] or "",
            "professioni": "|".join(profili.LABEL[p] for p in c["_prof"]),
            "titolo_studio_stimato": "|".join(studio.LABEL[s] for s in c["_studio"]), "posti": c.get("posts") or "",
            "pubblicazione": (c.get("opens") or "")[:10], "scadenza": c["closes"][:10] if valid_closes(c) else "",
            "numero_gu": c.get("gu_issue") or "", "url_gu": c.get("gu_url") or "",
            "url_pagina": f"{BASE}/{page_rel(c)}",
            "discipline_mediche": "|".join(discipline.LABEL[d] for d in c["_disc"])}


def num(v):
    return "" if v is None else str(int(v)) if v == int(v) else str(v)


def dataset_row(c):
    keys = keys_of(c)
    return {"id": c["id"], "titolo": " ".join(c["title"].split()), "ente": " ".join((c.get("ente") or "").split()),
            "area_inpa": c.get("region") or "", "regioni": "|".join(label_of(k) for k in keys),
            "provincia": c["_prov"] or "", "comune": c["_comune"] or "",
            "professioni": "|".join(profili.LABEL[p] for p in c["_prof"]),
            "discipline_mediche": "|".join(discipline.LABEL[d] for d in c["_disc"]),
            "titolo_studio_stimato": "|".join(studio.LABEL[s] for s in c["_studio"]), "posti": c.get("posts") or "",
            "valutazione": c.get("eval") or "", "apertura": c.get("opens") or "",
            "scadenza": c["closes"] if valid_closes(c) else "",
            "retribuzione_min": num(c.get("pay_min")), "retribuzione_max": num(c.get("pay_max")),
            "aggiornato_inpa": c["lastmod"], "url_inpa": INPA_PAGE.format(c["id"]),
            "url_pagina": f"{BASE}/{page_rel(c)}", "sito_ente": c.get("pa_url") or ""}


def write_dataset(outdir, open_, latest, when):
    """dati/concorsi-aperti.csv: every open call, one row each, with the derived fields; dati.html says what's in them.
    inPA has no open dataset of its calls: this is the closest thing, under its CC BY 3.0 licence."""
    by_close = lambda c: (c["closes"] if valid_closes(c) else "9999", c["id"])
    rows = [dataset_row(c) for c in sorted((c for c in open_ if not is_gu(c)), key=by_close)]
    gu_rows = [gu_dataset_row(c) for c in sorted((c for c in open_ if is_gu(c)), key=by_close)]
    os.makedirs(os.path.join(outdir, "dati"), exist_ok=True)
    files = [("concorsi-aperti.csv", FIELDS, rows)] + ([("concorsi-gazzetta.csv", GU_FIELDS, gu_rows)] if GU_ON else [])
    sizes = {}
    for name, fields_, rows_ in files:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=[k for k, _ in fields_])
        w.writeheader()
        w.writerows(rows_)
        text = buf.getvalue()
        path = os.path.join(outdir, "dati", name)
        with open(path + ".tmp", "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
        sizes[name] = os.path.getsize(path)
    write_datapackage(outdir, [(name, fields_) for name, fields_, _ in files], latest)
    e = html.escape
    fields = "\n".join(f"<tr><td><code>{k}</code></td><td>{e(d)}</td></tr>" for k, d in FIELDS)
    gu_fields = "\n".join(f"<tr><td><code>{k}</code></td><td>{e(d)}</td></tr>" for k, d in GU_FIELDS)
    changes = "\n".join(f"<li>{day_} · {t}</li>" for day_, t in CSV_CHANGES)
    gu_section = f"""
<h2 id="gazzetta">I concorsi della Gazzetta Ufficiale, in un secondo file</h2>
<p>Molti concorsi, soprattutto di aziende sanitarie e università, sono pubblicati nella Gazzetta Ufficiale (4ª serie speciale) e non su inPA: {len(gu_rows)} di quelli aperti ora (<a href="gazzetta-e-inpa.html">i numeri</a>).
Sono in un file a parte, perché ne so meno: solo il sommario della Gazzetta, con una scadenza indicata dalla redazione e senza ora.</p>
<div class="actions"><a class="pill" href="dati/concorsi-gazzetta.csv" download><span aria-hidden="true">⬇</span> CSV Gazzetta Ufficiale ({sizes["concorsi-gazzetta.csv"] // 1024} kB)</a></div>
<p class="small">Indirizzo fisso: <code>{BASE}/dati/concorsi-gazzetta.csv</code>. Stesso formato dell'altro file (virgola, UTF-8, intestazione), con colonne in parte diverse. Fonte: Gazzetta Ufficiale della Repubblica Italiana; il testo <b>non è autentico</b> (fa fede solo la Gazzetta) ed è riprodotto <b>gratuitamente</b>, come chiedono le sue condizioni d'uso.
I concorsi che sono anche su inPA stanno solo nel primo file (il confronto è automatico: qualche doppione può sfuggire).</p>
<div class="table"><table><thead><tr><th>Campo</th><th>Cosa contiene</th></tr></thead><tbody>
{gu_fields}
</tbody></table></div>
""" if GU_ON else ""
    body = f"""{layout.crumbs([("", "Dati aperti")])}
<div class="prose">
<h1>I concorsi aperti su inPA, in un file</h1>
<p class="lead">inPA, il portale del reclutamento della pubblica amministrazione, non pubblica i suoi bandi come dati aperti (almeno, non ne ho trovati: né sul portale né su dati.gov.it). Qui ci sono tutti i concorsi aperti
che leggo su inPA ({len(rows)} ora), in un unico file CSV, rigenerato ogni 4 ore: per un'analisi, un articolo, un foglio di calcolo o un programma.</p>
<div class="actions"><a class="pill" href="dati/concorsi-aperti.csv" download><span aria-hidden="true">⬇</span> CSV ({sizes["concorsi-aperti.csv"] // 1024} kB)</a>
</div>
<p class="small">Aggiornato il {when}. Indirizzo fisso, da usare anche in un programma: <code>{BASE}/dati/concorsi-aperti.csv</code>.</p>

<h2>Licenza e citazione</h2>
<p>I contenuti vengono da inPA, Portale del reclutamento (Dipartimento della Funzione Pubblica), in licenza <a href="https://creativecommons.org/licenses/by/3.0/it/">CC BY 3.0</a>, e restano sotto la stessa licenza.
Se li riusi cita inPA come fonte; se ti va, anche questa pagina. È un <strong>estratto non ufficiale: fa fede inPA</strong>.</p>

<h2>I campi</h2>
<p>Una riga per concorso aperto, ordinate per scadenza. Nel CSV: separatore virgola, codifica UTF-8, intestazione nella prima riga; un campo vuoto vuol dire che inPA non dà l'informazione o che non sono riuscito a ricavarla.</p>
<div class="table"><table><thead><tr><th>Campo</th><th>Cosa contiene</th></tr></thead><tbody>
{fields}
</tbody></table></div>
{gu_section}
<h2 id="modifiche">Se lo usi in un programma</h2>
<p>Gli indirizzi dei file non cambiano. Le colonne non vengono rinominate né tolte; quelle nuove si aggiungono in fondo. Conviene comunque leggere le colonne per nome, dall'intestazione.
Nomi, tipi e descrizioni delle colonne sono anche in <a href="dati/datapackage.json"><code>datapackage.json</code></a> (formato <a href="https://datapackage.org/">Frictionless Data Package</a>).
Ogni modifica è annotata qui sotto, con la data. Per domande o se ti serve un campo in più: <a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a>.</p>
<ul class="small">
{changes}
</ul>

<h2>Come aprirlo</h2>
<p>Excel: <b>Dati → Da testo/CSV</b>, scegli il file e la codifica UTF-8 (se lo apri con un doppio clic, con le impostazioni italiane le colonne non si separano).
LibreOffice Calc: apri il file e scegli «Virgola» come separatore. Se ti serve in un altro formato, <a href="mailto:ossian@ossian.cloud">scrivimi</a>.</p>

<h2>Limiti</h2>
<ul>
<li>Ci sono solo i concorsi aperti, cioè con la scadenza non ancora passata, presenti su inPA. Non tutte le amministrazioni pubblicano tutto su inPA.</li>
<li>Regioni, provincia, comune, professioni e titolo di studio sono ricavati da me, con regole spiegate in <a href="info.html">Info</a> e nel <a href="https://github.com/ossian-cloud/concorsi-feed">codice</a>: possono sbagliare. Gli altri campi sono quelli di inPA, che possono contenere errori o arrivare in ritardo.</li>
<li>Le descrizioni e i documenti allegati non ci sono: sono sulla scheda ufficiale, a cui rimanda <code>url_inpa</code>.</li>
<li>Non ci sono dati di persone: nei titoli i nomi sono sostituiti da «[nome omesso]». Se trovi un dato personale, scrivi a <a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a> e lo tolgo.</li>
</ul>
</div>"""
    emit_page(outdir, "dati.html", "Concorsi pubblici aperti (inPA) in CSV: dati aperti · ossian.cloud",
              f"Tutti i {len(rows)} concorsi pubblici aperti su inPA in un file CSV, aggiornato ogni 4 ore, con regione, provincia e professione. Licenza CC BY 3.0.",
              body, "dati.html", extra_head=dataset_ld(len(rows), latest))


def dataset_ld(n, latest):
    """schema.org Dataset, so Google Dataset Search can list the CSV."""
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": "Concorsi pubblici aperti su inPA",
          "description": f"Tutti i concorsi, le selezioni e gli avvisi di mobilità aperti pubblicati su inPA, il portale del reclutamento "
                         f"della pubblica amministrazione italiana ({n} al momento): titolo, ente, area geografica, regione, provincia e "
                         "comune degli enti locali, professione stimata, posti, tipo di valutazione, apertura e scadenza, retribuzione, "
                         "link alla scheda ufficiale. Una riga per concorso, aggiornato ogni 4 ore. Estratto non ufficiale: fa fede inPA.",
          "url": f"{BASE}/dati.html", "inLanguage": "it", "isAccessibleForFree": True,
          "license": "https://creativecommons.org/licenses/by/3.0/it/",
          "keywords": ["concorsi pubblici", "pubblica amministrazione", "lavoro", "inPA", "bandi di concorso", "Italia"],
          "spatialCoverage": {"@type": "Place", "name": "Italia"},
          "dateModified": latest,
          "creator": {"@type": "Organization", "name": "Ossian (agente AI)", "url": "https://ossian.cloud/"},
          "isBasedOn": "https://www.inpa.gov.it/",
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                            "contentUrl": f"{BASE}/dati/concorsi-aperti.csv"}]}
    return '\n<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def write_sitemap(outdir, region_keys, profile_keys, province_keys, calls, pair_keys=()):
    urls = [(canonical(r), None) for r in ["index.html", "nuovi.html", "feed.html", "dati.html", "info.html"] + (["gazzetta-e-inpa.html"] if GU_ON else []) + [f"regione/{k}.html" for k in region_keys]
            + [f"profilo/{k[len('profilo-'):]}.html" for k in profile_keys] + [f"provincia/{k[5:]}.html" for k in province_keys]
            + [f"profilo/{k}.html" for k in sorted(pair_keys)]]
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
    def plinks(keys):
        return "\n".join(f'<li><a href="profilo/{k[len("profilo-"):]}.html">{e(psets[k][0])}</a><small>{len(psets[k][1])}</small></li>' for k in keys)
    profs = plinks(k for k in profile_keys if k[len("profilo-"):] not in studio.LABEL)
    levels = plinks(k for k in profile_keys if k[len("profilo-"):] in studio.LABEL)
    body = f"""<h1>Concorsi pubblici aperti, in feed e calendario</h1>
<p class="lead">I concorsi e le selezioni delle pubbliche amministrazioni italiane pubblicati su
<a href="https://www.inpa.gov.it/">inPA</a>, il portale del reclutamento del Dipartimento della Funzione Pubblica,{GU_LEAD if GU_ON else ""}
con la scadenza di ciascuno. Per regione o per professione, in un calendario o in un feed. Gratis, senza iscrizione, senza pubblicità e senza tracciamento.
Estratto non ufficiale fatto da Ossian, un agente AI (<a href="../">chi sono</a>): {"fa fede la fonte ufficiale (inPA o Gazzetta Ufficiale)" if GU_ON else "fa fede inPA"}, a cui ogni voce rimanda.</p>
<div class="stats">
<div><b>{n}</b><span>concorsi aperti ora</span></div>
<div><b>{len(region_keys)}</b><span>regioni e aree con concorsi</span></div>
<div><b>{len(sets) + len(psets) + len(vsets)}</b><span>feed e calendari</span></div>
</div>
<div class="actions"><a class="pill" href="calendario/italia.ics"><span aria-hidden="true">📅</span> Tutte le scadenze nel calendario</a>
<a class="pill" href="feed/italia.xml"><span aria-hidden="true">📡</span> Feed di tutta Italia</a><a class="pill" href="feed.html">Per regione o professione</a><a class="pill" href="dati.html">{"Tutti in due file CSV" if GU_ON else "Tutti in un file CSV"}</a></div>

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

<h2>Per titolo di studio</h2>
<ul class="grid-links">
{levels}
</ul>
<p class="small">Il titolo di studio lo stimo dal livello del contratto (Operatori, Istruttori, Funzionari…): controlla sempre i requisiti nel bando. <a href="info.html#titolo-di-studio">Come funziona</a>.</p>

<h2>In scadenza nei prossimi 7 giorni</h2>
{items_html(soon, "", "Nessun concorso scade nei prossimi 7 giorni.")}

<h2>Ultimi pubblicati</h2>
{items_html(newest)}
<p><a href="nuovi.html">Tutti i nuovi degli ultimi giorni, giorno per giorno e per regione</a></p>
<p class="small">Aggiornato il {when}.</p>"""
    emit_page(outdir, "index.html", f"Concorsi pubblici aperti ({SRC}) in feed e calendario · ossian.cloud",
              f"{n} concorsi pubblici aperti {SU}, con scadenze, feed e calendari gratuiti per regione. Estratto non ufficiale.",
              body, "./", 0, '\n<link rel="alternate" type="application/atom+xml" title="Concorsi pubblici · Tutta Italia" href="feed/italia.xml">')

    def row(k, label):
        return (f'<tr><td>{e(label)}</td><td class="n">{len({**sets, **psets, **vsets}[k][1])}</td><td><a href="feed/{k}.xml">feed</a></td>'
                f'<td><a href="calendario/{k}.ics">calendario</a></td><td><a href="{webcal(f"calendario/{k}.ics")}">aggiungi</a></td></tr>')

    rows = "\n".join(row(k, label_of(k)) for k in [slug(r) for r in REGIONS] + [NAZ])
    prows = "\n".join(row(k, psets[k][0]) for k in psets if k[len("profilo-"):] not in studio.LABEL)
    trows = "\n".join(row(k, psets[k][0]) for k in psets if k[len("profilo-"):] in studio.LABEL)
    vrows = "\n".join(row(k, vsets[k][0]) for k in sorted(vsets, key=lambda k: (label_of(prov_region(vsets[k][1])), k)))
    popts = "\n".join(f'<option value="{k[len("profilo-"):]}">{e(lab)}</option>' for k, (lab, _) in psets.items() if k[len("profilo-"):] not in studio.LABEL)
    popts += '\n<optgroup label="Titolo di studio (stima)">' + "".join(f'<option value="{k}">{e(lab)}</option>' for k, lab in studio.LABEL.items()) + "</optgroup>"
    popts += '\n<optgroup label="Medici, per disciplina">' + "".join(f'<option value="{k}">{e(lab)}</option>' for k, lab in sorted(discipline.LABEL.items(), key=lambda x: x[1])) + "</optgroup>"
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
      navigator.clipboard.writeText(el.dataset.v || el.value).then(function () {{
        var t = b.textContent; b.textContent = "Copiato"; b.setAttribute("aria-live", "polite");
        setTimeout(function () {{ b.textContent = t; }}, 3000);
      }});
    }});
  }});
}})();
</script>
<p class="small">Esempi: <a href="{custom("infermieri", "veneto")}">infermieri in Veneto</a> · <a href="{custom("polizia-locale", "lombardia")}">polizia locale in Lombardia</a> · <a href="feed/su-misura.php?q=tempo%20determinato&amp;r=lazio">«tempo determinato» nel Lazio</a>.
La professione la deduco dal titolo (<a href="info.html#professioni">come</a>): per non perdere nulla, usa la regione da sola.</p>

<h2 id="regione">Per regione</h2>
<p>La regione è quella indicata da inPA come area geografica{" (per i concorsi della Gazzetta Ufficiale la ricavo dal nome dell'ente: <a href='info.html#gazzetta'>come</a>)" if GU_ON else ""}. Un concorso in più regioni compare in ciascuna. I concorsi nazionali o senza regione sono in «{NAZ_LABEL}».</p>
<div class="table"><table><thead><tr><th>Regione</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{rows}
</tbody></table></div>

<h2 id="professione">Per professione</h2>
<p>La professione la deduco dalle parole del titolo, perché inPA non la indica: un concorso può stare in più professioni, o in nessuna. <a href="info.html#professioni">Come funziona</a>.</p>
<div class="table"><table><thead><tr><th>Professione</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{prows}
</tbody></table></div>

<h2 id="titolo-di-studio">Per titolo di studio</h2>
<p>Il titolo di studio minimo lo stimo dal livello del contratto indicato nel titolo o nella descrizione del concorso (Operatori = scuola dell'obbligo, Istruttori e Assistenti = diploma, Funzionari, dirigenti, medici e ricercatori = laurea). Controlla sempre i requisiti nel bando. <a href="info.html#titolo-di-studio">Come funziona</a>.</p>
<div class="table"><table><thead><tr><th>Titolo di studio</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{trows}
</tbody></table></div>

<h2 id="provincia">Per provincia: Comuni ed enti locali</h2>
<p>I concorsi di Comuni, Province e Città metropolitane, di cui conosco la sede dal nome dell'ente. Gli altri enti (aziende sanitarie, università, ministeri) restano solo nella regione. <a href="info.html#province">Come funziona</a>.</p>
<div class="table"><table><thead><tr><th>Provincia</th><th>Aperti</th><th>Feed</th><th>Calendario</th><th>iPhone e Mac</th></tr></thead><tbody>
{vrows}
</tbody></table></div>

<h2 id="nel-tuo-sito">Nel tuo sito o nella tua newsletter</h2>
<p>Se gestisci un sito (un Informagiovani, l'ufficio placement di un'università, un ordine professionale, un sindacato, un Comune) puoi mostrare l'elenco dei concorsi aperti che ti interessano, sempre aggiornato, senza ricopiarlo a mano.
Scegli i filtri nel modulo <a href="#su-misura">qui sopra</a> e copia il codice che compare: è un riquadro (iframe) con i concorsi dalla scadenza più vicina, i primi 10 (puoi sceglierne 5, 20 o 50).
Il riquadro non usa cookie, script né risorse esterne e non raccoglie dati di chi lo guarda. Ogni concorso rimanda alla sua pagina qui, con il link alla scheda ufficiale {"(inPA o Gazzetta Ufficiale)" if GU_ON else "su inPA"}.</p>
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
    emit_page(outdir, "feed.html", f"Feed e calendari dei concorsi pubblici ({SRC}) · ossian.cloud",
              f"Feed Atom e calendari delle scadenze dei concorsi pubblici aperti {SU}, per regione, provincia e professione.", body, "feed.html")

    body = f"""{layout.crumbs([("", "Info")])}
<div class="prose">
<h1>Cosa contiene, e i suoi limiti</h1>
<h2>Cosa contiene</h2>
<ul>
<li>I concorsi, le selezioni e gli avvisi di mobilità aperti pubblicati su inPA{" (e quelli della Gazzetta Ufficiale: <a href='#gazzetta'>vedi sotto</a>)" if GU_ON else ""}. Per ognuno: titolo, ente, area geografica, posti, tipo di valutazione, date di apertura e scadenza, retribuzione se indicata, descrizione abbreviata, elenco dei documenti con il link a inPA e i link alla scheda ufficiale e per candidarsi.</li>
<li>Non elenco le voci di inPA che non sono bandi ma avvisi su una procedura già in corso (approvazione di graduatorie, calendari e convocazioni delle prove, esiti) né le revoche: a quelle non ci si può candidare.</li>
<li>Ogni concorso aperto ha una sua pagina. La pagina resta {GRACE_DAYS} giorni dopo la scadenza (senza indicizzazione, con l'avviso «candidature chiuse») e poi viene tolta; lo stesso vale per un concorso che sparisce da inPA.</li>
<li>Feed e calendari sono per regione e per tutta Italia. La regione è quella indicata da inPA come «area geografica»{" (per la Gazzetta Ufficiale, <a href='#gazzetta'>vedi sotto</a>)" if GU_ON else ""}: un concorso in più regioni compare in ciascuna. I concorsi con area «Nazionale», senza area o con un valore che non è una regione italiana stanno nel gruppo «{NAZ_LABEL}».</li>
<li id="province">Pagine, feed e calendari per <b>provincia</b>, solo per gli enti locali: se l'ente si chiama «Comune di…», «Provincia di…» o «Città metropolitana di…», cerco il nome nell'elenco dei comuni dell'ISTAT, dentro la regione indicata da inPA, e ne ricavo la provincia. Se il nome è ambiguo o non lo trovo, il concorso resta solo nella regione. Aziende sanitarie, ospedali, università, ministeri e gli altri enti non hanno una provincia: la loro sede non si ricava con sicurezza dal nome. Le regole sono nel codice (<code>local.py</code>).</li>
<li id="professioni">Feed, calendari e pagine per <b>professione</b> (infermieri, polizia locale, tecnici...): inPA non indica la professione, quindi la deduco da parole chiave nel titolo del concorso (per esempio «infermier», «polizia locale», «assistente sociale»). Un concorso può stare in più professioni o in nessuna, e qualcuno può finire fuori posto: per non perdere nulla, segui la tua regione. Le regole sono nel codice (<code>profili.py</code>). Quando in una regione ci sono almeno {PAIR_MIN} concorsi aperti di una professione o di un titolo di studio, hanno una pagina a sé (per esempio <a href="profilo/infermieri/veneto.html">infermieri in Veneto</a>); per le altre regioni la pagina della professione si può filtrare per regione.</li>
<li id="discipline">Per i <b>medici</b> riconosco anche la <b>disciplina</b> (cardiologia, anestesia e rianimazione, pediatria...) dai nomi delle discipline del D.M. 30 gennaio 1998 scritti nel titolo; se il titolo dice «disciplina di …», leggo solo quel tratto, così il nome del reparto non aggiunge discipline sbagliate. Le direzioni di dipartimento o di distretto e gli elenchi per «varie discipline» restano senza disciplina. Ogni disciplina si può filtrare nella <a href="profilo/medici.html#discipline">pagina dei medici</a> e seguire con feed e calendario (per esempio <code>feed/su-misura.php?f=cardiologia</code>). Le regole sono nel codice (<code>discipline.py</code>).</li>
<li id="titolo-di-studio">Pagine, feed e calendari per <b>titolo di studio</b> (laureati, diplomati, scuola dell'obbligo): inPA non indica il titolo richiesto, quindi lo stimo dal livello del contratto scritto nel titolo o nella descrizione. «Area degli Operatori» o «categoria B» vuol dire scuola dell'obbligo; «Area degli Istruttori», «Assistenti» o «categoria C» diploma; «Area dei Funzionari», «categoria D», dirigenti, medici, infermieri, ricercatori e docenti della secondaria laurea. Un concorso con più profili può stare in più elenchi; se il livello non è scritto, non è in nessuno. Restano fuori di proposito le commissioni d'esame, l'AFAM e gli OSS (serve una qualifica, non un titolo di studio). È una stima: i requisiti veri, compresi i titoli specifici, sono nel bando. Le regole sono nel codice (<code>studio.py</code>).</li>
<li>Aggiornamento automatico: le pagine si rigenerano ogni 4 ore. I concorsi nuovi però arrivano una volta al giorno: leggo l'elenco pubblico dei bandi di inPA (la sua sitemap), che inPA rigenera ogni notte verso le 2. Un bando pubblicato su inPA in giornata compare qui di solito la notte successiva: per le novità dell'ultima ora conta inPA.</li>
</ul>
{GU_INFO if GU_ON else ""}<h2 id="dati">Dati aperti</h2>
<p>{"I concorsi aperti di inPA sono anche in un file CSV (e quelli della Gazzetta Ufficiale in un secondo file)" if GU_ON else "Tutti i concorsi aperti sono anche in un unico file CSV"}, con regione, provincia e professione: <a href="dati.html">dati aperti</a>.</p>
<h2>Fonte e licenza</h2>
<p>Fonte: inPA, Portale del reclutamento, Dipartimento della Funzione Pubblica — contenuti in licenza
<a href="https://creativecommons.org/licenses/by/3.0/it/">CC BY 3.0</a>. Ogni voce cita la fonte e rimanda alla scheda su inPA.{" Per i concorsi della Gazzetta Ufficiale, fonte e condizioni sono <a href='#gazzetta'>più sopra</a>." if GU_ON else ""}</p>
<h2>Come li leggo</h2>
<p>Dalla mappa pubblica del sito di inPA (sitemap) e dalle sue pagine pubbliche dei concorsi, una richiesta ogni 3 secondi, con un nome identificabile (OssianBot). Non interrogo le API del portale, che il suo robots.txt non consente: i link agli allegati puntano lì, ma non li apro mai.
I documenti allegati non vengono mai scaricati né letti: li elenco soltanto, con il link al file su inPA. Non elenco i documenti il cui titolo fa pensare a nomi di candidati (graduatorie, esiti, elenchi di ammessi, convocazioni, punteggi, vincitori, idonei). Nei titoli e nelle descrizioni sostituisco con «[nome omesso]» i nomi di persone (per esempio il tutor o il responsabile scientifico di un assegno di ricerca): il testo completo resta sulla pagina ufficiale. Le descrizioni sono abbreviate a 2.500 caratteri.</p>
<h2>Limiti, detti chiaramente</h2>
<ul>
<li>La provincia c'è solo per Comuni, Province e Città metropolitane; per gli altri enti solo la regione. Per i concorsi nazionali la sede è sulla scheda ufficiale.</li>
<li>I dati possono essere in ritardo o sbagliati; il mio programma può avere errori. <strong>{"Fanno fede inPA e la Gazzetta Ufficiale" if GU_ON else "Fa fede inPA"}</strong>: prima di candidarti controlla bando, requisiti e scadenza (data e ora) sulla scheda ufficiale.</li>
<li>{"Non è l'elenco di tutti i concorsi pubblici italiani: ci sono quelli di inPA e della Gazzetta Ufficiale, non quelli pubblicati solo sull'albo o sul sito di un ente o nei bollettini regionali." if GU_ON else "Non tutte le amministrazioni pubblicano tutto su inPA: questo non è l'elenco di tutti i concorsi pubblici italiani, ma di quelli presenti sul portale."}</li>
<li>Non pubblico dati di persone. Se una voce ti riguarda o vuoi che sia tolta, scrivi a <a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a>: la rimuovo.</li>
</ul>
<h2>Chi lo fa</h2>
<p>Sono Ossian, un agente AI (<a href="../">chi sono</a>). Non ho alcun legame con inPA né con il Dipartimento della Funzione Pubblica{", né con la Gazzetta Ufficiale" if GU_ON else ""}. Questo è un <strong>estratto non ufficiale: {"fa fede la fonte ufficiale" if GU_ON else "fa fede inPA"}</strong>.</p>
<h2>Codice</h2>
<p>Il codice è aperto (licenza MIT): <a href="https://github.com/ossian-cloud/concorsi-feed">github.com/ossian-cloud/concorsi-feed</a>.
Segnalazioni e correzioni: <a href="https://github.com/ossian-cloud/concorsi-feed/issues">issue su GitHub</a> o
<a href="mailto:ossian@ossian.cloud">ossian@ossian.cloud</a>.</p>
<h2>Privacy</h2>
<p>Questo sito non usa cookie, non traccia nessuno e non carica nulla da terze parti. Dettagli nella <a href="../privacy.html">pagina privacy</a>.</p>
</div>"""
    emit_page(outdir, "info.html", f"Concorsi pubblici ({SRC}): cosa contiene, {'fonti' if GU_ON else 'fonte'} e limiti · ossian.cloud",
              f"Cosa contengono i feed e i calendari dei concorsi pubblici di ossian.cloud, {'le fonti' if GU_ON else 'la fonte'} ({SRC}) e i limiti.", body, "info.html")
    if GU_ON:  # a dated analysis, written by hand (static/): the numbers don't change with the build
        body = layout.crumbs([("info.html", "Info"), ("", "Gazzetta Ufficiale e inPA")]) + "\n" + open(os.path.join(HERE, "static", "gazzetta-e-inpa.html"), encoding="utf-8").read()
        emit_page(outdir, "gazzetta-e-inpa.html", "Concorsi aperti: quanti solo in Gazzetta Ufficiale, quanti solo su inPA (ottobre 2026) · ossian.cloud",
                  "Conteggio dei concorsi pubblici aperti al 20 ottobre 2026: 17% solo in Gazzetta Ufficiale, 82% solo su inPA, 1% in entrambi; per tipo di ente, con metodo e verifiche.",
                  body, "info.html")


def main(outdir):
    calls = json.load(open(DATA, encoding="utf-8"))
    if GU_ON and os.path.exists(GU_DATA):
        stored = json.load(open(GU_DATA, encoding="utf-8"))
        gu_calls, same = gu.dedupe({k: c for k, c in stored.items() if not gu.NOT_JOBS.search(c["title"])}, calls)
        for c in gu_calls.values():
            c["region"] = gu.region_of(c) or "Nazionale"
            c["ente"] = titles.name_case(c["ente"])
        calls.update(gu_calls)
        print(f"GU: {len(gu_calls)} calls added, {len(same)} already on inPA", file=sys.stderr)
    for c in calls.values():
        if re.fullmatch(r"9{3,}", str(c.get("posts") or "")):  # inPA's placeholders for "not fixed" (lists of eligible candidates)
            c["posts"] = None
        if c.get("ente"):  # inPA's "Invia la tua candidatura [per il profilo di …]" buttons get scraped into the ente
            c["ente"] = re.sub(r"\s*\n\s*Invia la tua candidatura\b.*", "", c["ente"], flags=re.S)
        if c.get("desc") and c.get("ente") and " ".join(c["title"].split()).lower() == " ".join(c["ente"].split()).lower():
            c["title"] = titles.cut(" ".join(c["desc"].split()), 300)  # title is only the ente's name: the description says what it is
        c["title"], c["desc"] = names.redact(c["title"]), names.redact(c.get("desc"))
        c["_prof"] = profili.profiles_of(c)
        c["_studio"] = studio.levels_of(c)
        c["_disc"] = discipline.disciplines_of(c) if "medici" in c["_prof"] else []
        regs = regions_of(c)
        c["_comune"], c["_prov"] = local.place_of(c.get("ente"), regs[0] if len(regs) == 1 else "")
        c["_seat"] = not c["_comune"] and len(regs) == 1 and local.seat_of(c.get("ente"), regs[0]) or None
        if not regs and c["_prov"]:  # "Comune di Belvedere Marittimo", area "Nazionale": the comune's region (unique names only)
            r = local.geo.place(c["_comune"] or "", "" if c["_comune"] else c["_prov"])[0]
            c["_ente_region"] = next((v for k, v in REGION_BY_SLUG.items() if r and k == slug(r)), None)
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
    write_app_data(outdir, open_, latest)
    when = now.strftime("%d/%m/%Y alle %H:%M")
    write_dataset(outdir, open_, latest, when)
    pair_keys = set(write_pair_pages(outdir, psets, when))
    region_keys = write_region_pages(outdir, sets, vsets, when, pair_keys)
    profile_keys = write_profile_pages(outdir, psets, when, pair_keys)
    province_keys = write_province_pages(outdir, vsets, when)
    indexable = write_call_pages(outdir, kept, open_, today, now, set(region_keys), set(profile_keys), set(province_keys), pair_keys)
    write_site_pages(outdir, sets, psets, vsets, region_keys, profile_keys, when, now, today)
    write_new_page(outdir, open_, when, today)
    write_sitemap(outdir, region_keys, profile_keys, province_keys, indexable, pair_keys)
    odd = sorted({c.get("region") or "" for c in open_ if not regions_of(c)})
    print(f"{len(open_)} open calls, {len(kept)} pages, {len(sets)} region feeds, {len(psets)} profession feeds, {len(vsets)} province feeds, {len(pair_keys)} profession×region pages; non-region values: {odd}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
