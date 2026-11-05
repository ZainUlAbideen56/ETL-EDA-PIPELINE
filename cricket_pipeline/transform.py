from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config
from .logger import get_logger

log = get_logger()

_INNINGS_LABEL = re.compile(r"^(?P<team>.+?)\s+Inning[s]?\s+(?P<no>\d+)\s*$", re.I)
_WIN_INNINGS = re.compile(r"^(?P<winner>.+?)\s+won by an innings and (?P<m>\d+) runs?", re.I)
_WIN_RUNS = re.compile(r"^(?P<winner>.+?)\s+won by (?P<m>\d+) runs?", re.I)
_WIN_WICKETS = re.compile(r"^(?P<winner>.+?)\s+won by (?P<m>\d+) (?:wickets?|wkts?)", re.I)


def clean_text(value) -> str | None:
    """Collapse repeated spaces, strip ends. None stays None."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None

def overs_to_balls(overs: float) -> int:
    """Cricket overs are NOT decimals: 19.4 means 19 overs + 4 balls = 118 balls."""
    whole = int(overs)
    balls = round((overs - whole) * 10)
    if not 0 <= balls <= 5:
        raise ValueError(f"invalid overs value: {overs}")
    return whole * 6 + balls

def parse_status(status: str | None, match_winner: str | None = None) -> dict:
    """Turn 'India won by 5 wickets' into winner / win_type / win_margin / result_type."""
    text = clean_text(status) or ""
    result = {"result_type": "other", "winner": None, "win_type": None, "win_margin": None}

    for win_type, pattern in (("innings", _WIN_INNINGS), ("runs", _WIN_RUNS), ("wickets", _WIN_WICKETS)):
        found = pattern.match(text)
        if found:
            result.update(
                result_type="win",
                winner=clean_text(found["winner"]),
                win_type=win_type,
                win_margin=int(found["m"]),
            )
            return result

    low = text.lower()
    if "tied" in low or re.search(r"\bties\b|\btie\b", low):
        result["result_type"] = "tie"
    elif "draw" in low:
        result["result_type"] = "draw"
    elif "no result" in low or "abandon" in low:
        result["result_type"] = "no_result"
    elif clean_text(match_winner):
        result.update(result_type="win", winner=clean_text(match_winner))
    return result


def parse_innings_label(label: str) -> tuple[str, int | None]:
    """'Pakistan Women Inning 2' -> ('Pakistan Women', 2)."""
    found = _INNINGS_LABEL.match(clean_text(label) or "")
    if found:
        return clean_text(found["team"]), int(found["no"])
    return clean_text(label), None


def resolve_team(name: str | None, teams: list[str], short_names: dict[str, str] | None = None) -> str | None:
    """Map a team name from the API (any case, short code, longer/shorter form) to the match's real team name."""
    name = clean_text(name)
    if not name:
        return None
    low = name.lower()
    for team in teams:                                  
        if team and team.lower() == low:
            return team
    for team, short in (short_names or {}).items():   
        if team in teams and short and short.lower() == low:
            return team
    for team in teams:                           
        if team and "".join(w[0] for w in team.split()).lower() == low:
            return team
    hits = [t for t in teams if t and (t.lower() in low or low in t.lower()
                                       or low.split(",")[0].strip() == t.lower())]
    return hits[0] if len(hits) == 1 else None


def resolve_innings_teams(labels: list[str], teams: list[str]) -> list[str | None]:
    """Work out which team batted in each innings.

    The API sometimes writes labels in lower case ('argentina women Inning 1') or with both teams
    ('Mexico Women,Argentina Women Inning 1'). Those are matched to the match's two teams.
    """
    found: list[str | None] = []
    for label in labels:
        base, _ = parse_innings_label(label)
        found.append(resolve_team(base, teams))
    if len(teams) == 2:
        for pos, team in enumerate(found):
            if team is not None:
                continue
            neighbour = found[pos - 1] if pos > 0 and found[pos - 1] else (
                found[pos + 1] if pos + 1 < len(found) else None)
            if neighbour in teams:
                found[pos] = teams[1] if neighbour == teams[0] else teams[0]
    return found


