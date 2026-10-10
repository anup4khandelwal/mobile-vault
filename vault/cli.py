"""The `vault` command-line tool. Phases 2/3/5 commands (redact, tag-now,
backup) are stubbed until those phases are built."""
from __future__ import annotations

import argparse
import sys
import time

from vault import daemon, db, ingest
from vault.config import init_vault_layout, load_config
from vault.logging_setup import setup_logging

DEFAULT_CONFIG_PATH = "~/vault/config.toml"

NOT_YET_IMPLEMENTED = {
    "redact": "Phase 2 (redactor)",
    "unredact": "Phase 2 (redactor)",
    "tag-now": "Phase 3 (tagger)",
    "backup": "Phase 5 (persistence and backup)",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="path to config.toml"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create ~/vault layout, config.toml, names.txt")
    p_ingest = sub.add_parser("ingest-now", help="run one ingest+extract+index pass immediately")
    p_ingest.add_argument(
        "--report-rss",
        action="store_true",
        help="print peak RSS of this process after the pass (Phase 1 acceptance check)",
    )

    p_search = sub.add_parser("search", help="full-text search")
    p_search.add_argument("query")
    p_search.add_argument("--type", dest="doc_type", default=None)
    p_search.add_argument("--person", default=None)
    p_search.add_argument("--from", dest="date_from", default=None)
    p_search.add_argument("--to", dest="date_to", default=None)
    p_search.add_argument("--limit", type=int, default=20)

    sub.add_parser("status", help="counts of documents by status")

    for name in NOT_YET_IMPLEMENTED:
        sub.add_parser(name, help="(not yet implemented)")

    return parser


def cmd_init(args) -> int:
    vault_dir = "~/vault"
    try:
        cfg = load_config(args.config)
        vault_dir = str(cfg.paths.root)
    except FileNotFoundError:
        pass
    paths, token = init_vault_layout(vault_dir)
    print(f"vault layout ready at {paths.root}")
    if token:
        print(f"API token (save this now, it will not be shown again): {token}")
    else:
        print("config.toml already existed - token unchanged")
    return 0


def cmd_ingest_now(args) -> int:
    cfg = load_config(args.config)
    logger = setup_logging(cfg.paths.logs)
    conn = db.connect(cfg.paths.db_file)
    tracker = ingest.StabilityTracker(stable_polls=cfg.stable_polls)
    # Two quick polls so a manual run still honours the "stable size" guard
    # against a file mid-copy, without waiting out the full 60s loop.
    tracker.poll(cfg.paths.inbox)
    time.sleep(1)
    counts = daemon.run_once(conn, cfg, logger, tracker)
    print(
        f"new={counts['new']} duplicate={counts['duplicate']} "
        f"unsupported={counts['unsupported']} extracted={counts['extracted']}"
    )
    if args.report_rss:
        import resource

        peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(f"peak RSS: {peak_kb / 1024:.1f} MB")
    return 0


def cmd_search(args) -> int:
    cfg = load_config(args.config)
    conn = db.connect(cfg.paths.db_file)
    rows = db.search(
        conn,
        args.query,
        doc_type=args.doc_type,
        person=args.person,
        date_from=args.date_from,
        date_to=args.date_to,
        limit=args.limit,
    )
    if not rows:
        print("no matches")
        return 0
    for r in rows:
        print(f"{r['id']}  [{r['doc_type'] or '-'}]  {r['doc_date'] or '-'}  {r['snippet']}")
    return 0


def cmd_status(args) -> int:
    cfg = load_config(args.config)
    conn = db.connect(cfg.paths.db_file)
    counts = db.status_counts(conn)
    if not counts:
        print("no documents yet")
        return 0
    for status, n in sorted(counts.items()):
        print(f"{status}: {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd in NOT_YET_IMPLEMENTED:
        print(f"'{args.cmd}' lands in {NOT_YET_IMPLEMENTED[args.cmd]} - not implemented yet.")
        return 1

    handlers = {
        "init": cmd_init,
        "ingest-now": cmd_ingest_now,
        "search": cmd_search,
        "status": cmd_status,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
