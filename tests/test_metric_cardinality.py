"""Repository-native tests for the metric-cardinality analyzer (README contract)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(APP_ROOT, "metric_cardinality.py")


def run_cli(data_bytes, suffix=".jsonl"):
    """Write data to a temp file outside the repo and run the CLI."""
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=suffix, prefix="mca-", delete=False
    ) as handle:
        handle.write(data_bytes)
        path = handle.name
    try:
        proc = subprocess.run(
            [sys.executable, CLI, path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc
    finally:
        os.unlink(path)


def lines(*objs):
    return ("\n".join(json.dumps(o) for o in objs) + "\n").encode("utf-8")


def rec(metric, labels, value=1.0, timestamp=1700000000000, extra=None):
    obj = {"metric": metric, "labels": labels, "value": value, "timestamp": timestamp}
    if extra:
        obj.update(extra)
    return obj


class TestMetricCardinality(unittest.TestCase):
    def test_ranking_counts_and_duplicates(self):
        data = lines(
            rec("api_calls", {"pod": "a"}),
            rec("api_calls", {"pod": "a"}),  # duplicate series: samples+1 only
            rec("api_calls", {"pod": "b"}),
            rec("db_queries", {"host": "h1"}),
        )
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("api_calls samples=3 series=2", out)
        self.assertIn("db_queries samples=1 series=1", out)
        self.assertLess(out.index("api_calls"), out.index("db_queries"))

    def test_label_key_order_insensitive(self):
        data = lines(
            rec("m", {"a": "1", "b": "2"}),
            rec("m", {"b": "2", "a": "1"}),
        )
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("m samples=2 series=1", proc.stdout.decode("utf-8"))

    def test_byte_identity_and_tie_break(self):
        # "M" and "m" are distinct metrics; tie on series broken byte-wise
        # ("Zebra" < "apple" because uppercase bytes sort first).
        data = lines(
            rec("apple", {"k": "1"}),
            rec("Zebra", {"k": "1"}),
            rec("M", {"k": "1"}),
            rec("m", {"k": "1"}),
        )
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("M samples=1 series=1", out)
        self.assertIn("m samples=1 series=1", out)
        self.assertLess(out.index("M samples"), out.index("m samples"))
        self.assertLess(out.index("Zebra"), out.index("apple"))

    def test_action_drop_when_every_series_distinct(self):
        data = lines(
            rec("m", {"pod": "a"}),
            rec("m", {"pod": "b"}),
            rec("m", {"pod": "c"}),
        )
        proc = run_cli(data)
        out = proc.stdout.decode("utf-8")
        self.assertEqual(out.count("Recommendation:"), 1)
        self.assertIn("Recommendation: drop `pod` on `m` (series=3, values=3).", out)

    def test_action_restrict(self):
        data = lines(
            rec("m", {"pod": "a", "z": "1"}),
            rec("m", {"pod": "a", "z": "2"}),
            rec("m", {"pod": "b", "z": "1"}),
            rec("m", {"pod": "c", "z": "2"}),
        )
        out = run_cli(data).stdout.decode("utf-8")
        self.assertIn(
            "Recommendation: restrict values of `pod` on `m` (series=4, values=3).",
            out,
        )

    def test_action_aggregate_away_single_series(self):
        data = lines(rec("m", {"az": "1"}), rec("m", {"az": "1"}))
        out = run_cli(data).stdout.decode("utf-8")
        self.assertIn("aggregate away `az` on `m` (series=1, values=1).", out)

    def test_no_label_keys_exact_templates(self):
        data = lines(rec("lonely", {}), rec("lonely", {}))
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("lonely has no label keys.", out)
        self.assertIn(
            "Recommendation: lonely has no labels (series=1); "
            "aggregate away lonely.",
            out,
        )
        self.assertEqual(out.count("Recommendation:"), 1)

    def test_empty_file_no_data(self):
        proc = run_cli(b"")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("Recommendation: no data was available (skipped 0).", out)
        self.assertIn("Skipped lines: 0", out)
        self.assertEqual(out.count("Recommendation:"), 1)

    def test_all_blank_file_no_data(self):
        proc = run_cli(b"   \n\t\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("Recommendation: no data was available (skipped 0).", out)

    def test_all_malformed_names_skipped(self):
        data = b"not json\n" + lines(rec("m", {"k": "v"}))[:0] + b"{}\n"
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("Recommendation: no valid telemetry was found (skipped 2).", out)
        self.assertIn("Skipped lines: 2", out)

    def test_blank_lines_ignored_and_trailing_newline(self):
        core = lines(rec("m", {"k": "1"}), rec("m", {"k": "2"}))
        with_newline = b"\n" + core + b"   \n"
        without_newline = b"\n" + core.rstrip(b"\n") + b"   "
        out_with = run_cli(with_newline).stdout
        out_without = run_cli(without_newline).stdout
        self.assertEqual(out_with, out_without)
        self.assertIn(b"Skipped lines: 0", out_with)
        self.assertIn(b"m samples=2 series=2", out_with)

    def test_extra_top_level_fields_ignored(self):
        data = lines(rec("m", {"k": "1"}, extra={"region": "us", "debug": [1, 2]}))
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("m samples=1 series=1", proc.stdout.decode("utf-8"))

    def test_malformed_lines_skipped_and_counted(self):
        good = rec("m", {"k": "1"})
        bad = [
            '{"metric": "m", "labels": {"k": "1"}, "value": 1.0, ',  # invalid JSON
            json.dumps({"metric": "m", "labels": {"k": "1"}, "value": 1.0}),  # no ts
            json.dumps(
                {"metric": "", "labels": {}, "value": 1.0, "timestamp": 1}
            ),  # empty metric
            json.dumps(
                {"metric": "m", "labels": {"k": 5}, "value": 1.0, "timestamp": 1}
            ),  # non-string label value
            json.dumps(
                {"metric": "m", "labels": {}, "value": float("inf"), "timestamp": 1}
            ),  # non-finite value
            json.dumps(
                {"metric": "m", "labels": {}, "value": 1.0, "timestamp": 1.5}
            ),  # non-integer timestamp
            json.dumps(
                {"metric": "m", "labels": {}, "value": True, "timestamp": 1}
            ),  # bool value
        ]
        payload = ("\n".join([json.dumps(good)] + bad) + "\n").encode("utf-8")
        proc = run_cli(payload)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("m samples=1 series=1", out)
        self.assertIn("Skipped lines: 7", out)

    def test_label_values_opaque(self):
        data = lines(rec("m", {"v": "01"}), rec("m", {"v": "1"}))
        out = run_cli(data).stdout.decode("utf-8")
        self.assertIn("m samples=2 series=2", out)

    def test_missing_file_nonzero_one_line_stderr(self):
        missing = os.path.join(
            tempfile.gettempdir(), "mca-does-not-exist-12345.jsonl"
        )
        if os.path.exists(missing):
            os.unlink(missing)
        proc = subprocess.run(
            [sys.executable, CLI, missing],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(proc.returncode, 0)
        err = proc.stderr.decode("utf-8")
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_determinism_byte_identical(self):
        data = lines(
            rec("b", {"k": "2"}),
            rec("a", {"k": "1", "j": "x"}),
            rec("b", {"k": "1"}),
        )
        first = run_cli(data).stdout
        second = run_cli(data).stdout
        self.assertEqual(first, second)

    def test_top_metric_label_breakdown_tie_order(self):
        # Two label keys tied on distinct-value count: byte-smaller key first.
        data = lines(
            rec("m", {"a": "1", "b": "1"}),
            rec("m", {"a": "2", "b": "2"}),
        )
        proc = run_cli(data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("m samples=2 series=2", out)
        self.assertIn("a values=2", out)
        self.assertIn("b values=2", out)
        self.assertLess(out.index("a values=2"), out.index("b values=2"))
        self.assertIn(
            "Recommendation: drop `a` on `m` (series=2, values=2).", out
        )

    def test_label_key_value_byte_identity(self):
        # Label keys differing only by case are distinct; values differing
        # only by surrounding whitespace are distinct (no folding/trimming).
        key_data = lines(rec("m", {"A": "1"}), rec("m", {"a": "1"}))
        proc = run_cli(key_data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("m samples=2 series=2", out)
        self.assertIn("A values=1", out)
        self.assertIn("a values=1", out)
        self.assertLess(out.index("A values=1"), out.index("a values=1"))
        val_data = lines(rec("m", {"k": "x"}), rec("m", {"k": " x"}))
        proc = run_cli(val_data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.decode("utf-8")
        self.assertIn("m samples=2 series=2", out)
        self.assertIn("k values=2", out)

    def test_observable_shape_and_section_order(self):
        data = lines(
            rec("top", {"b": "1"}),
            rec("top", {"b": "2"}),
            rec("other", {"z": "9"}),
            "oops",
        )
        proc = run_cli(data)
        out = proc.stdout.decode("utf-8")
        self.assertEqual(out.count("Recommendation:"), 1)
        idx_metric = out.index("top samples=2 series=2")
        idx_breakdown = out.index("b values=2")
        idx_skipped = out.index("Skipped lines: 1")
        idx_rec = out.index("Recommendation:")
        self.assertLess(idx_metric, idx_breakdown)
        self.assertLess(idx_breakdown, idx_skipped)
        self.assertLess(idx_skipped, idx_rec)


if __name__ == "__main__":
    unittest.main()
