#!/usr/bin/env python3
"""Metric-cardinality analyzer.

Reads one generated telemetry file in JSON Lines format and writes a
human-readable cardinality report to stdout (requirements contract in
README.md). Pure standard library; deterministic output.
"""

import json
import math
import sys


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_record(obj):
    """Return (metric, labels) if obj is a valid telemetry line, else None."""
    if not isinstance(obj, dict):
        return None
    if "metric" not in obj or "labels" not in obj:
        return None
    if "value" not in obj or "timestamp" not in obj:
        return None
    metric = obj["metric"]
    labels = obj["labels"]
    value = obj["value"]
    timestamp = obj["timestamp"]
    if not isinstance(metric, str) or metric == "":
        return None
    if not isinstance(labels, dict):
        return None
    for key, val in labels.items():
        if not isinstance(key, str) or not isinstance(val, str):
            return None
    if not _is_number(value):
        return None
    try:
        if not math.isfinite(value):
            return None
    except TypeError:
        return None
    if not _is_int(timestamp):
        return None
    return metric, labels


def analyze_bytes(data):
    """Analyze raw file bytes.

    Returns (metrics, skipped, has_nonblank) where metrics maps metric name
    to {'samples': int, 'series': set of label tuples, 'label_values': dict
    of key -> set of values}.
    """
    if data == b"":
        raw_lines = []
    else:
        raw_lines = data.split(b"\n")
        if data.endswith(b"\n"):
            # A trailing newline terminates the last line; it is not an
            # extra line.
            raw_lines.pop()
    metrics = {}
    skipped = 0
    has_nonblank = False
    for raw in raw_lines:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            has_nonblank = True
            skipped += 1
            continue
        if text.strip() == "":
            continue
        has_nonblank = True
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            skipped += 1
            continue
        record = _valid_record(obj)
        if record is None:
            skipped += 1
            continue
        metric, labels = record
        # Canonical series identity: sorted key/value pairs. Python str
        # ordering matches UTF-8 byte ordering, and str equality matches
        # exact byte equality for valid UTF-8, so no normalization occurs.
        series_key = tuple(sorted(labels.items()))
        entry = metrics.get(metric)
        if entry is None:
            entry = {"samples": 0, "series": set(), "label_values": {}}
            metrics[metric] = entry
        entry["samples"] += 1
        entry["series"].add(series_key)
        for key, val in labels.items():
            entry["label_values"].setdefault(key, set()).add(val)
    return metrics, skipped, has_nonblank


def _rank_metrics(metrics):
    series_counts = {name: len(entry["series"]) for name, entry in metrics.items()}
    # Series descending, then metric name ascending (byte-wise).
    return sorted(metrics, key=lambda name: (-series_counts[name], name))


def _recommend(top, series_count, ranked_keys, label_values):
    if not ranked_keys:
        return (
            "%s has no label keys." % top,
            "Recommendation: %s has no labels (series=%d); aggregate away %s."
            % (top, series_count, top),
        )
    key = ranked_keys[0]
    distinct = len(label_values[key])
    if series_count == 1:
        action = "aggregate away"
    elif distinct == series_count:
        action = "drop"
    else:
        action = "restrict values of"
    breakdown = ["%s values=%d" % (key, len(label_values[key])) for key in ranked_keys]
    recommendation = (
        "Recommendation: %s `%s` on `%s` (series=%d, values=%d)."
        % (action, key, top, series_count, distinct)
    )
    return breakdown, recommendation


def render(metrics, skipped, has_nonblank):
    lines = []
    lines.append("Metrics (ranked by series):")
    ranked = _rank_metrics(metrics)
    series_counts = {name: len(metrics[name]["series"]) for name in ranked}
    for name in ranked:
        lines.append(
            "%s samples=%d series=%d"
            % (name, metrics[name]["samples"], series_counts[name])
        )
    if not ranked:
        lines.append("Skipped lines: %d" % skipped)
        if not has_nonblank:
            lines.append("Recommendation: no data was available (skipped 0).")
        else:
            lines.append(
                "Recommendation: no valid telemetry was found (skipped %d)."
                % skipped
            )
        return "\n".join(lines) + "\n"
    top = ranked[0]
    series_count = series_counts[top]
    label_values = metrics[top]["label_values"]
    # Label keys by distinct-value count descending, then key ascending.
    ranked_keys = sorted(label_values, key=lambda k: (-len(label_values[k]), k))
    lines.append("Top metric %s label breakdown:" % top)
    breakdown, recommendation = _recommend(top, series_count, ranked_keys, label_values)
    if isinstance(breakdown, list):
        lines.extend(breakdown)
    else:
        lines.append(breakdown)
    lines.append("Skipped lines: %d" % skipped)
    lines.append(recommendation)
    return "\n".join(lines) + "\n"


def run_file(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        message = "Error: cannot read input file '%s': %s" % (path, exc)
        sys.stderr.write(" ".join(message.splitlines()) + "\n")
        return 1
    metrics, skipped, has_nonblank = analyze_bytes(data)
    sys.stdout.write(render(metrics, skipped, has_nonblank))
    return 0


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("Usage: metric_cardinality.py <input-file>\n")
        return 2
    return run_file(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
