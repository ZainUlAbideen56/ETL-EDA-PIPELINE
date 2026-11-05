from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from flask import Flask, jsonify, render_template, request

from cricket_pipeline import config

app = Flask(__name__)
FORMATS = ("Test", "ODI", "T20", "Other")

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, params=()) -> list[dict]:
    with closing(connect()) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def filters() -> tuple[str, list]:
    """Turn the filter values from the URL into a WHERE clause.

    Only '?' placeholders are put into the SQL text, the values themselves are passed
    separately, so nobody can inject SQL through the URL.
    """
    where, params = [], []
    if "formats" in request.args:
        chosen = [f for f in request.args["formats"].split(",") if f in FORMATS]
        if not chosen:
            return "1=0", []
        where.append(f"format IN ({','.join('?' * len(chosen))})")
        params += chosen
    year_from = request.args.get("year_from", type=int)
    year_to = request.args.get("year_to", type=int)
    if year_from is not None and year_to is not None:
        where.append("CAST(strftime('%Y', match_date) AS INTEGER) BETWEEN ? AND ?")
        params += [year_from, year_to]
    gender = request.args.get("gender", "all")
    if gender in ("men", "women"):
        where.append("is_women = ?")
        params.append(1 if gender == "women" else 0)
    return (" AND ".join(where) or "1=1"), params


@app.errorhandler(sqlite3.OperationalError)
def database_problem(exc):
    return jsonify(error=f"Database problem ({exc}). Run 'python main.py etl' first."), 503

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/filters")
def api_filters():
    year = "CAST(strftime('%Y', match_date) AS INTEGER)"
    span = rows(f"SELECT MIN({year}) AS year_min, MAX({year}) AS year_max FROM fact_match")[0]
    formats = [r["format"] for r in rows("SELECT DISTINCT format FROM fact_match ORDER BY format")]
    return jsonify(formats=formats, **span)


@app.route("/api/summary")
def api_summary():
    w, p = filters()
    m = rows(f"SELECT COUNT(*) AS matches FROM fact_match WHERE {w}", p)[0]
    i = rows("SELECT COUNT(*) AS innings, ROUND(AVG(runs), 0) AS avg_runs "
             f"FROM fact_innings JOIN fact_match USING (match_id) WHERE {w}", p)[0]
    t = rows("SELECT COUNT(*) AS teams FROM (SELECT team1 AS t FROM fact_match WHERE "
             f"{w} UNION SELECT team2 FROM fact_match WHERE {w})", p + p)[0]
    return jsonify(**m, **i, **t)


@app.route("/api/formats")
def api_formats():
    w, p = filters()
    return jsonify(rows("SELECT format AS label, COUNT(*) AS value FROM fact_match "
                        f"WHERE {w} GROUP BY format ORDER BY value DESC", p))


@app.route("/api/years")
def api_years():
    w, p = filters()
    return jsonify(rows("SELECT CAST(strftime('%Y', match_date) AS INTEGER) AS year, format, "
                        f"COUNT(*) AS value FROM fact_match WHERE {w} GROUP BY year, format ORDER BY year", p))


@app.route("/api/runrate")
def api_runrate():
    w, p = filters()
    return jsonify(rows("SELECT format AS label, ROUND(AVG(run_rate), 2) AS value "
                        "FROM fact_innings JOIN fact_match USING (match_id) "
                        f"WHERE {w} AND run_rate IS NOT NULL GROUP BY format", p))


@app.route("/api/batting_first")
def api_batting_first():
    w, p = filters()
    return jsonify(rows("SELECT format AS label, ROUND(100.0 * AVG(batting_first_won), 1) AS value, "
                        "COUNT(batting_first_won) AS n FROM fact_match "
                        f"WHERE {w} AND batting_first_won IS NOT NULL GROUP BY format", p))


@app.route("/api/teams")
def api_teams():
    w, p = filters()
    minimum = request.args.get("min", 10, type=int)
    data = rows(
        f"WITH f AS (SELECT * FROM fact_match WHERE {w}), "
        "p AS (SELECT team1 AS team FROM f UNION ALL SELECT team2 FROM f) "
        "SELECT team, COUNT(*) AS played, "
        "(SELECT COUNT(*) FROM f WHERE f.winner = p.team) AS wins "
        "FROM p GROUP BY team HAVING COUNT(*) >= ?", p + [minimum])
    for d in data:
        d["win_pct"] = round(100 * d["wins"] / d["played"], 1)
    data.sort(key=lambda d: d["win_pct"], reverse=True)
    return jsonify(data[:12])


@app.route("/api/venues")
def api_venues():
    w, p = filters()
    return jsonify(rows("SELECT venue AS label, COUNT(*) AS value FROM fact_match "
                        f"WHERE {w} AND venue != 'Unknown' GROUP BY venue ORDER BY value DESC LIMIT 10", p))


@app.route("/api/matches")
def api_matches():
    w, p = filters()
    q = request.args.get("q", "").strip()
    if q:
        w += " AND (match_name LIKE ? OR venue LIKE ? OR winner LIKE ?)"
        p = p + [f"%{q}%"] * 3
    total = rows(f"SELECT COUNT(*) AS n FROM fact_match WHERE {w}", p)[0]["n"]
    data = rows("SELECT match_date, match_name, format, venue, winner, status FROM fact_match "
                f"WHERE {w} ORDER BY match_date DESC LIMIT 25", p)
    return jsonify(total=total, rows=data)


@app.route("/api/quality")
def api_quality():
    path = config.REPORT_DIR / "data_quality_report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    runs = rows("SELECT * FROM etl_run_log ORDER BY run_id DESC LIMIT 5")
    return jsonify(report=report, runs=runs)


if __name__ == "__main__":
    app.run(debug=True)