import copy
import uuid

import pytest

pytest.importorskip("pydantic")
from cricket_pipeline.schemas import validate_matches 

GOOD = {
    "id": str(uuid.uuid4()), "name": "India vs Pakistan, 1st T20", "matchType": "t20",
    "status": "India won by 10 runs", "venue": "Gaddafi Stadium, Lahore", "date": "2024-05-01",
    "teams": ["India", "Pakistan"],
    "score": [{"r": 180, "w": 6, "o": 20, "inning": "India Inning 1"},
              {"r": 170, "w": 8, "o": 20, "inning": "Pakistan Inning 1"}],
    "matchStarted": True, "matchEnded": True,
}


def _with(**changes):
    rec = copy.deepcopy(GOOD)
    rec.update(changes)
    return rec


def test_good_record_passes_and_format_is_standardised():
    valid, rejected = validate_matches([GOOD])
    assert len(valid) == 1 and not rejected
    assert valid[0]["matchType"] == "T20"


@pytest.mark.parametrize("bad", [
    _with(id="not-a-guid"),
    _with(date="1995-01-01"),
    _with(date="2999-01-01"),
    _with(teams=["India"]),
    _with(score=[{"r": 100, "w": 11, "o": 20, "inning": "India Inning 1"}]),
    _with(score=[{"r": 100, "w": 5, "o": 19.7, "inning": "India Inning 1"}]),
    _with(score=[{"r": -4, "w": 5, "o": 19.2, "inning": "India Inning 1"}]),
])
def test_bad_records_are_rejected_with_a_reason(bad):
    valid, rejected = validate_matches([bad])
    assert not valid and len(rejected) == 1 and rejected[0]["reasons"]


def test_missing_date_is_rejected():
    rec = copy.deepcopy(GOOD)
    del rec["date"]
    valid, rejected = validate_matches([rec])
    assert not valid and "date" in rejected[0]["reasons"]