def _nullable_equal(left: pd.Series, right: pd.Series) -> pd.Series:
    """Element-wise equality that keeps missing values as <NA> (tri-state boolean)."""
    values = [
        pd.NA if (pd.isna(a) or pd.isna(b)) else bool(a == b)
        for a, b in zip(left, right)
    ]
    return pd.Series(values, index=left.index, dtype="boolean")

@dataclass
class TransformResult:
    matches: pd.DataFrame
    innings: pd.DataFrame
    teams: pd.DataFrame
    series: pd.DataFrame
    stats: dict = field(default_factory=dict)


def build_tables(valid_matches: list[dict], valid_series: list[dict]) -> TransformResult:
    """Convert validated dicts into clean, analysis-ready tables."""
    stats: dict = {"validated_matches": len(valid_matches)}

    match_rows: list[dict] = []
    innings_rows: list[dict] = []
    short_names: dict[str, str] = {}

    for rec in valid_matches:
        match_id = str(rec["id"])
        teams = [clean_text(t) for t in rec["teams"]]
        for info in rec.get("teamInfo") or []:
            name, short = clean_text(info.get("name")), clean_text(info.get("shortname"))
            if name and short:
                short_names[name] = short

        outcome = parse_status(rec.get("status"), rec.get("matchWinner"))
        match_short = {clean_text(i.get("name")): clean_text(i.get("shortname"))
                       for i in rec.get("teamInfo") or []}
        outcome["winner"] = resolve_team(outcome["winner"], teams, match_short) or outcome["winner"]
        venue = clean_text(rec.get("venue"))
        toss_choice = clean_text(rec.get("tossChoice"))

        match_rows.append(
            {
                "match_id": match_id,
                "match_name": clean_text(rec["name"]),
                "format": rec["matchType"],
                "match_date": pd.Timestamp(rec["date"]),
                "venue": venue or "Unknown",
                "city": venue.rsplit(",", 1)[-1].strip() if venue and "," in venue else "Unknown",
                "series_id": str(rec["series_id"]) if rec.get("series_id") else None,
                "team1": teams[0] if len(teams) > 0 else None,
                "team2": teams[1] if len(teams) > 1 else None,
                "is_women": any("women" in (t or "").lower() for t in teams),
                "status": clean_text(rec.get("status")),
                "match_ended": bool(rec.get("matchEnded")),
                "toss_winner": clean_text(rec.get("tossWinner")),
                "toss_decision": toss_choice.lower() if toss_choice else None,
                **outcome,
            }
        )

        scores = rec.get("score") or []
        innings_teams = resolve_innings_teams([inn["inning"] for inn in scores], teams)
        for number, inn in enumerate(scores, start=1):
            team = innings_teams[number - 1] or parse_innings_label(inn["inning"])[0]
            balls = overs_to_balls(inn["o"])
            innings_rows.append(
                {
                    "match_id": match_id,
                    "innings_no": number,
                    "team": team,
                    "runs": int(inn["r"]),
                    "wickets": int(inn["w"]),
                    "overs": float(inn["o"]),
                    "balls": balls,
                    "run_rate": round(inn["r"] / (balls / 6), 2) if balls > 0 else np.nan,
                    "all_out": int(inn["w"]) == config.MAX_WICKETS,
                }
            )

    matches = pd.DataFrame(match_rows)
    innings = pd.DataFrame(innings_rows)

    before = len(matches)
    matches = matches.drop_duplicates("match_id", keep="last").reset_index(drop=True)
    stats["duplicates_removed"] = before - len(matches)
    if not innings.empty:
        innings = innings[innings["match_id"].isin(matches["match_id"])]
        innings = innings.drop_duplicates(["match_id", "innings_no"], keep="last").reset_index(drop=True)

    stats["not_completed_filtered"] = int((~matches["match_ended"]).sum())
    matches = matches[matches["match_ended"]].drop(columns="match_ended").reset_index(drop=True)
    if not innings.empty:
        innings = innings[innings["match_id"].isin(matches["match_id"])].reset_index(drop=True)

    if not innings.empty:
        first = innings[innings["innings_no"] == 1].set_index("match_id")
        second = innings[innings["innings_no"] == 2].set_index("match_id")
        matches["batting_first_team"] = matches["match_id"].map(first["team"])
        matches["first_innings_runs"] = matches["match_id"].map(first["runs"])
        matches["second_innings_runs"] = matches["match_id"].map(second["runs"])
        matches["total_runs"] = matches["match_id"].map(innings.groupby("match_id")["runs"].sum())
        matches["innings_count"] = matches["match_id"].map(innings.groupby("match_id").size()).fillna(0).astype(int)
    else:
        for col in ("batting_first_team", "first_innings_runs", "second_innings_runs", "total_runs"):
            matches[col] = np.nan
        matches["innings_count"] = 0

    limited = matches["format"].isin(config.LIMITED_OVERS)
    won_first = _nullable_equal(matches["winner"], matches["batting_first_team"])
    matches["batting_first_won"] = won_first.where(limited, pd.NA).astype("boolean")
    matches["toss_won_match"] = _nullable_equal(matches["toss_winner"], matches["winner"])

    all_team_names = pd.concat(
        [
            matches["team1"], matches["team2"], matches["winner"], matches["toss_winner"],
            innings["team"] if not innings.empty else pd.Series(dtype="object"),
        ]
    ).dropna().unique()
    teams = pd.DataFrame({"team_name": sorted(all_team_names)})
    teams["short_name"] = teams["team_name"].map(short_names)
    teams["is_women"] = teams["team_name"].str.contains("women", case=False)

    series = _build_series_table(valid_series, matches)

    matches["match_date"] = matches["match_date"].dt.strftime("%Y-%m-%d")
    matches = matches.sort_values("match_date").reset_index(drop=True)

    stats["clean_matches"] = len(matches)
    stats["clean_innings"] = len(innings)
    stats["teams"] = len(teams)
    log.info(
        "Transform done: %d matches, %d innings, %d teams, %d series",
        len(matches), len(innings), len(teams), len(series),
    )
    return TransformResult(matches, innings, teams, series, stats)


