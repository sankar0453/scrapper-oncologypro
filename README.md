# esmo-scraper

Dynamic URL / metadata / PDF collector for any conference on
`oncologypro.esmo.org`. Talks directly to the site's own public Kontent.ai
Delivery API instead of paginating the UI -- see
`~/.claude/skills/esmo-oncologypro-scraper/SKILL.md` for how that API was
found and how it's shaped.

## Demo

![demo](docs/demo.gif)

23 seconds: dynamic conference discovery (`list-conferences`), format
availability for one congress (`formats`), a real run with PDF rendering
(`run --render-pdfs`), then proof of output -- the folder tree it wrote and
the `content_status` breakdown from the master metadata file, showing public
abstracts rendered and gated eposters correctly skipped. Recorded with
[asciinema](https://asciinema.org); the source `.cast` and the exact scripted
commands are in [`docs/`](docs). Full write-up: [`CASE_STUDY.md`](CASE_STUDY.md).

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .          # core
./.venv/bin/pip install -e ".[s3]"    # + boto3, only if you'll use --storage s3
```

## Quick start

```bash
# What conferences exist right now? (dynamic -- scans live content, nothing hardcoded)
esmo-scraper list-conferences --search "ESMO Congress"

# What formats (abstract/eposter/slides/webcast) does a specific one have?
esmo-scraper formats --congress-search "ESMO Congress 2026"

# Collect URLs + metadata for one or more formats
esmo-scraper run --congress-search "ESMO Congress 2026" --congress-slug esmo-congress-2026 \
  --formats abstract --local-root data

# Also render a PDF per item, for formats that turn out to be public content
esmo-scraper run --congress-search "ESMO Congress 2026" --congress-slug esmo-congress-2026 \
  --formats abstract eposter slides --render-pdfs --local-root data
```

`--congress-slug` is just the URL path segment after `congress-resources/` on
oncologypro -- read it off the URL the user gives you.

## Format accessibility (important)

Empirically, on `oncologypro.esmo.org`:

- **abstract** content is tagged `Public` -- full text is fetchable through
  this same public API, so `--render-pdfs` can render real PDFs from it.
- **eposter**, **slides**, **webcast** content is tagged `Members`/`Tickets`
  -- these items exist and their *catalog metadata* (URL, title, citation)
  is always collected, but the API's own listing endpoint excludes them from
  bulk queries once gated, and a direct per-item fetch returns only security
  metadata, no content. This tool treats that as a hard boundary: it never
  logs in or carries a session, so gated formats are recorded with
  `content_status: "gated"` and nothing is downloaded for them. If a future
  conference turns out to expose a format publicly, the tool detects that
  per-conference (see `collectors/content.py: probe_type_gated`) rather than
  assuming based on format name.

## Folder structure

```
data/
└── {congress-slug}/                          # e.g. esmo-congress-2026
    ├── master_metadata.jsonl                 # CUMULATIVE across every run against
    │                                          # this conference -- one row per
    │                                          # (presentation, format), upserted in
    │                                          # place. This is what answers "what do
    │                                          # we currently have for this conference".
    │
    └── {run_id}/                              # e.g. 20261121T003315Z-7h2kq
        │                                       # (UTC timestamp + random suffix:
        │                                       #  sortable, unique even for two runs
        │                                       #  started in the same second)
        ├── urls/
        │   ├── abstract.csv
        │   ├── abstract.jsonl
        │   ├── eposter.csv
        │   └── slides.csv
        ├── pdfs/
        │   └── abstract/
        │       ├── 8446__some-title.pdf
        │       └── ...
        ├── logs/
        │   ├── run.log                        # human-readable
        │   └── run.jsonl                       # structured, one JSON object per line
        └── run_summary.json                   # counts + timing for exactly this run
```

Running the **same conference again** writes a new `{run_id}/` (so you keep
every run's own URL list / PDFs / logs for audit), while
`master_metadata.jsonl` is updated in place: items unchanged since the last
run are marked `"unchanged"` and (if a PDF already exists for them) are
**not** re-rendered; only `"new"` or `"updated"` items do real work. This is
what makes re-running safe and cheap.

Running a **different conference** just uses a different `{congress-slug}`
top-level directory -- fully isolated, no shared state.

Selecting **multiple formats** (`--formats abstract eposter slides`) writes
one subtree per format under `urls/` and `pdfs/`, and one row per
`(presentation, format)` pair in `master_metadata.jsonl` (keyed as
`{presentation_codename}::{format}`), so each format's status is tracked
independently -- e.g. a presentation can be `"public"`/rendered for
`abstract` and `"gated"` for `eposter` at the same time.

With `--storage s3`, the exact same relative paths become S3 keys under
`s3://{bucket}/{prefix}/...` -- the folder structure above is the key
structure.

## Observability

Every run gets a `run_id` that tags every log line (console + `run.log` +
structured `run.jsonl`) so concurrent or repeated runs never get mixed up
when you grep or ingest logs later. `run.jsonl` is ready to feed into
CloudWatch Logs / Datadog / Loki / `jq` without a custom parser -- each line
has `ts`, `level`, `run_id`, `stage`, and stage-specific fields (counts,
durations, error text). `run_summary.json` is the one-file answer to "how
did this run go" (rows collected, PDFs rendered vs skipped-unchanged vs
gated-skipped, errors, duration) and `master_metadata.jsonl`'s status counts
are the cumulative answer to "what do we have overall".

