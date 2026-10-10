# Deploy runbook: laptop -> Redmi Note 7S (Termux)

Run these from a machine that actually has LAN access to the phone (the
build brief assumes a laptop on the same network as `192.168.1.10`). The
cloud session that wrote this code cannot reach that address, so none of
this has been exercised against the real device yet - go through it in
order and report back anything that doesn't match.

Do **not** run `pkg upgrade`, change SSH password auth, or restart the
`llm` tmux session as part of this - those are separate, explicitly-gated
steps in the build brief (sections 4 and 8), not part of getting Phase 0/1
running.

## 0. One-time phone setup (Termux)

```
ssh -p 8022 u0_a351@192.168.1.10
pkg update
pkg install -y python openssh rsync poppler tesseract
tesseract --list-langs        # confirm "eng" is present
python3 --version              # need >= 3.11 (stdlib tomllib)
```

If `python3 --version` is older than 3.11, `pkg install -y python` again
after `pkg update` usually pulls the current Termux build. If `hin`/`mar`
language data matters to you, `pkg search tesseract` for the language
subpackages Termux currently ships and install what you need - the
preflight script below reports what's missing either way.

Exit back to the laptop (`exit` or Ctrl-D) before continuing.

## 1. Sync the code over

From the laptop, in this repo's root:

```
rsync -avz --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  -e "ssh -p 8022" \
  ./ u0_a351@192.168.1.10:~/vault-app/
```

This never touches `~/vault/` on the phone - only `~/vault-app/`. Re-run
this same command after every code change; it's idempotent.

## 2. Run preflight

```
ssh -p 8022 u0_a351@192.168.1.10 "python3 ~/vault-app/scripts/preflight.py"
```

Expect a PASS/FAIL table for: python version, sqlite FTS5, pdftotext,
pdftoppm, pdfinfo, tesseract, tesseract languages, llama-server `/health`,
free RAM, free disk. The script will try `pkg install -y poppler tesseract`
itself if either binary is missing. **Nothing below this line should be run
until every row says PASS.** If `llama_server_health` fails, that's
expected if the `llm` tmux session isn't running yet or llama-server
hasn't finished loading the model - everything else in Phase 0/1 works
without it; it only matters starting Phase 3.

If it fails and you can't tell why from the DETAIL column, paste the exact
table output back (it will not contain anything from inside `~/vault/`).

## 3. Initialise the vault layout

```
ssh -p 8022 u0_a351@192.168.1.10 "python3 -m vault.cli init" 2>&1
```

Actually run it with the module path set, since there's no installed
package yet:

```
ssh -p 8022 u0_a351@192.168.1.10 \
  "cd ~/vault-app && PYTHONPATH=. python3 -m vault.cli --config ~/vault/config.toml init"
```

This creates `~/vault/{inbox,store,text,redacted,db,logs}` (each `chmod
700`), `~/vault/config.toml` with a freshly generated API token, and an
empty `~/vault/names.txt`. **Copy the printed token somewhere safe now** -
it is not shown again (you can read it later directly from
`~/vault/config.toml` on the phone, but that file is inside the opaque
`~/vault/` tree this session will never read for you).

Optionally make `vault` callable directly:

```
ssh -p 8022 u0_a351@192.168.1.10 "chmod +x ~/vault-app/bin/vault && ln -sf ~/vault-app/bin/vault \$PREFIX/bin/vault"
```

From here on, replace the `PYTHONPATH=... python3 -m vault.cli` prefix
below with plain `vault` if you did this.

## 4. Phase 1 acceptance check - using synthetic fixtures only

The build brief requires testing only against synthetic fixtures, never
real documents. This repo's `tests/fixtures/` already contains fabricated
ones (fake names, fake PAN/Aadhaar-shaped numbers, fake lab values) - copy
those into the real inbox for this one check, then remove them again.

```
ssh -p 8022 u0_a351@192.168.1.10 bash -s <<'EOF'
set -e
cd ~/vault-app
cp tests/fixtures/digital.pdf        ~/vault/inbox/fixture-digital.pdf
cp tests/fixtures/scanned_trigger.pdf ~/vault/inbox/fixture-scanned.pdf
cp tests/fixtures/sample.png         ~/vault/inbox/fixture-image.png
cp tests/fixtures/sample.txt         ~/vault/inbox/fixture-text.txt
cp tests/fixtures/unsupported.xyz    ~/vault/inbox/fixture-unsupported.xyz
PYTHONPATH=. python3 -m vault.cli --config ~/vault/config.toml ingest-now --report-rss
PYTHONPATH=. python3 -m vault.cli --config ~/vault/config.toml status
PYTHONPATH=. python3 -m vault.cli --config ~/vault/config.toml search HAEMOGLOBIN
PYTHONPATH=. python3 -m vault.cli --config ~/vault/config.toml search "INTEREST CERTIFICATE"
EOF
```

Expect:
- `status` shows `extracted` for the pdf/png/txt fixtures (the "scanned"
  one takes longer - it goes through OCR - rerun `ingest-now` if it's
  still `new` right after the first pass).
- The `unsupported` fixture shows status `unsupported` and is still sitting
  in `~/vault/inbox/fixture-unsupported.xyz` (never moved).
- Both `search` calls return at least one row with a highlighted snippet.
- `peak RSS` printed by `--report-rss` is well under 150 MB.

Then clean the fixtures back out so they don't linger as fake "documents"
in the real vault. If `~/vault` has no real documents in it yet (i.e. you
just did step 3 and this is the first thing you dropped in), the simplest
clean slate is to wipe and recreate the DB and store/text dirs:

```
ssh -p 8022 u0_a351@192.168.1.10 \
  "rm -rf ~/vault/db ~/vault/store ~/vault/text ~/vault/inbox/fixture-unsupported.xyz && mkdir -p ~/vault/db ~/vault/store ~/vault/text && chmod 700 ~/vault/db ~/vault/store ~/vault/text"
```

If you've already started dropping real documents in before running this
check, don't wipe the whole tree - instead remove just the five fixture
rows by doc_id (the `status` output from above lists them) and delete
their files under `store/<year>/<doc_id>.*` and `text/<doc_id>.txt`
individually.

## 5. Run the unit test suite on the phone too (optional but cheap)

```
ssh -p 8022 u0_a351@192.168.1.10 \
  "cd ~/vault-app && PYTHONPATH=. python3 -m unittest discover -s tests -v"
```

This exercises the mocked pdf/image extraction branches for real on the
target Python/sqlite build, not just in the cloud sandbox that wrote them.

## What's still open after this

- The daemon loop (`vault/daemon.py:run_loop`) isn't wired to a persistent
  process yet (tmux session `vault`, Termux:Boot) - that's Phase 5. Right
  now only the manual `ingest-now` path has been exercised.
- Phases 2-5 (redactor, tagger, API/UI, backup) aren't built yet.

Report back: the preflight table, the `status`/`search`/`--report-rss`
output from step 4, and anything that failed or looked wrong.
