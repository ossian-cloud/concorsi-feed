"""Fetch open public-sector job calls (concorsi, mobilità, avvisi) from inPA, the Italian government's
recruitment portal, and keep slim records.

Route: the public sitemap https://www.inpa.gov.it/sitemap-bandi.xml lists the open calls with a lastmod;
each call has a server-rendered page on www.inpa.gov.it. Both are allowed by robots.txt. The portal's JSON
API (portale.inpa.gov.it) is disallowed by its robots.txt, so it is never called, and neither are the
attachments there: we only link to them. Content is CC BY 3.0 (Note legali of the Dipartimento della
Funzione Pubblica): cite inPA and link back to the call's page.

Usage: python3 fetch.py [--max N]
Writes data/calls.json (dict id -> record). Fetches only calls that are new or whose lastmod changed,
one request every PAUSE seconds, saving as it goes so an interrupted run resumes. Calls that leave the
sitemap are kept with 'gone' set for GRACE_DAYS. Refuses to run while data/BLOCKED exists.
"""
import argparse
import datetime as dt
import fcntl
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SITEMAP = "https://www.inpa.gov.it/sitemap-bandi.xml"
DESC_MAX = 2500     # characters of description kept (600 until 2026-10-11; those cut at 600 are re-read, REFETCH_MAX a run)
REFETCH_MAX = 150
PAGE = "https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id={}"
UA = "OssianBot/0.1 (+https://ossian.cloud/concorsi/; ossian@ossian.cloud)"
PAUSE = 3
GRACE_DAYS = 14
STALE_DAYS = 2  # a sitemap this many days behind our newest stored lastmod is a stale copy
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "calls.json")
BLOCKED = os.path.join(HERE, "data", "BLOCKED")
MONTHS = {m: i + 1 for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre "
                                          "ottobre novembre dicembre".split())}
# Attachments whose title suggests names of candidates: never listed (rankings, admitted lists, results, summons).
PERSONAL = re.compile(r"graduatori|ammess|esit[oi]|convocazion|punteggi|candidat|nominativ|elenco|vincitor|idone", re.I)


class Blocked(Exception):
    pass


_last = 0.0


def get(url):
    global _last
    wait = PAUSE - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            raise Blocked(f"HTTP {e.code} on {url}")
        raise
    finally:
        _last = time.time()


def text(s):
    s = re.sub(r"<br\s*/?>|</p>", "\n", s or "")
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in s.splitlines() if line.strip())


def when(s):
    """'09 Ottobre 2026  00:01' -> '2026-10-09T00:01' (Rome local time, as shown)."""
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", (s or "").strip())
    if not m or m.group(2).lower() not in MONTHS:
        return None
    d = dt.datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0))
    return d.strftime("%Y-%m-%dT%H:%M")


def money(s):
    m = re.search(r"[\d.]+(,\d+)?", s or "")
    return float(m.group(0).replace(".", "").replace(",", ".")) if m else None


def parse(page):
    """The fields of one call page. Raises ValueError if the page doesn't look like one."""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not h1 or "concorso-label" not in page:
        raise ValueError("no call on page")
    fields = {}
    for label, body in re.findall(r'concorso-label[^>]*>\s*([^<:]+):\s*</span>(.*?)(?=<span class="concorso-label|<div class="d-block|</article)', page, re.S):
        fields[label.strip()] = body
    desc = text(fields.get("Descrizione", ""))
    attach = []
    for href, title in re.findall(r'<a[^>]+href="(https://portale\.inpa\.gov\.it/api/media/[^"]+)"[^>]*>(.*?)</a>',
                                   fields.get("Bando/Avviso e Allegati", ""), re.S):
        t = " ".join(text(title).split())
        pub = re.search(r"\(Pubblicato il ([^)]*)\)\s*$", t)
        t = t[:pub.start()].strip() if pub else t
        if t and not PERSONAL.search(t):
            attach.append({"title": t, "url": html.unescape(href), "pub": when(pub.group(1)) if pub else None})
    pa = re.search(r'href="([^"]+)"', fields.get("Link al sito della PA", ""))
    posts = re.search(r"\d+", text(fields.get("Numero di posti", "")))
    return {
        "title": text(h1.group(1)),
        "desc": desc[:DESC_MAX],
        "desc_max": DESC_MAX,
        "region": text(fields.get("Area geografica", "")),
        "eval": text(fields.get("Valutazione", "")),
        "status": text(fields.get("Stato", "")),
        "opens": when(text(fields.get("Data apertura candidature", ""))),
        "closes": when(text(fields.get("Data chiusura candidature", ""))),
        "posts": int(posts.group(0)) if posts else None,
        "ente": text(fields.get("Ente di riferimento", "")),
        "pa_url": html.unescape(pa.group(1)) if pa else None,
        "pay_min": money(text(fields.get("Corrispettivo minimo annuo", ""))),
        "pay_max": money(text(fields.get("Corrispettivo massimo annuo", ""))),
        "attachments": attach,
    }


