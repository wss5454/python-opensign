"""Dealer ID routing: who downloads a finished contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Realtime-monitor"))

from app.ws import document_finished_payload  # noqa: E402
from custom_client import (  # noqa: E402
    should_download_for_dealer,
    store_directory_for_event,
)


class DealerDownloadTests(unittest.TestCase):
    def test_configured_id_matches_only_itself(self):
        self.assertTrue(should_download_for_dealer("101", "101"))
        self.assertTrue(should_download_for_dealer(" 101 ", "101"))
        self.assertFalse(should_download_for_dealer("101", "202"))
        self.assertFalse(should_download_for_dealer("101", None))
        self.assertFalse(should_download_for_dealer("101", ""))
        self.assertFalse(should_download_for_dealer("101", "  "))

    def test_blank_local_id_downloads_anything(self):
        self.assertTrue(should_download_for_dealer("", "202"))
        self.assertTrue(should_download_for_dealer(None, None))
        self.assertTrue(should_download_for_dealer("  ", "101"))

    def test_leading_zeros_are_significant(self):
        self.assertFalse(should_download_for_dealer("00123", "123"))
        self.assertTrue(should_download_for_dealer("00123", "00123"))


class CompanyRoutingTests(unittest.TestCase):
    def test_routes_signed_file_to_matching_company_folder(self):
        marina = Path("D:/Wallace/Company1/signed")
        storage = Path("D:/Wallace/Company2/signed")
        stores = {"101": marina, "202": storage}
        self.assertEqual(
            store_directory_for_event(
                dealer_stores=stores,
                local_dealer_id="",
                default_store=marina,
                event_dealer_id="202",
            ),
            storage,
        )
        self.assertIsNone(
            store_directory_for_event(
                dealer_stores=stores,
                local_dealer_id="",
                default_store=marina,
                event_dealer_id="303",
            )
        )
        self.assertIsNone(
            store_directory_for_event(
                dealer_stores=stores,
                local_dealer_id="",
                default_store=marina,
                event_dealer_id="",
            )
        )

    def test_single_company_without_id_uses_default_folder(self):
        folder = Path("D:/signed")
        self.assertEqual(
            store_directory_for_event(
                dealer_stores={},
                local_dealer_id="",
                default_store=folder,
                event_dealer_id="999",
            ),
            folder,
        )

    def test_parse_companies_list(self):
        import tempfile

        from monitor import parse_company_specs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch_a = root / "a-out"
            watch_b = root / "b-out"
            watch_a.mkdir()
            watch_b.mkdir()
            config_path = root / "config.yaml"
            companies = parse_company_specs(
                {
                    "companies": [
                        {
                            "name": "Marina",
                            "dealer_id": "101",
                            "watch_directory": str(watch_a),
                            "store_directory": str(root / "a-signed"),
                        },
                        {
                            "name": "Storage",
                            "dealer_id": "202",
                            "watch_directory": str(watch_b),
                            "store_directory": str(root / "b-signed"),
                        },
                    ]
                },
                config_path,
            )
            self.assertEqual([c["dealer_id"] for c in companies], ["101", "202"])
            self.assertEqual(companies[0]["dealership_name"], "Marina")
            self.assertEqual(companies[1]["watch_directory"], watch_b.resolve())
            self.assertTrue((root / "a-signed").is_dir())

    def test_second_company_requires_dealer_id(self):
        import tempfile

        from monitor import parse_company_specs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            with self.assertRaises(ValueError):
                parse_company_specs(
                    {
                        "companies": [
                            {
                                "dealer_id": "101",
                                "watch_directory": str(root / "a"),
                                "store_directory": str(root / "a-signed"),
                            },
                            {
                                "watch_directory": str(root / "b"),
                                "store_directory": str(root / "b-signed"),
                            },
                        ]
                    },
                    root / "config.yaml",
                )


class FinishedPayloadTests(unittest.TestCase):
    def test_includes_dealer_id(self):
        document = SimpleNamespace(
            id=12,
            status="completed",
            title="Contract",
            filename="005086611111_contract.pdf",
            public_token="abc",
            dealer_id=" 101 ",
            completed_at=None,
        )
        payload = document_finished_payload(document)
        self.assertEqual(payload["event"], "document.finished")
        self.assertEqual(payload["document_id"], 12)
        self.assertEqual(payload["dealer_id"], "101")

    def test_blank_dealer_id_is_null(self):
        document = SimpleNamespace(
            id=1,
            status="completed",
            title="Contract",
            filename="a.pdf",
            public_token="abc",
            dealer_id="  ",
            completed_at=None,
        )
        self.assertIsNone(document_finished_payload(document)["dealer_id"])


if __name__ == "__main__":
    unittest.main()
