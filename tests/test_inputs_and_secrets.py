import builtins
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from product_models import LeadGenRequest
from pydantic import ValidationError
from secret_store import load_jwt_secret
from utils import csv_safe_cell

VALID = dict(category="Plumber", city="Austin", state="TX", target_count=25,
             opportunity_profile="website_conversion")


class InputTests(unittest.TestCase):
    def test_normalization(self):
        req = LeadGenRequest(**{**VALID, "category": "  Roof   Repair ", "city": " New  York ", "state": "new york"})
        self.assertEqual((req.category, req.city, req.state), ("Roof Repair", "New York", "NY"))

    def test_target_boundaries(self):
        for target in (1, 100):
            self.assertEqual(LeadGenRequest(**{**VALID, "target_count": target}).target_count, target)

    def test_invalid_values(self):
        invalid = [("target_count", value) for value in (0, 101, -1, 10**10, "25", 1.2, True)]
        invalid += [("state", "ZZ"), ("state", "Ontario"), ("opportunity_profile", "outreach")]
        invalid += [(field, value) for field in ("category", "city", "state")
                    for value in ("", "  ", "x" * 201, "Bad\nText", "Bad\x00Text", "Bad\u202eText")]
        for field, value in invalid:
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                LeadGenRequest(**{**VALID, field: value})

    def test_missing_and_extra_fields(self):
        for field in VALID:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                LeadGenRequest(**{k: v for k, v in VALID.items() if k != field})
        with self.assertRaises(ValidationError):
            LeadGenRequest(**VALID, country="Canada")

    def test_all_state_names_and_dc(self):
        from product_models import US_STATES
        for name, abbreviation in US_STATES.items():
            self.assertEqual(LeadGenRequest(**{**VALID, "state": name}).state, abbreviation)


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".jwt_secret"

    def test_environment_preferred_without_file(self):
        secret = "environment-fixture-" + "s" * 48
        self.assertEqual(load_jwt_secret(self.path, {"JWT_SECRET": secret}), secret)
        self.assertFalse(self.path.exists())

    def test_generated_and_persisted(self):
        secret = load_jwt_secret(self.path, {})
        self.assertGreaterEqual(len(secret), 80)
        self.assertEqual(load_jwt_secret(self.path, {}), secret)
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_secret(self):
        self.path.write_text("existing-test-secret-" + "x" * 40)
        self.assertEqual(load_jwt_secret(self.path, {}), self.path.read_text())

    def test_concurrent_publication(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: load_jwt_secret(self.path, {}), range(24)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_no_unix_locking_or_secret_output(self):
        original_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "fcntl":
                raise AssertionError("Unix-only module requested")
            return original_import(name, *args, **kwargs)
        output = io.StringIO()
        with patch("builtins.__import__", side_effect=guarded), redirect_stdout(output), redirect_stderr(output):
            secret = load_jwt_secret(self.path, {})
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_invalid_or_unwritable_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_jwt_secret(self.path, {"JWT_SECRET": "short"})
        self.path.write_text("")
        with self.assertRaises(RuntimeError):
            load_jwt_secret(self.path, {})
        with patch("secret_store.os.link", side_effect=PermissionError):
            with self.assertRaises(RuntimeError):
                load_jwt_secret(self.path.parent / "another-secret", {})


class CsvTests(unittest.TestCase):
    def test_formula_markers_and_hidden_prefixes(self):
        for value in ('=HYPERLINK("https://example.org")', '+SUM(1,2)', '-1+2', '@SUM(1)',
                      ' \t=1', '\r\n+1', '\ufeff@cmd', '\x00=1', '\u00a0+1', '\tordinary text'):
            with self.subTest(value=value):
                self.assertEqual(csv_safe_cell(value), "'" + value)

    def test_ordinary_values_and_types(self):
        for value in ('Plumber & Sons', 'info@example.org', "'already escaped", '123', 12, -2, None):
            self.assertEqual(csv_safe_cell(value), value)