def _build_series_table(valid_series: list[dict], matches: pd.DataFrame) -> pd.DataFrame:
    """dim_series = API series + a placeholder row for every series_id used by a match."""
    rows = []
    for rec in valid_series:
        rows.append(
            {
                "series_id": str(rec["id"]),
                "series_name": clean_text(rec["name"]),
                "start_date": pd.to_datetime(rec.get("startDate"), errors="coerce"),
                "end_date": pd.to_datetime(rec.get("endDate"), errors="coerce"),
                "odi_matches": rec.get("odi", 0),
                "t20_matches": rec.get("t20", 0),
                "test_matches": rec.get("test", 0),
            }
        )
    series = pd.DataFrame(
        rows,
        columns=["series_id", "series_name", "start_date", "end_date",
                 "odi_matches", "t20_matches", "test_matches"],
    )
    for col in ("start_date", "end_date"):
        series[col] = pd.to_datetime(series[col], errors="coerce").dt.strftime("%Y-%m-%d")
    series = series.drop_duplicates("series_id", keep="last")

    used = set(matches["series_id"].dropna())
    missing = sorted(used - set(series["series_id"]))
    if missing:                    
        filler = pd.DataFrame({"series_id": missing, "series_name": "Unknown series"})
        series = pd.concat([series, filler], ignore_index=True)
    return series.reset_index(drop=True)


def quality_report(result: TransformResult, rejected: list[dict], extracted: int) -> dict:
    """Numbers that go into reports/data_quality_report.json."""
    m = result.matches
    missing_pct = (m.isna().mean() * 100).round(2).to_dict() if len(m) else {}
    return {
        "records_extracted": extracted,
        "rejected_by_pydantic": len(rejected),
        "duplicates_removed": result.stats.get("duplicates_removed", 0),
        "not_completed_filtered": result.stats.get("not_completed_filtered", 0),
        "clean_matches_loaded": result.stats.get("clean_matches", 0),
        "clean_innings_loaded": result.stats.get("clean_innings", 0),
        "missing_percent_by_column": missing_pct,
    }