"""Tests for the marina sent-contracts CSV log."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Realtime-monitor"))

from send_log import CSV_COLUMNS, SendLog, resolve_send_log_path  # noqa: E402


class SendLogTests(unittest.TestCase):
    def test_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sent_contracts.csv"
            log = SendLog(path)
            log.log_recipients(
                [
                    {"name": "Alice Owner", "email": "alice@example.com"},
                    {"name": "Bob", "email": "bob@example.com"},
                ],
                contract_file="WetSlip_1.pdf",
                document_id="42",
                status="sent",
            )
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(list(rows[0].keys()), list(CSV_COLUMNS))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["customer_email"], "alice@example.com")
            self.assertEqual(rows[0]["contract_file"], "WetSlip_1.pdf")
            self.assertEqual(rows[0]["document_id"], "42")
            self.assertEqual(rows[0]["status"], "sent")
            self.assertEqual(rows[1]["customer_email"], "bob@example.com")

    def test_append_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sent.csv"
            log = SendLog(path)
            log.append_row(
                customer_email="a@example.com",
                contract_file="a.pdf",
                status="sent",
            )
            log.append_row(
                customer_email="b@example.com",
                contract_file="b.pdf",
                status="failed",
                detail="no email",
            )
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["status"], "failed")
            self.assertEqual(rows[1]["detail"], "no email")

    def test_resolve_send_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("watch_directory: .\n", encoding="utf-8")
            self.assertEqual(
                resolve_send_log_path({}, config_path),
                (Path(tmp) / "sent_contracts.csv").resolve(),
            )
            self.assertIsNone(resolve_send_log_path({"send_log_path": "off"}, config_path))
            self.assertEqual(
                resolve_send_log_path({"send_log_path": "logs/out.csv"}, config_path),
                (Path(tmp) / "logs" / "out.csv").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