def sitemap():
    xml = get(SITEMAP)
    out = {}
    for loc, lastmod in re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml):
        m = re.search(r"concorso_id=([0-9a-f]{32})", loc)
        if m:
            out[m.group(1)] = lastmod
    if len(out) < 100:
        raise Blocked(f"sitemap has only {len(out)} calls")
    return out


def save(calls):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(calls, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DATA)


def block(reason):
    os.makedirs(os.path.dirname(BLOCKED), exist_ok=True)
    open(BLOCKED, "w").write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {reason}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="fetch at most N pages this run (0 = all)")
    a = ap.parse_args()
    if os.path.exists(BLOCKED):
        sys.exit(f"data/BLOCKED exists, not running: {open(BLOCKED).read().strip()}")
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    lock = open(DATA + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one fetch at a time (the service, or a manual backfill)
    except BlockingIOError:
        sys.exit("another fetch is running")
    calls = json.load(open(DATA)) if os.path.exists(DATA) else {}
    now = dt.datetime.now(dt.timezone.utc)
    try:
        listed = sitemap()
    except Blocked as e:
        block(str(e))
        sys.exit(f"BLOCKED: {e}")
    # a stale cached sitemap (14 Oct 10:13: newest lastmod 27 Sep) would mark hundreds of open calls gone;
    # skip this run instead, without blocking: the next cycle usually gets the current one
    newest = max((c.get("lastmod", "") for c in calls.values()), default="")
    if newest and max(listed.values()) < (dt.datetime.fromisoformat(newest.replace("Z", "+00:00"))
                                          - dt.timedelta(days=STALE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        sys.exit(f"stale sitemap: newest lastmod {max(listed.values())}, stored {newest}; not updating")
    for cid, c in calls.items():
        if cid not in listed and not c.get("gone"):
            c["gone"] = now.isoformat(timespec="seconds")
        elif cid in listed:
            c.pop("gone", None)
    for cid in [k for k, c in calls.items() if c.get("gone") and now - dt.datetime.fromisoformat(c["gone"]) > dt.timedelta(days=GRACE_DAYS)]:
        del calls[cid]
    todo = [cid for cid, lm in sorted(listed.items(), key=lambda x: x[1], reverse=True)
            if cid not in calls or calls[cid].get("lastmod") != lm]
    todo += [cid for cid in listed if cid in calls and cid not in todo and calls[cid].get("desc_max", 600) < DESC_MAX
             and len(calls[cid].get("desc") or "") >= calls[cid].get("desc_max", 600)][:REFETCH_MAX]
    if a.max:
        todo = todo[:a.max]
    print(f"{len(listed)} listed (newest lastmod {max(listed.values(), default='-')}), {len(calls)} stored, {len(todo)} to fetch", flush=True)
    done = errors = 0
    for cid in todo:
        try:
            rec = parse(get(PAGE.format(cid)))
        except Blocked as e:
            block(str(e))
            save(calls)
            sys.exit(f"BLOCKED: {e}")
        except (ValueError, urllib.error.URLError, TimeoutError) as e:
            errors += 1
            print(f"{cid}: {e}", file=sys.stderr, flush=True)
            if errors >= 10 and errors > done:
                block(f"{errors} errors in {done + errors} pages, last: {e}")
                save(calls)
                sys.exit("BLOCKED: too many errors")
            continue
        rec.update(id=cid, lastmod=listed[cid], fetched=now.isoformat(timespec="seconds"))
        calls[cid] = rec
        done += 1
        if done % 25 == 0:
            save(calls)
            print(f"{done}/{len(todo)}", flush=True)
    save(calls)
    print(f"fetched {done}, errors {errors}, total {len(calls)}", flush=True)


if __name__ == "__main__":
    main()
