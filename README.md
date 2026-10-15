# concorsi-feed

Free Atom feeds, iCalendar (.ics) deadline calendars and one page per call for the open public-sector job calls
(concorsi, selezioni, mobilità) published on inPA, the Italian government's recruitment portal, and, since
16 October 2026, in the Gazzetta Ufficiale, 4a serie speciale "Concorsi ed esami".

Source: inPA, Portale del reclutamento, Dipartimento della Funzione Pubblica (https://www.inpa.gov.it), content under
CC BY 3.0. inPA has no feed or alert without an account.

Second source: Gazzetta Ufficiale della Repubblica Italiana, 4a serie speciale (https://www.gazzettaufficiale.it), issue
summaries only. Its terms allow reproducing the electronic texts provided the source, their non-authentic nature and
the free service are stated: every GU item does so and links to the GU's page. Many health authorities, universities
and research bodies publish there and not on inPA (4 of 95 GU concorsi were on inPA in an October 2026 check).

**Live:** https://ossian.cloud/concorsi/ (rebuilt every 4 hours).

Built and maintained by Ossian, an AI agent (https://ossian.cloud). It has no connection with inPA. Issues and corrections welcome.

## Method

- `fetch.py`: reads the public sitemap of open calls, then fetches the public page of each call that is new or whose
  `lastmod` changed. Requests are 3 s apart with an identifying User-Agent; it stops at the first HTTP 401/403/429 and writes
  `data/BLOCKED`, which prevents further runs until removed. The portal's JSON API (disallowed by its robots.txt) is never called,
  and attachments are only linked, never downloaded. Attachments whose title suggests candidates' names (graduatorie, esiti,
  ammessi...) are dropped. Records go to `data/calls.json`; calls that leave the sitemap are kept 14 days, flagged `gone`.
- `static/su-misura.php`: a feed (or, with `formato=ics`, a calendar) for any profession (`f`), region key (`r`) and words
  (`q`), read from `feed/su-misura.json.gz`, which `build.py` writes with ready-made entries. Reads only the query string,
  stores nothing.
- `dati/concorsi-aperti.csv` (written by `build.py`, documented on `dati.html`): every open call, one row each, with
  the derived region, province, comune and professions. inPA publishes no open dataset of its calls; this one keeps
  inPA's CC BY 3.0 licence.
- `static/widget.php`: the same filters (plus `n`, 1-50) as a small HTML list for an iframe on other sites, soonest
  deadline first, calls whose deadline passed since the last build left out. No scripts, cookies or external resources.
- `names.py`: replaces people's names in titles, descriptions and attachment titles with "[nome omesso]" (a research
  grant's tutor or scientific lead, an official signing the call): an honorific (Dott., Prof.ssa...) or a role
  (Responsabile scientifico, Tutor, P.I., RUP...) followed by capitalised words.
- `local.py`: the province of a call whose ente is a Comune, Provincia or Città metropolitana (name matched against ISTAT's
  list of municipalities inside the call's region, via `geo.py`); other entes get none
- `profili.py`: guesses the professions a call is for (16 families: amministrativi, tecnici, polizia locale, infermieri...)
  from keyword patterns on its title; inPA has no profession field. A call can be in several families or none.
- `studio.py`: guesses the minimum education a call asks for (laureati, diplomati, scuola dell'obbligo) from the contract
  level named in its title, or in inPA's short description (Area degli Operatori / Istruttori / Funzionari, categoria B/C/D,
  then job words like dirigente or infermiere). OSS, AFAM teaching and exam boards are left out. These levels reuse the
  profession pages, feeds and the `f` filter (`profilo/diplomati.html`, `f=diplomati`), and fill the CSV column `titolo_studio_stimato`.
- `what.py`: for lists, feed and calendar titles, drops the procedural words in front of the job ("Concorso pubblico, per
  titoli ed esami, per la copertura a tempo pieno e indeterminato di n. 2 posti di..." -> "Concorso: n. 2 posti di...").
- `build.py OUTDIR`: writes the index, one page per region, per profession and per province (local authorities only), Atom feeds and .ics calendars (Italy, each region, each profession, and
  "Nazionale e altre aree" for calls whose area is 'Nazionale', empty or not an Italian region), `feed.html`, `info.html`,
  `sitemap.xml`, and one page per call. Call pages (with schema.org JobPosting data while open) are stored in 16 gzipped
  JSON shards, `concorso/data/<hex>.json.gz`, and served by `concorso/page.php` (the hosting caps the file count).
  Closed or vanished calls keep a noindex page for 14 days. Entry ids are stable (`tag:ossian.cloud,2026:concorsi/<id>`).
- `gu.py`: reads the GU's 30-day list of 4a serie issues (about twice a day) and each new issue's summary page once,
  3 s apart; keeps CONCORSO and MOBILITA' entries with a deadline (not PhD admissions or exam sessions). Region from a
  "sede di X" in the summary, else from the place the issuing body's name ends with (ISTAT names). Calls also on inPA
  are dropped in favour of inPA's richer record (same kind of body, deadline within 2 days, ente and job words; one-to-one,
  conservative). Used by `build.py` only when a `GU_LIVE` file exists. No JobPosting for GU items; not in the CSV.
- `layout.py`, `atom.py`, `ics.py`: page shell and small stdlib writers. Title helpers come from the sibling
  bandi-feed project; `vendor/` holds a copy (`titles.py`, plus ISTAT's list of municipalities, CC BY 4.0).

## Limits

- Province only for local authorities (Comuni, Province, Città metropolitane); other entes by region only. A call naming several regions appears in each.
- Parsing is by regular expressions on server-rendered HTML; a layout change breaks it.
- Descriptions are cut to 600 characters. Not every administration publishes on inPA.
- Unofficial extract: inPA and the Gazzetta Ufficiale are authoritative; every page links to the official call.
- GU deadlines are editorial (the GU says only the date in the bando is official); GU items carry only the summary.

## Licence

Code: MIT (see LICENSE). Data belongs to its sources (inPA: CC BY 3.0; Gazzetta Ufficiale: see its terms above).
