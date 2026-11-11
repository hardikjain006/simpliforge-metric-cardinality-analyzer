# Metric-Cardinality Analyzer

## Goal

Analyze generated telemetry and produce one actionable result
about metric cardinality, delivered as a CLI or a static page.

## Non-goals

- No live metric collection, scraping, or network access.
- No storage backend, daemon, or server process.
- No query language; analysis covers one input file per run.

## Inputs

- One generated telemetry file in JSON Lines format (one JSON object
  per line, UTF-8).
- Each line has these required fields (additional top-level fields are ignored):
  - `metric`: non-empty string, the metric name.
  - `labels`: object with zero or more string keys and string values.
  - `value`: finite number.
  - `timestamp`: integer Unix milliseconds.
- The input file path is supplied by the caller (CLI argument or
  documented file location for the static-page build step).
- A run reads only the given file; no other input is required.

## Analysis behavior

- Parse the file line by line in file order.
- A **series** is a distinct `(metric, labels)` pair, where `labels`
  is the sorted `key=value` set. Two lines with the same metric and
  the same label set belong to the same series.
- Identity uses exact byte equality (UTF-8 bytes, no case folding,
  trimming, or type coercion) for metric names and for label keys.
  Two label sets are equal when they hold the same key/value pairs
  with byte-equal keys and byte-equal values, regardless of key
  order.
- For each metric name compute:
  - `samples`: total valid lines for that metric.
  - `series`: number of distinct series for that metric.
  - Per label key: number of distinct values seen for that metric.
- Rank metric names by `series` descending; break ties by metric name
  ascending (byte-wise).
- For the top-ranked metric, rank its label keys by distinct-value
  count descending; break ties by label key ascending (byte-wise).
- The **actionable result** names the top metric, its series count,
  its top label key, and one recommended action:
  `drop`, `restrict values of`, or `aggregate away` that label key
  on that metric.
- The action is a pure function of the top metric's series count `s`
  and its top label key's distinct-value count `d` (ranks and ties
  already resolved by the rules above):
  - `s == 1`: `aggregate away` (one series has no key cardinality
    to reduce).
  - otherwise, `d == s`: `drop` (every series carries a distinct
    value for that key).
  - otherwise: `restrict values of`.
- If the top-ranked metric has no label keys (all its valid lines
  carry `"labels": {}`), the breakdown section holds the single
  statement `<metric> has no label keys.`, and the `Recommendation:`
  line still appears exactly once as
  `Recommendation: <metric> has no labels (series=N); aggregate away <metric>.`
  The top-label-key naming requirement is waived in this case.

## Outputs

The implementation MUST provide at least one of the following.
Supporting both is allowed.

- Minimal observable shape, in section order (metric entries, then
  top-metric breakdown, then skipped-line statement, then the
  recommendation last): each metric entry names the metric and states
  its `samples` and `series` counts (CLI: one line per metric
  containing all three; page: one table row per metric with the
  three values); each breakdown entry names a label key and its
  distinct-value count in breakdown order; the skipped-line
  statement names the skipped count (present in every run, including
  zero); exactly one recommendation item carries the `Recommendation:`
  prefix (CLI: one line; page: one statement element).
- When zero valid lines exist, that single `Recommendation:` item
  carries the no-data statement and the top-metric/top-label-key
  naming requirement is waived: empty or all-blank input yields
  `Recommendation: no data was available (skipped 0).`; an input
  with lines but no valid lines yields
  `Recommendation: no valid telemetry was found (skipped N).`

### Option A — CLI

- Reads the input file and writes a human-readable report to stdout.
- The report contains:
  1. One line per metric: `metric`, `samples`, `series`,
     ordered by the ranking above.
  2. For the top metric: its per-label-key distinct-value breakdown.
  3. Exactly one `Recommendation:` line naming the top metric, the
     top label key, and the recommended action.
- Exit code `0` on success, including inputs with zero valid lines.

### Option B — static page

- A single self-contained HTML file (no network fetches) rendering
  the same three report sections: metric table, top-metric label
  breakdown, and exactly one recommendation statement.
- The page is produced from the input file by a documented local
  build step and opens directly from disk.

## Determinism

- The same input file bytes and the same invocation produce
  byte-identical observable output (stdout bytes for the CLI;
  HTML bytes for the static page).
- Ranking and tie-breaks follow the rules above, so output order is
  fully determined.

## Boundary cases and errors

- Empty file (zero lines): report zero metrics and a recommendation
  line/page statement that no data was available. Exit `0` (CLI).
- A blank line (empty or whitespace-only) is ignored: not parsed,
  not counted as valid, and excluded from the skipped-line count.
  Lines are split on newlines; a trailing newline at end of file
  does not create an extra line. An all-blank file is a
  zero-valid-lines run with skipped count `0`.
- Unknown extra top-level fields on a line are ignored: a line is
  valid when all required fields are present and valid, regardless
  of additional fields.
- A malformed line (invalid JSON, missing/wrong-typed field, empty
  `metric`, non-string label key/value, non-finite `value`) is
  skipped, counted, and the run still exits `0` if at least one valid
  line exists. The report states the skipped-line count.
- If no valid lines exist (all lines malformed, or all lines blank),
  the report states that no valid telemetry was found and names the
  skipped-line count. Exit `0` (CLI).
- Duplicate lines for the same series increment `samples` but not
  `series`.
- Missing input file or unreadable file: print a one-line error to
  stderr and exit non-zero (CLI); or do not emit a page and fail the
  documented build step with a one-line error (static page).
- Label values are treated as opaque strings; no normalization
  (no case folding, trimming, or number coercion).

## Acceptance checklist

- [ ] Given a generated JSONL telemetry file, the tool emits the
      metric ranking, the top-metric label breakdown, and exactly
      one recommendation.
- [ ] Re-running on the same file yields byte-identical output.
- [ ] Empty input yields the defined no-data result with exit `0`.
- [ ] Malformed lines are skipped and counted without aborting a
      run that has valid lines.
