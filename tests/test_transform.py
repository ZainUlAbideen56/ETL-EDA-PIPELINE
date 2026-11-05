import datetime as dt
import uuid

import pytest

from cricket_pipeline.transform import (build_tables, clean_text, overs_to_balls,
                                        parse_innings_label, parse_status)

@pytest.mark.parametrize("overs, balls", [(0.0, 0), (19.4, 118), (20.0, 120), (49.5, 299), (0.1, 1)])
def test_overs_to_balls(overs, balls):
    assert overs_to_balls(overs) == balls


def test_overs_to_balls_rejects_invalid_ball_part():
    with pytest.raises(ValueError):
        overs_to_balls(19.7)

def test_clean_text():
    assert clean_text("  Gaddafi   Stadium ,  Lahore ") == "Gaddafi Stadium , Lahore"
    assert clean_text("   ") is None and clean_text(None) is None

@pytest.mark.parametrize("status, winner, win_type, margin, result", [
    ("India won by 5 wickets", "India", "wickets", 5, "win"),
    ("Pakistan Women won by 23 runs", "Pakistan Women", "runs", 23, "win"),
    ("England won by an innings and 45 runs", "England", "innings", 45, "win"),
    ("Match drawn", None, None, None, "draw"),
    ("Match tied (India won the super over)", None, None, None, "tie"),
    ("No result", None, None, None, "no_result"),
    ("Match not started", None, None, None, "other"),
])
def test_parse_status(status, winner, win_type, margin, result):
    out = parse_status(status)
    assert (out["winner"], out["win_type"], out["win_margin"], out["result_type"]) == (winner, win_type, margin, result)

def test_parse_innings_label():
    assert parse_innings_label("Pakistan Women Inning 2") == ("Pakistan Women", 2)
    assert parse_innings_label("Super Over") == ("Super Over", None)

def _match(winner_text, r1, w1, o1, r2, w2, o2, ended=True, mid=None):
    return {
        "id": mid or uuid.uuid4(), "name": "India vs Pakistan, 1st T20", "matchType": "T20",
        "status": winner_text, "venue": "Gaddafi Stadium, Lahore", "date": dt.date(2024, 5, 1),
        "teams": ["India", "Pakistan"], "teamInfo": [{"name": "India", "shortname": "IND"}],
        "score": [{"r": r1, "w": w1, "o": o1, "inning": "India Inning 1"},
                  {"r": r2, "w": w2, "o": o2, "inning": "Pakistan Inning 1"}],
        "series_id": None, "matchStarted": True, "matchEnded": ended,
        "tossWinner": "India", "tossChoice": "Bat", "matchWinner": None,
    }

def test_build_tables_core_features():
    res = build_tables([_match("India won by 10 runs", 180, 6, 20.0, 170, 8, 20.0)], [])
    m, i = res.matches.iloc[0], res.innings
    assert len(res.matches) == 1 and len(i) == 2
    assert m.winner == "India" and m.win_type == "runs" and m.win_margin == 10
    assert m.city == "Lahore" and m.batting_first_team == "India"
    assert bool(m.batting_first_won) is True and bool(m.toss_won_match) is True
    assert m.toss_decision == "bat" and m.total_runs == 350
    assert i.loc[0, "run_rate"] == 9.0 and i.loc[0, "balls"] == 120

def test_chasing_win_is_detected():
    res = build_tables([_match("Pakistan won by 4 wickets", 150, 9, 20.0, 151, 6, 18.3)], [])
    assert bool(res.matches.iloc[0].batting_first_won) is False
    assert res.innings.loc[1, "balls"] == 111 

def test_duplicates_and_unfinished_matches_are_removed():
    mid = uuid.uuid4()
    rows = [_match("India won by 10 runs", 180, 6, 20.0, 170, 8, 20.0, mid=mid),
            _match("India won by 10 runs", 180, 6, 20.0, 170, 8, 20.0, mid=mid),
            _match("Match not started", 1, 0, 0.1, 1, 0, 0.1, ended=False)]
    res = build_tables(rows, [])
    assert res.stats["duplicates_removed"] == 1
    assert res.stats["not_completed_filtered"] == 1
    assert len(res.matches) == 1

def test_dimension_tables_are_consistent():
    res = build_tables([_match("India won by 10 runs", 180, 6, 20.0, 170, 8, 20.0)], [])
    assert set(res.teams.team_name) == {"India", "Pakistan"}
    assert res.teams.set_index("team_name").loc["India", "short_name"] == "IND"