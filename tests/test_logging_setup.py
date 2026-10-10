import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vault.logging_setup import log_event, setup_logging


class TestLoggingSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        # each test gets its own logger name to avoid handler reuse across tests
        self.logger = logging.getLogger(f"vault-test-{id(self)}")
        self.logger.handlers.clear()
        self.logger.setLevel(logging.INFO)
        self.log_dir = Path(self.tmp.name)
        handler = logging.FileHandler(self.log_dir / "vault.log")
        from vault.logging_setup import _JsonFormatter

        handler.setFormatter(_JsonFormatter())
        self.logger.addHandler(handler)

    def tearDown(self):
        self.tmp.cleanup()

    def _read_lines(self):
        content = (self.log_dir / "vault.log").read_text()
        return [json.loads(line) for line in content.splitlines() if line]

    def test_log_event_only_contains_whitelisted_fields(self):
        log_event(self.logger, "extract", doc_id="doc1", status="extracted", duration_ms=12.345)
        lines = self._read_lines()
        self.assertEqual(len(lines), 1)
        allowed = {"ts", "level", "stage", "doc_id", "status", "duration_ms", "error_class"}
        self.assertTrue(set(lines[0].keys()) <= allowed)
        self.assertEqual(lines[0]["doc_id"], "doc1")
        self.assertEqual(lines[0]["status"], "extracted")

    def test_log_event_error_reduces_to_class_name_only(self):
        try:
            raise ValueError("this text must never reach the log")
        except ValueError as e:
            log_event(self.logger, "extract", doc_id="doc1", error=e)
        lines = self._read_lines()
        self.assertEqual(lines[0]["error_class"], "ValueError")
        serialized = json.dumps(lines[0])
        self.assertNotIn("this text must never reach the log", serialized)

    def test_setup_logging_creates_log_dir(self):
        fresh_dir = Path(self.tmp.name) / "nested" / "logs"
        logger = setup_logging(fresh_dir)
        self.assertTrue(fresh_dir.exists())
        self.assertIsInstance(logger, logging.Logger)


if __name__ == "__main__":
    unittest.main()
