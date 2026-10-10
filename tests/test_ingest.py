import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vault import db, ingest

FIXTURES = Path(__file__).parent / "fixtures"


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox"
        self.store = self.root / "store"
        self.inbox.mkdir()
        self.store.mkdir()
        self.conn = db.connect(self.root / "db" / "vault.sqlite")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _drop_in_inbox(self, fixture_name: str, as_name: str | None = None) -> Path:
        dest = self.inbox / (as_name or fixture_name)
        shutil.copy(FIXTURES / fixture_name, dest)
        return dest

    def test_make_doc_id_is_unique_and_sha_suffixed(self):
        id1 = ingest.make_doc_id("abcdef1234567890")
        id2 = ingest.make_doc_id("abcdef1234567890")
        self.assertTrue(id1.endswith("-abcdef12"))
        # timestamps include milliseconds, but to be safe assert the format
        self.assertRegex(id1, r"^\d{8}T\d{9}Z-[0-9a-f]{8}$")

    def test_sha256_of_matches_hashlib(self):
        import hashlib

        p = FIXTURES / "sample.txt"
        expected = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(ingest.sha256_of(p), expected)

    def test_stability_tracker_requires_two_stable_polls(self):
        tracker = ingest.StabilityTracker(stable_polls=2)
        f = self.inbox / "growing.txt"
        f.write_text("a")
        self.assertEqual(tracker.poll(self.inbox), [])  # count=1, not stable yet
        f.write_text("ab")  # size changed between polls
        self.assertEqual(tracker.poll(self.inbox), [])  # count resets to 1
        self.assertEqual(tracker.poll(self.inbox), [f])  # unchanged -> count=2, stable

    def test_ingest_one_supported_file_moves_to_store(self):
        path = self._drop_in_inbox("sample.txt")
        result = ingest.ingest_one(self.conn, path, self.store)
        self.assertEqual(result.outcome, "new")
        self.assertFalse(path.exists())
        row = db.get_doc(self.conn, result.doc_id)
        self.assertEqual(row["status"], "new")
        self.assertTrue(Path(row["store_path"]).exists())

    def test_ingest_one_unsupported_stays_in_place(self):
        path = self._drop_in_inbox("unsupported.xyz")
        result = ingest.ingest_one(self.conn, path, self.store)
        self.assertEqual(result.outcome, "unsupported")
        self.assertTrue(path.exists())  # never moved
        row = db.get_doc(self.conn, result.doc_id)
        self.assertEqual(row["status"], "unsupported")

    def test_duplicate_content_is_skipped_and_left_in_place(self):
        first = self._drop_in_inbox("sample.txt", as_name="first.txt")
        first_result = ingest.ingest_one(self.conn, first, self.store)
        self.assertEqual(first_result.outcome, "new")

        dup = self._drop_in_inbox("duplicate_of_sample.txt", as_name="second.txt")
        dup_result = ingest.ingest_one(self.conn, dup, self.store)
        self.assertEqual(dup_result.outcome, "duplicate")
        self.assertEqual(dup_result.doc_id, first_result.doc_id)
        self.assertTrue(dup.exists())  # duplicate file is never deleted

        counts = db.status_counts(self.conn)
        self.assertEqual(counts["new"], 1)  # only one row, not two

    def test_ingest_pass_end_to_end(self):
        tracker = ingest.StabilityTracker(stable_polls=2)
        self._drop_in_inbox("sample.txt")
        self._drop_in_inbox("unsupported.xyz")

        self.assertEqual(ingest.ingest_pass(self.conn, tracker, self.inbox, self.store), [])
        results = ingest.ingest_pass(self.conn, tracker, self.inbox, self.store)
        outcomes = sorted(r.outcome for r in results)
        self.assertEqual(outcomes, ["new", "unsupported"])


if __name__ == "__main__":
    unittest.main()
