# Cricket ETL + EDA Project

Project 1 for Programming for AI (Fall 2026), BS AI, UET Lahore.

We take cricket match data from a web API, check it, clean it, store it in a
database and then explore it. The task was: extract from an API, validate and
transform with pandas and Pydantic, load into a database, and do a structured EDA.
On top of that we added a small web page that shows what is inside the database.

## How the data moves

```
API -> extract.py -> schemas.py -> transform.py -> load.py -> cricket.db
        (download)    (Pydantic     (pandas         (SQLite)       |
                       checks)       cleaning)                     +--> eda.py  (charts + report)
                                                                   +--> app.py  (web page)
```

The order matters. Validation comes before transformation because the cleaning
code assumes every record is already sensible (for example, it cannot convert
"19.7 overs" into balls, since that value does not exist in cricket).

## Data source

We use the CricketData.org API (https://cricketdata.org). It needs a free key,
which allows roughly 100 requests per day. One request returns 25 matches, so
`--max-pages 20` downloads about 500 matches and uses 20 requests.

## Setup

You need Python 3.10 or newer. In the project folder:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and put your own key after `CRICKET_API_KEY=`. Do not upload `.env`
to GitHub (it is already listed in `.gitignore`). Every team member should make
their own key, because the daily limit is per key.

## Running

```
python main.py etl --max-pages 20     download, validate, clean, load
python main.py eda                    charts and reports/eda_report.md
python app.py                         web page at http://127.0.0.1:5000
pytest -v                             tests
```

Run `etl` before `eda` or `app.py`, because both read from `data/cricket.db`.
Running `etl` twice is safe: rows are updated, not duplicated.

There is also an `--offline` option that uses a made-up sample from
`scripts/generate_sample_data.py`. It is only there to test the code without
internet. It is not real cricket data and must not be used for the real results.

## The web page

`app.py` is a small Flask server. It has two jobs: it sends the page
(`templates/index.html`, `static/style.css`, `static/script.js`), and it answers
data requests from the page with JSON. The page draws the charts with Chart.js.

Filters at the top (format, years, men/women) change every number and chart. The
page also has a team win table with an adjustable minimum number of matches, a
searchable match list and a data quality section.

The database is opened in read-only mode, so the page can not change any data.
User input is never pasted into the SQL text, only passed as parameters.

| Address | Returns |
|---|---|
| `/` | the web page |
| `/api/filters` | formats available and the first and last year |
| `/api/summary` | number of matches, innings, teams and average runs |
| `/api/formats` | matches per format |
| `/api/years` | matches per year and format |
| `/api/runrate` | average run rate per format |
| `/api/batting_first` | percentage of wins by the team batting first |
| `/api/teams?min=10` | win percentage per team |
| `/api/venues` | ten busiest venues |
| `/api/matches?q=text` | latest matches, with optional search |
| `/api/quality` | data quality numbers and the last ETL runs |

The filters (`formats`, `year_from`, `year_to`, `gender`) can be added to most of
these addresses.

Chart.js is loaded from a CDN. If you want the page to work without internet,
download https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js and
save it as `static/chart.umd.min.js`. The page uses that copy when the CDN is
not reachable.

## Files

| File | What it does |
|---|---|
| `main.py` | Command line: `etl`, `eda` or `all` |
| `app.py` | Flask server and JSON API for the web page |
| `templates/index.html` | Structure of the web page |
| `static/style.css` | Colours and layout |
| `static/script.js` | Filters, requests to the API and charts |
| `cricket_pipeline/config.py` | Paths, API address and constants |
| `cricket_pipeline/logger.py` | Prints progress and writes `logs/pipeline.log` |
| `cricket_pipeline/extract.py` | Downloads pages from the API, retries on server errors, saves the raw JSON |
| `cricket_pipeline/schemas.py` | Pydantic models that decide if a record is valid |
| `cricket_pipeline/transform.py` | pandas cleaning and new columns |
| `cricket_pipeline/load.py` | Creates the SQLite tables and loads the data |
| `cricket_pipeline/pipeline.py` | Runs the ETL steps in order |
| `cricket_pipeline/eda.py` | The exploratory analysis, charts and report |
| `tests/` | 28 tests for validation and transformation |
| `scripts/generate_sample_data.py` | Makes the fake sample for offline testing |

## What each step does

**Extract.** Asks the API for `matches` and `series` page by page. The raw answer
is saved in `data/raw/` untouched, so we can always see what the API really sent.

**Validate.** Each match goes through a Pydantic model. A record is rejected if,
for example, the ID is not a proper UUID, wickets are above 10, runs are negative,
the overs value has more than 5 balls, the date is before 2000 or in the future for
a finished match, or a finished match does not have exactly two teams. Rejected
records are not thrown away silently. They go to `data/processed/rejected_records.csv`
with the reason.

**Transform.** Done with pandas. It tidies the text, removes duplicate matches, keeps
only finished matches, and splits the result text ("India won by 5 wickets") into
winner, type of win and margin. Overs are converted to balls (19.4 overs is
19 x 6 + 4 = 118 balls) and the run rate is calculated from that. New columns
include whether the team batting first won and whether the toss winner won.

**Load.** Writes five tables into `data/cricket.db`: `dim_series`, `dim_team`,
`fact_match`, `fact_innings` and `etl_run_log`, plus a view `vw_team_record`.
The tables have primary keys, foreign keys and CHECK rules (for example wickets
between 0 and 10). All tables are loaded in one transaction, so a failure in the
middle does not leave half-loaded data.

**EDA.** Reads the data back from the database with SQL. It covers an overview and
missing values, single-variable charts, relations between variables, teams and
venues, batting first versus chasing, toss, a few statistical tests and an outlier
check. Charts go to `reports/figures/` and the written summary to
`reports/eda_report.md`. Outliers are checked but not removed, because very high
scores are real cricket events and not data errors.

## Output folders

- `data/raw/` : original API responses
- `data/processed/` : cleaned CSV files and the rejected records
- `data/cricket.db` : the database
- `reports/` : EDA report, data quality report, figures
- `logs/` : log of every run

## Things to know

- Only the first 3 pages of the series list are downloaded. Matches that belong to
  a series we did not download get the name "Unknown series" in `dim_series`. This
  keeps the foreign key valid and does not affect the analysis. The number of pages
  can be raised in `pipeline.py` (`fetch_series(max_pages=3)`).
- Toss information is not always present in the API data, so the toss part of the
  EDA only runs when there are at least 30 matches with toss details.
- The free API plan has a daily limit, so avoid running `etl` many times in one day.
- If the API changes a field name, the place to fix it is `schemas.py`.
- `app.py` runs with `debug=True`, which is fine for a project demo but should be
  turned off if the page is ever put on a real server.

## Team

| Member | Part |
|---|---|
| MUHAMMAD ZAIN UL ABIDEEN | Extract and validate |
| MUHAMMAD HASSAN ISHTIAQ | Transform and load |
| MUHAMMAD ALI SHAKEEL | EDA |
| ZAIN HAIDER | Web Interface |