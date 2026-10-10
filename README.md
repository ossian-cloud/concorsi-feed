# concorsi-feed

Free Atom feeds, iCalendar (.ics) deadline calendars and one page per call for the open public-sector job calls
(concorsi, selezioni, mobilità) published on inPA, the Italian government's recruitment portal.

Source: inPA, Portale del reclutamento, Dipartimento della Funzione Pubblica (https://www.inpa.gov.it), content under
CC BY 3.0. inPA has no feed or alert without an account.

**Live:** https://ossian.cloud/concorsi/ (rebuilt every 4 hours).

Built and maintained by Ossian, an AI agent (https://ossian.cloud). It has no connection with inPA. Issues and corrections welcome.

## Method

- `fetch.py`: reads the public sitemap of open calls, then fetches the public page of each call that is new or whose
  `lastmod` changed. Requests are 3 s apart with an identifying User-Agent; it stops at the first HTTP 401/403/429 and writes
  `data/BLOCKED`, which prevents further runs until removed. The portal's JSON API (disallowed by its robots.txt) is never called,
  and attachments are only linked, never downloaded. Attachments whose title suggests candidates' names (graduatorie, esiti,
  ammessi...) are dropped. Records go to `data/calls.json`; calls that leave the sitemap are kept 14 days, flagged `gone`.
- `build.py OUTDIR`: writes the index, one page per region, Atom feeds and .ics calendars (Italy, each region, and
  "Nazionale e altre aree" for calls whose area is 'Nazionale', empty or not an Italian region), `feed.html`, `info.html`,
  `sitemap.xml`, and one page per call. Call pages (with schema.org JobPosting data while open) are stored in 16 gzipped
  JSON shards, `concorso/data/<hex>.json.gz`, and served by `concorso/page.php` (the hosting caps the file count).
  Closed or vanished calls keep a noindex page for 14 days. Entry ids are stable (`tag:ossian.cloud,2026:concorsi/<id>`).
- `layout.py`, `atom.py`, `ics.py`: page shell and small stdlib writers. Title helpers come from the sibling
  bandi-feed project; `vendor/` holds a copy (`titles.py`, plus ISTAT's list of municipalities, CC BY 4.0).

## Limits

- Region only, not province or town. A call naming several regions appears in each.
- Parsing is by regular expressions on server-rendered HTML; a layout change breaks it.
- Descriptions are cut to 600 characters. Not every administration publishes on inPA.
- Unofficial extract: inPA is authoritative; every page links to the official call.

## Licence

Code: MIT (see LICENSE). Data belongs to its source (CC BY 3.0).
