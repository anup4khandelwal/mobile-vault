"""Ties ingest + extract + index into one pass, used by the 60s loop and by
`vault ingest-now`. Processes one document at a time - no thread pools."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from vault import db, extract, ingest
from vault.config import Config
from vault.logging_setup import log_event


def process_one_new_doc(conn, cfg: Config, logger: logging.Logger, row) -> None:
    doc_id = row["id"]
    path = Path(row["store_path"])
    ext = row["original_ext"]
    started = time.monotonic()
    try:
        text, pages = extract.extract_document(
            path,
            ext,
            min_chars_per_page=cfg.min_chars_per_page,
            langs=cfg.ocr_langs,
            dpi=cfg.rasterize_dpi,
        )
    except extract.LockedPdfError:
        db.update_status(conn, doc_id, "locked")
        log_event(logger, "extract", doc_id=doc_id, status="locked")
        return
    except Exception as e:
        db.update_status(conn, doc_id, "extract_failed")
        log_event(logger, "extract", doc_id=doc_id, status="extract_failed", error=e)
        return

    text_path = cfg.paths.text / f"{doc_id}.txt"
    text_path.write_text(text)
    text_path.chmod(0o600)
    db.set_extracted(conn, doc_id, pages, text)
    duration_ms = (time.monotonic() - started) * 1000
    log_event(logger, "extract", doc_id=doc_id, status="extracted", duration_ms=duration_ms)


def run_once(conn, cfg: Config, logger: logging.Logger, tracker: ingest.StabilityTracker) -> dict:
    """One ingest+extract pass. Returns counts for `vault ingest-now` to print."""
    counts = {"new": 0, "duplicate": 0, "unsupported": 0, "extracted": 0}

    for result in ingest.ingest_pass(conn, tracker, cfg.paths.inbox, cfg.paths.store):
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
        log_event(logger, "ingest", doc_id=result.doc_id, status=result.outcome)

    for row in db.get_docs_by_status(conn, "new"):
        process_one_new_doc(conn, cfg, logger, row)
        counts["extracted"] += 1

    return counts


def run_loop(conn, cfg: Config, logger: logging.Logger) -> None:
    tracker = ingest.StabilityTracker(stable_polls=cfg.stable_polls)
    while True:
        run_once(conn, cfg, logger, tracker)
        time.sleep(cfg.poll_interval_s)
