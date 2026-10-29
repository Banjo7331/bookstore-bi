# bookstore-analytics

Dashboard over five bookstore datasets, with a chat assistant that answers
questions about the data and can drive the dashboard.

## Running it

```bash
pip install -r requirements.txt
cd app && ANTHROPIC_API_KEY=sk-ant-... python app.py
```

Then open http://localhost:8000. Without the key the dashboard still works and
the chat returns a 503.

Rebuilding the cleaned data from the raw `STORE*` folders needs the extra dev
dependencies:

```bash
pip install -r requirements-dev.txt
python build_data.py path/to/raw/data
python verify.py path/to/raw/data
```

## Layout

```
parsers.py     price, timestamp and person-name parsing
pipeline.py    load and clean one STORE folder, compute the metrics
build_data.py  raw folders -> app/data/*.csv.gz + metrics.json
verify.py      recomputes the headline numbers a second way
app/
  app.py        Flask routes: dashboard, JSON API, chat
  datastore.py  loads the cleaned tables, filtering and aggregation
  tools.py      the tools the model is allowed to call
  test_chat.py  tool-calling loop tests against a scripted fake API
```

The app only needs Flask and pandas at runtime, because the cleaned tables are
committed as gzipped CSV. That keeps it deployable on a free PythonAnywhere
account, where pyarrow is awkward to install.

## Cleaning notes

The raw data is messy in three ways worth writing down.

**Prices come in 52 formats.** `$18.00`, `USD 18.00`, `18.0$`, `18.`, and two
that look like typos but are not: `$20¢25` and `46$99¢`. In those the currency
symbol or the cent sign is the decimal separator. One rule handles all of them:
a currency character between two digits is a decimal point, anything else that
is not a digit or a dot is noise. EUR converts at 1.2 and rounds to cents with
`Decimal`. All 49,545 rows parse.

**Timestamps come in 132 formats.** The separator decides the field order:
`10.12.2025` is 10 December, `02/16/26` is 16 February. Values above 12 in both
positions confirm it. A single `dayfirst` flag would corrupt half the rows.
Beyond that there is ISO, `D-Month-YYYY` in three capitalisations, C `asctime`,
the time before or after the date, and `AM` / `am` / `A.M.`. All rows parse.

**Users need reconciling.** Records differing in at most one of name, address,
phone or e-mail are one person. Done by blocking on each leave-one-out triple
and merging with union-find, which also handles chains — someone who changed
phone and later address. `verify.py` checks this against a brute-force
all-pairs comparison.

Author names have their honorifics and suffixes stripped and form a
`frozenset` per book, so a collaboration is one set and each author's solo work
another. No author appears in more than one spelling here, so the count does
not depend on that step.

## How the assistant avoids inventing numbers

The model gets 16 tools and a system prompt forbidding any figure it did not
get from one of them. Counting, summing, ranking and filtering happen in
pandas. The chat panel prints the chain of tool calls under each answer, so it
is visible which API produced the number.

Arithmetic belongs to the API, language belongs to the model. "Filter out books
with people names in the title" needs someone to read each title, which no
aggregation can do, so the model calls `list_book_titles`, decides itself, and
passes the chosen ids to `filter_books`. Dashboard-control tools return a
`ui_action` that the browser applies to the current view.

## Results

| | STORE1 | STORE2 | STORE3 | STORE4 | STORE5 |
|---|---|---|---|---|---|
| revenue | $739,354.03 | $668,103.84 | $681,626.00 | $778,289.82 | $704,422.31 |
| unique users | 3,221 | 3,166 | 2,955 | 2,850 | 2,987 |
| raw user records | 3,394 | 3,319 | 3,107 | 3,008 | 3,158 |
| unique author sets | 324 | 281 | 307 | 299 | 311 |
| best buyer ids | [48403, 48904, 50056] | [51014] | [52881, 53869, 54846] | [53347, 54809] | [52895, 53969] |

STORE1 top 5 days: 2025-08-20, 2025-09-22, 2026-01-15, 2025-09-03, 2025-10-17.
Most popular author set: Darron Ernser and Lorina Kertzmann, 173 copies.

In STORE3 one person shows up as both Burt Streich and Kendal Ernser, which is
the alias case the reconciliation is there for.
