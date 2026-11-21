from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import time

from .api_client import KontentClient
from .collectors import content as content_collector
from .collectors import urls as url_collector
from .config import FORMAT_FIELD_MAP, ProxyConfig, RunConfig, StorageConfig
from .discovery import available_formats, list_conferences, resolve_conference
from .logging_setup import new_run_id, setup_logging
from .manifest import MasterMetadata
from .proxy import ProxyPool
from .render.pdf import render_pdf_bytes, safe_filename
from .storage import build_storage


def _add_common_args(p: argparse.ArgumentParser):
    p.add_argument("--congress-search", required=True, help='e.g. "ESMO Congress 2026"')
    p.add_argument("--congress-slug", required=True, help='URL slug, e.g. "esmo-congress-2026"')
    p.add_argument("--formats", nargs="+", default=["abstract"], choices=sorted(FORMAT_FIELD_MAP.keys()))
    p.add_argument("--limit", type=int, default=0, help="Cap on presentations scanned (0 = no limit)")
    p.add_argument("--render-pdfs", action="store_true", help="Also render PDFs for public-content formats")
    p.add_argument("--allow-gated", action="store_true",
                    help="Still attempt fetch_bodies for non-public formats (the public API will just return "
                         "whatever it's willing to expose -- this never authenticates)")
    p.add_argument("--storage", choices=["local", "s3"], default="local")
    p.add_argument("--local-root", default="data")
    p.add_argument("--s3-bucket")
    p.add_argument("--s3-prefix", default="esmo")
    p.add_argument("--s3-region")
    p.add_argument("--proxy", help="http(s)://user:pass@host:port, or set $ESMO_SCRAPER_PROXY")
    p.add_argument("--proxy-list", help="path to a file of proxy URLs to round-robin, or set $ESMO_SCRAPER_PROXY_LIST")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--no-json-logs", action="store_true")
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--request-delay", type=float, default=0.25)
    p.add_argument("--refresh-conferences", action="store_true",
                    help="Bypass the ~1h local conference-list cache (use right after a new congress goes live)")


def _config_from_args(args) -> RunConfig:
    return RunConfig(
        congress_search=args.congress_search,
        congress_slug=args.congress_slug,
        formats=args.formats,
        limit=args.limit,
        render_pdfs=args.render_pdfs,
        allow_gated=args.allow_gated,
        storage=StorageConfig(
            backend=args.storage, local_root=args.local_root,
            s3_bucket=args.s3_bucket, s3_prefix=args.s3_prefix, s3_region=args.s3_region,
        ),
        proxy=ProxyConfig.from_env_and_args(args.proxy, args.proxy_list),
        log_level=args.log_level,
        log_json=not args.no_json_logs,
        batch_size=args.batch_size,
        request_delay_seconds=args.request_delay,
    )


def cmd_list_conferences(args):
    client = KontentClient()
    confs = list_conferences(client, force_refresh=args.refresh_conferences)
    search = (args.search or "").lower()
    for codename, name in sorted(confs.items(), key=lambda kv: kv[1]):
        if search in name.lower():
            print(f"{name}\t{codename}")


def cmd_formats(args):
    client = KontentClient()
    match = resolve_conference(client, args.congress_search, force_refresh=args.refresh_conferences)
    if not match:
        print("No single conference match -- run list-conferences to see options.", file=sys.stderr)
        sys.exit(1)
    ticket_code, name = match
    print(f"{name} ({ticket_code})")
    for field_name, count in available_formats(client, ticket_code).items():
        print(f"  {field_name}: {count}")


