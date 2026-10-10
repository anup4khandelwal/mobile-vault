# mobile-vault

A private, LAN-only household document vault running on an Android phone
(Termux). Documents never leave the phone; only redacted text the owner has
previewed may be copied out by hand. Full design brief: see the project
build brief supplied alongside this repo.

## Status

- **Phase 0 (Preflight):** done - `scripts/preflight.py`.
- **Phase 1 (Ingest, extract, search, no LLM):** done - `vault/ingest.py`,
  `vault/extract.py`, `vault/db.py`, `vault/daemon.py`, `vault/cli.py`.
- **Phase 2 (Redactor):** not started.
- **Phase 3 (Tagger):** not started.
- **Phase 4 (API and UI):** not started.
- **Phase 5 (Persistence and backup):** not started.

This code was written and unit-tested in a cloud sandbox with no access to
the phone's LAN. **It has not yet been run on the actual device.** See
`RUNBOOK.md` for the exact commands to deploy and verify it there.

## Layout

```
vault/            application code (this is what deploys to ~/vault-app/)
  config.py       config.toml loading, ~/vault layout creation
  db.py           SQLite + FTS5 schema, CRUD, search
  ingest.py       inbox polling, SHA-256 dedup, doc_id assignment, filing
  extract.py      pdftotext/pdftoppm/tesseract orchestration, OCR fallback
  daemon.py       ties ingest+extract+index into one pass / loop
  cli.py          `vault` command: init, ingest-now, search, status
  logging_setup.py  structured logging that cannot carry document content
scripts/
  preflight.py    Phase 0 checks, run once on the phone before anything else
bin/vault         shell wrapper so `vault <cmd>` works without -m vault.cli
tests/
  fixtures/       synthetic, fabricated fixtures (fake names/PAN/Aadhaar/labs)
  test_*.py       unittest suite, stdlib only (no pytest needed)
```

## Running the tests

```
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

No external tools (pdftotext/tesseract) are required to run the suite - the
PDF/image extraction subprocess boundary is mocked; only the `.txt` pipeline
runs fully end to end, since it needs no external binary. See
`tests/test_extract.py` and `tests/test_daemon_e2e.py` for what's covered
versus what still needs on-device verification per `RUNBOOK.md`.

## Deploying to the phone

See `RUNBOOK.md`.
