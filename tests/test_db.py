import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vault import db


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "vault.sqlite")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_fts5_available(self):
        self.assertTrue(db.check_fts5(self.conn))

    def test_wal_mode_enabled(self):
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_insert_and_get_by_sha256(self):
        db.insert_doc(
            self.conn, doc_id="doc1", sha256="abc123", original_ext=".txt", status="new"
        )
        row = db.get_doc_by_sha256(self.conn, "abc123")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "doc1")
        self.assertEqual(row["status"], "new")

    def test_duplicate_sha256_rejected(self):
        db.insert_doc(
            self.conn, doc_id="doc1", sha256="same-hash", original_ext=".txt", status="new"
        )
        with self.assertRaises(Exception):
            db.insert_doc(
                self.conn, doc_id="doc2", sha256="same-hash", original_ext=".txt", status="new"
            )

    def test_set_extracted_and_search_round_trip(self):
        db.insert_doc(
            self.conn, doc_id="doc1", sha256="h1", original_ext=".txt", status="new"
        )
        db.set_extracted(self.conn, "doc1", 1, "INTEREST CERTIFICATE for Rohan Mehta, PAN ABCDE1234F")
        results = db.search(self.conn, "INTEREST CERTIFICATE")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "doc1")

    def test_search_no_match(self):
        db.insert_doc(
            self.conn, doc_id="doc1", sha256="h1", original_ext=".txt", status="new"
        )
        db.set_extracted(self.conn, "doc1", 1, "nothing relevant here")
        results = db.search(self.conn, "zzz_not_present")
        self.assertEqual(results, [])

    def test_search_hyphenated_query_does_not_raise(self):
        db.insert_doc(
            self.conn, doc_id="doc1", sha256="h1", original_ext=".pdf", status="new"
        )
        db.set_extracted(self.conn, "doc1", 1, "Account Number: 123-456-789")
        # FTS5 special characters (hyphens, colons) in the query must not
        # raise a syntax error - they get escaped as literal tokens.
        results = db.search(self.conn, "123-456-789")
        self.assertIsInstance(results, list)

    def test_search_filters_by_doc_type(self):
        db.insert_doc(self.conn, doc_id="doc1", sha256="h1", original_ext=".txt", status="new")
        db.set_extracted(self.conn, "doc1", 1, "lab report haemoglobin")
        db.set_tags(
            self.conn, "doc1", doc_type="lab_report", doc_date="2024-01-01",
            person="Asha Verma", gist="routine checkup", tag_source="llm",
        )
        matched = db.search(self.conn, "haemoglobin", doc_type="lab_report")
        self.assertEqual(len(matched), 1)
        unmatched = db.search(self.conn, "haemoglobin", doc_type="bank_statement")
        self.assertEqual(unmatched, [])

    def test_status_counts(self):
        db.insert_doc(self.conn, doc_id="d1", sha256="h1", original_ext=".txt", status="new")
        db.insert_doc(self.conn, doc_id="d2", sha256="h2", original_ext=".pdf", status="locked")
        db.insert_doc(self.conn, doc_id="d3", sha256="h3", original_ext=".pdf", status="new")
        counts = db.status_counts(self.conn)
        self.assertEqual(counts["new"], 2)
        self.assertEqual(counts["locked"], 1)


if __name__ == "__main__":
    unittest.main()