## Proxy

```bash
esmo-scraper run ... --proxy http://user:pass@host:port
esmo-scraper run ... --proxy-list proxies.txt     # round-robins, retires dead proxies
# or: export ESMO_SCRAPER_PROXY=... / ESMO_SCRAPER_PROXY_LIST=...
```

Request pacing (`--request-delay`, default 0.25s between pages) stays the
same regardless of proxy count -- proxies here are for egress routing, not
for evading rate limits.

## S3

Yes -- PDFs and the metadata/URL files can go straight to S3 instead of (or
as a staging area before moving to) local disk:

```bash
esmo-scraper run ... --storage s3 --s3-bucket my-bucket --s3-prefix esmo
```

AWS credentials are never read from this tool's config -- boto3's normal
credential chain handles it (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env
vars, an `AWS_PROFILE`, or an instance/role credential when running on AWS
infrastructure). Nothing here creates the bucket or IAM policy for you --
set those up with whatever IaC you already use (console, Terraform, CDK);
the tool just needs `s3:PutObject`/`s3:GetObject`/`s3:ListBucket` on the
prefix you give it.

## Licensing / Terms of Use note

Abstract content belongs to its authors / the congress's publishing journal
and is covered by ESMO's Terms of Use (personal, non-commercial use; no
redistribution without ESMO's written permission -- see
`esmo.org/terms-of-use/website-terms-conditions`). This tool doesn't enforce
that for you; it's on whoever runs it and whatever they do with the output.

### What's safe to put in a public repo / portfolio (not legal advice)

| Item | Public repo? | Why |
|---|---|---|
| This source code | **Yes** | Your own original work; it never embeds or ships any scraped content. |
| The demo GIF/video | **Yes** | Shows public conference names and a handful of titles on screen -- the same short, factual text any search engine or citation index displays, not reproduced abstract bodies. |
| `CASE_STUDY.md` / architecture diagrams | **Yes** | Original writing and diagrams describing the system; cites ESMO's own Terms of Use rather than copying content from the site. |
| A small illustrative sample (a handful of rows) of URLs/titles/citations | Low risk | Bibliographic metadata (titles, citations, URLs) is generally treated like a citation index, not a copyrighted work in itself -- but keep it to a handful, not the full scraped set, out of caution. |
| The full compiled dataset (`abstracts_*.csv/json`, `master_metadata.jsonl` for a real run) | **No** | ESMO's Terms define "Content" broadly enough to cover compiled abstract metadata, and restrict use to "personal use" -- a dataset published for anyone to download goes beyond that, regardless of whether it's monetized. |
| The rendered PDFs (full abstract text) | **No** | This is the actual copyrighted material (author / *Annals of Oncology*), and ESMO's Terms explicitly require written permission before any redistribution. |

`.gitignore` in this repo already excludes the PDFs, the zip, and the
compiled CSV/JSON outputs for this reason -- they're useful to generate
locally for your own reference, not to commit.
