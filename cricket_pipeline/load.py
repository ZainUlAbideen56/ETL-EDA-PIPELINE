from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .logger import get_logger
from .transform import TransformResult

log = get_logger()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dim_series (
    series_id     TEXT PRIMARY KEY,
    series_name   TEXT NOT NULL,
    start_date    TEXT,
    end_date      TEXT,
    odi_matches   INTEGER,
    t20_matches   INTEGER,
    test_matches  INTEGER
);

CREATE TABLE IF NOT EXISTS dim_team (
    team_name   TEXT PRIMARY KEY,
    short_name  TEXT,
    is_women    INTEGER NOT NULL CHECK (is_women IN (0, 1))
);

CREATE TABLE IF NOT EXISTS fact_match (
    match_id             TEXT PRIMARY KEY,
    match_name           TEXT NOT NULL,
    format               TEXT NOT NULL CHECK (format IN ('Test', 'ODI', 'T20', 'Other')),
    match_date           TEXT NOT NULL,
    venue                TEXT NOT NULL,
    city                 TEXT NOT NULL,
    series_id            TEXT REFERENCES dim_series(series_id),
    team1                TEXT NOT NULL REFERENCES dim_team(team_name),
    team2                TEXT NOT NULL REFERENCES dim_team(team_name),
    is_women             INTEGER NOT NULL CHECK (is_women IN (0, 1)),
    status               TEXT,
    result_type          TEXT NOT NULL CHECK (result_type IN ('win','tie','draw','no_result','other')),
    winner               TEXT REFERENCES dim_team(team_name),
    win_type             TEXT CHECK (win_type IN ('runs','wickets','innings') OR win_type IS NULL),
    win_margin           INTEGER CHECK (win_margin IS NULL OR win_margin >= 0),
    toss_winner          TEXT,
    toss_decision        TEXT,
    batting_first_team   TEXT,
    first_innings_runs   INTEGER,
    second_innings_runs  INTEGER,
    total_runs           INTEGER,
    innings_count        INTEGER NOT NULL DEFAULT 0,
    batting_first_won    INTEGER CHECK (batting_first_won IN (0, 1) OR batting_first_won IS NULL),
    toss_won_match       INTEGER CHECK (toss_won_match IN (0, 1) OR toss_won_match IS NULL)
);

CREATE TABLE IF NOT EXISTS fact_innings (
    match_id    TEXT NOT NULL REFERENCES fact_match(match_id) ON DELETE CASCADE,
    innings_no  INTEGER NOT NULL CHECK (innings_no >= 1),
    team        TEXT NOT NULL REFERENCES dim_team(team_name),
    runs        INTEGER NOT NULL CHECK (runs >= 0),
    wickets     INTEGER NOT NULL CHECK (wickets BETWEEN 0 AND 10),
    overs       REAL    NOT NULL CHECK (overs >= 0),
    balls       INTEGER NOT NULL CHECK (balls >= 0),
    run_rate    REAL,
    all_out     INTEGER NOT NULL CHECK (all_out IN (0, 1)),
    PRIMARY KEY (match_id, innings_no)
);

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    source          TEXT NOT NULL,
    extracted       INTEGER,
    rejected        INTEGER,
    loaded_matches  INTEGER,
    loaded_innings  INTEGER,
    status          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_match_date   ON fact_match(match_date);
CREATE INDEX IF NOT EXISTS idx_match_format ON fact_match(format);
CREATE INDEX IF NOT EXISTS idx_match_winner ON fact_match(winner);
CREATE INDEX IF NOT EXISTS idx_innings_team ON fact_innings(team);

CREATE VIEW IF NOT EXISTS vw_team_record AS
SELECT  t.team_name,
        COUNT(m.match_id)                                         AS matches_played,
        SUM(CASE WHEN m.winner = t.team_name THEN 1 ELSE 0 END)   AS wins,
        ROUND(100.0 * SUM(CASE WHEN m.winner = t.team_name THEN 1 ELSE 0 END)
              / COUNT(m.match_id), 1)                             AS win_percent
FROM dim_team t
JOIN fact_match m ON t.team_name IN (m.team1, m.team2)
GROUP BY t.team_name;
"""

def _to_rows(df: pd.DataFrame) -> list[tuple]:
    """DataFrame -> list of plain-Python tuples (NaN/NA become None, bools become ints)."""
    clean = df.astype(object).where(df.notna(), None)
    rows = []
    for row in clean.itertuples(index=False, name=None):
        rows.append(tuple(int(v) if isinstance(v, bool) else v for v in row))
    return rows


def upsert(conn: sqlite3.Connection, table: str, df: pd.DataFrame, key: list[str]) -> int:
    """INSERT new rows, UPDATE existing ones (matched on `key`)."""
    if df.empty:
        return 0
    cols = list(df.columns)
    updates = [c for c in cols if c not in key]
    action = (
        "DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in updates)
        if updates else "DO NOTHING"
    )
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({', '.join(key)}) {action}"
    )
    conn.executemany(sql, _to_rows(df))
    return len(df)


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_all(result: TransformResult, source: str, extracted: int, rejected: int,
             started_at: datetime, db_path: Path = config.DB_PATH) -> dict:
    """Create the schema (if needed) and upsert every table inside one transaction."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        with conn:                             
            n_series = upsert(conn, "dim_series", result.series, ["series_id"])
            n_teams = upsert(conn, "dim_team", result.teams, ["team_name"])
            n_matches = upsert(conn, "fact_match", result.matches, ["match_id"])

            ids = [(i,) for i in result.matches["match_id"]]
            conn.executemany("DELETE FROM fact_innings WHERE match_id = ?", ids)
            n_innings = upsert(conn, "fact_innings", result.innings, ["match_id", "innings_no"])

            conn.execute(
                "INSERT INTO etl_run_log (started_at, finished_at, source, extracted, rejected, "
                "loaded_matches, loaded_innings, status) VALUES (?,?,?,?,?,?,?,?)",
                (started_at.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"),
                 source, extracted, rejected, n_matches, n_innings, "SUCCESS"),
            )
        counts = {
            "dim_series": n_series, "dim_team": n_teams,
            "fact_match": n_matches, "fact_innings": n_innings,
        }
        log.info("Loaded into %s -> %s", db_path.name, counts)
        return counts
    finally:
        conn.close()