def cmd_run(args):
    cfg = _config_from_args(args)
    run_id = new_run_id()

    storage = build_storage(cfg.storage)
    run_root = f"{cfg.congress_slug}/{run_id}"
    logger = setup_logging(run_id, os.path.join(cfg.storage.local_root, run_root, "logs")
                            if cfg.storage.backend == "local" else f"/tmp/esmo_scraper_logs/{run_id}",
                            level=cfg.log_level, json_logs=cfg.log_json)
    logger.info("run starting", extra={
        "stage": "run_start", "congress_search": cfg.congress_search, "congress_slug": cfg.congress_slug,
        "formats": cfg.formats, "render_pdfs": cfg.render_pdfs, "storage_backend": cfg.storage.backend,
    })
    t0 = time.monotonic()

    proxy_pool = ProxyPool(cfg.proxy)
    client = KontentClient(proxy_pool=proxy_pool, max_retries=cfg.max_retries, request_delay_seconds=cfg.request_delay_seconds)

    match = resolve_conference(client, cfg.congress_search, force_refresh=args.refresh_conferences)
    if not match:
        logger.error("aborting: conference did not resolve to exactly one match", extra={"stage": "run_abort"})
        sys.exit(1)
    ticket_code, conference_name = match
    logger.info("conference resolved", extra={"stage": "resolve", "conference_name": conference_name, "ticket_code": ticket_code})

    # 1) collect URLs + catalog metadata for every selected format, in one pass
    rows = list(url_collector.collect(client, ticket_code, cfg.congress_slug, cfg.formats, limit=cfg.limit))
    logger.info("collected rows", extra={"stage": "collect_urls_done", "row_count": len(rows)})

    # per-run snapshot: exactly what this run saw, by format
    by_format: dict[str, list[dict]] = {}
    for r in rows:
        by_format.setdefault(r["format"], []).append(r)
    for fmt, fmt_rows in by_format.items():
        _write_csv(storage, f"{run_root}/urls/{fmt}.csv", fmt_rows)
        storage.write_text(f"{run_root}/urls/{fmt}.jsonl", "\n".join(json.dumps(r, default=str) for r in fmt_rows) + "\n")

    # 2) optionally fetch body content + render PDFs for public-content formats
    #    only for the codenames we actually collected rows for, not the whole
    #    conference -- cost scales with rows (respects --limit), not with the
    #    conference's total item count.
    bodies_by_format, gated_formats = {}, set()
    if cfg.render_pdfs or cfg.allow_gated:
        needed: dict[str, list[str]] = {}
        for r in rows:
            needed.setdefault(r["format"], []).append(r["linked_item_codename"])
        bodies_by_format, gated_formats = content_collector.fetch_all_bodies(client, ticket_code, cfg.formats, needed)
        if gated_formats:
            logger.warning(
                "some formats are access-gated and will be catalogued (URL/metadata) but not downloaded",
                extra={"stage": "gated_formats", "formats": sorted(gated_formats)},
            )

    master = MasterMetadata(storage, f"{cfg.congress_slug}/master_metadata.jsonl")
    rendered, skipped_unchanged, gated_skipped, errors = 0, 0, 0, 0

    for row in rows:
        fmt = row["format"]
        body_elements = bodies_by_format.get(fmt, {}).get(row["linked_item_codename"])
        record = dict(row)

        if fmt in gated_formats:
            record["content_status"] = "gated"
        elif body_elements is None:
            record["content_status"] = "not_fetched"
        elif not content_collector.is_public(body_elements):
            record["content_status"] = "gated"
            record["accessibility"] = [t["codename"] for t in body_elements.get("security__accessibility_level", {}).get("value", [])]
        else:
            record["content_status"] = "public"

        status = master.upsert(record, run_id)

        if cfg.render_pdfs and record["content_status"] == "public":
            pdf_path = f"{run_root}/pdfs/{fmt}/{safe_filename(str(row.get('abstract_code') or row['presentation_codename']) + '_' + str(row.get('title') or ''))}.pdf"
            if status == "unchanged" and master.records[row["codename"]].get("local_pdf_path") and storage.exists(master.records[row["codename"]]["local_pdf_path"]):
                skipped_unchanged += 1
                logger.debug("skipping unchanged, already rendered", extra={"stage": "render_skip", "codename": row["codename"]})
            else:
                try:
                    pdf_bytes = render_pdf_bytes(
                        title=row.get("title"), citation=row.get("citation"),
                        authors=body_elements.get("authors_block", {}).get("value"),
                        affiliations=body_elements.get("authors_affiliations", {}).get("value"),
                        body_html=body_elements.get("content", {}).get("value"),
                    )
                    location = storage.write_bytes(pdf_path, pdf_bytes)
                    master.records[row["codename"]]["local_pdf_path"] = pdf_path
                    master.records[row["codename"]]["storage_uri"] = location
                    rendered += 1
                except Exception as e:
                    errors += 1
                    logger.error("pdf render failed", extra={"stage": "render_error", "codename": row["codename"], "error": str(e)})
        elif record["content_status"] == "gated":
            gated_skipped += 1

    master.save()

    run_summary = {
        "run_id": run_id,
        "congress_slug": cfg.congress_slug,
        "conference_name": conference_name,
        "formats": cfg.formats,
        "rows_collected": len(rows),
        "pdfs_rendered": rendered,
        "pdfs_skipped_unchanged": skipped_unchanged,
        "gated_skipped": gated_skipped,
        "errors": errors,
        "master_status_counts": master.summary(),
        "duration_seconds": round(time.monotonic() - t0, 1),
    }
    storage.write_text(f"{run_root}/run_summary.json", json.dumps(run_summary, indent=2))
    logger.info("run complete", extra={"stage": "run_end", **run_summary})
    print(json.dumps(run_summary, indent=2))


def _write_csv(storage, relative_path: str, rows: list[dict]):
    if not rows:
        return
    buf = io.StringIO()
    fieldnames = sorted({k for r in rows for k in r.keys()})
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    storage.write_text(relative_path, buf.getvalue())


def main():
    ap = argparse.ArgumentParser(prog="esmo-scraper", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_conf = sub.add_parser("list-conferences", help="List every ESMO conference with presentations on the site")
    p_conf.add_argument("--search", default="", help="Filter by substring, case-insensitive")
    p_conf.add_argument("--refresh-conferences", action="store_true", help="Bypass the ~1h local conference-list cache")
    p_conf.set_defaults(func=cmd_list_conferences)

    p_fmt = sub.add_parser("formats", help="Show which formats (abstract/eposter/slides/webcast) have content for a conference")
    p_fmt.add_argument("--congress-search", required=True)
    p_fmt.add_argument("--refresh-conferences", action="store_true", help="Bypass the ~1h local conference-list cache")
    p_fmt.set_defaults(func=cmd_formats)

    p_run = sub.add_parser("run", help="Collect URLs (+ optionally render PDFs) for a conference")
    _add_common_args(p_run)
    p_run.set_defaults(func=cmd_run)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
