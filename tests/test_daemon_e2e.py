"""End-to-end Phase 1 pipeline test using only the .txt fixture, which needs
no external OCR/PDF tools - so it runs for real in this sandbox, unlike the
pdf/image paths which are unit-tested with mocks in test_extract.py. This is
the closest thing to the brief's Phase 1 acceptance criteria that can run
here; the pdf/jpg/locked/duplicate cases still need the on-device run
described in RUNBOOK.md.
"""
import logging
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vault import daemon, db, ingest
from vault.config import Config, VaultPaths

FIXTURES = Path(__file__).parent / "fixtures"


class TestDaemonEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name) / "vault"
        self.paths = VaultPaths.from_root(root)
        for d in self.paths.all_dirs():
            d.mkdir(parents=True)
        self.cfg = Config(paths=self.paths)
        self.conn = db.connect(self.paths.db_file)
        self.logger = logging.getLogger(f"vault-e2e-{id(self)}")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())
        self.tracker = ingest.StabilityTracker(stable_polls=2)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_txt_document_is_ingested_extracted_and_searchable(self):
        shutil.copy(FIXTURES / "sample.txt", self.paths.inbox / "report.txt")

        # stability requires two unchanged polls before a doc_id is assigned
        counts1 = daemon.run_once(self.conn, self.cfg, self.logger, self.tracker)
        self.assertEqual(counts1["new"], 0)

        counts2 = daemon.run_once(self.conn, self.cfg, self.logger, self.tracker)
        self.assertEqual(counts2["new"], 1)
        self.assertEqual(counts2["extracted"], 1)

        results = db.search(self.conn, "HAEMOGLOBIN")
        self.assertEqual(len(results), 1)
        doc_id = results[0]["id"]

        row = db.get_doc(self.conn, doc_id)
        self.assertEqual(row["status"], "extracted")
        text_path = self.paths.text / f"{doc_id}.txt"
        self.assertTrue(text_path.exists())
        self.assertIn("HAEMOGLOBIN", text_path.read_text())

    def test_unsupported_file_never_moved_and_never_extracted(self):
        shutil.copy(FIXTURES / "unsupported.xyz", self.paths.inbox / "weird.xyz")
        self.tracker.poll(self.paths.inbox)
        counts = daemon.run_once(self.conn, self.cfg, self.logger, self.tracker)
        self.assertEqual(counts["unsupported"], 1)
        self.assertTrue((self.paths.inbox / "weird.xyz").exists())


if __name__ == "__main__":
    unittest.main()
