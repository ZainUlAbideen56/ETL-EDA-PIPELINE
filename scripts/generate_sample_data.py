from __future__ import annotations

import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
NS = uuid.UUID("12345678-1234-5678-1234-567812345678")
rng = np.random.default_rng(42)

MEN = {"India": "IND", "Pakistan": "PAK", "Australia": "AUS", "England": "ENG", "South Africa": "SA",
       "New Zealand": "NZ", "Sri Lanka": "SL", "Bangladesh": "BAN", "West Indies": "WI", "Afghanistan": "AFG"}
WOMEN = {"India Women": "INDW", "Australia Women": "AUSW", "England Women": "ENGW", "Pakistan Women": "PAKW"}
SHORT = {**MEN, **WOMEN}
VENUES = [
    "Gaddafi Stadium, Lahore", "National Stadium, Karachi", "Rawalpindi Cricket Stadium, Rawalpindi",
    "Melbourne Cricket Ground, Melbourne", "Eden Gardens, Kolkata", "Lord's, London",
    "Newlands, Cape Town", "Wankhede Stadium, Mumbai", "Dubai International Cricket Stadium, Dubai",
    "Galle International Stadium, Galle", "Sher-e-Bangla National Stadium, Dhaka",
    "Eden Park, Auckland", "Sabina Park, Kingston", "Sydney Cricket Ground, Sydney",
]
CFG = {"T20": (20, 160, 32, 260), "ODI": (50, 270, 55, 420)}


def overs(lo: int, hi: int) -> float:
    return round(int(rng.integers(lo, hi)) + int(rng.integers(0, 6)) / 10, 1)


def limited_overs(fmt: str, a: str, b: str):
    max_o, mu, sd, cap = CFG[fmt]
    r1 = int(np.clip(rng.normal(mu, sd), 70, cap))
    w1 = int(rng.integers(2, 11))
    o1 = overs(int(max_o * .6), max_o) if w1 == 10 else float(max_o)
    potential = rng.normal(mu, sd)
    if potential > r1:                           
        r2, w2 = r1 + int(rng.integers(1, 7)), int(rng.integers(0, 10))
        o2 = overs(int(max_o * .5), max_o)
        status = f"{b} won by {10 - w2} wickets"
    else:
        r2 = int(np.clip(potential, 30, r1 - 1))
        w2 = int(rng.choice([10, int(rng.integers(3, 10))], p=[.6, .4]))
        o2 = overs(int(max_o * .5), max_o) if w2 == 10 else float(max_o)
        status = f"{a} won by {r1 - r2} runs"
    return [(a, 1, r1, w1, o1), (b, 1, r2, w2, o2)], status


def test_match(a: str, b: str):
    kind = rng.choice(["innings", "runs", "wickets", "draw"], p=[.25, .2, .25, .3])
    n = lambda mu, sd: int(np.clip(rng.normal(mu, sd), 60, 650))
    A1, B1, B2 = n(330, 90), n(260, 80), n(230, 70)
    ov = lambda: overs(70, 150)
    if kind == "innings":
        A1 = B1 + B2 + int(rng.integers(5, 250))
        return [(a, 1, A1, 10, ov()), (b, 1, B1, 10, ov()), (b, 2, B2, 10, ov())], \
            f"{a} won by an innings and {A1 - B1 - B2} runs"
    A2 = n(250, 80)
    if kind == "runs":
        A2 = max(30, B1 + B2 + int(rng.integers(5, 300)) - A1)
        return [(a, 1, A1, 10, ov()), (b, 1, B1, 10, ov()), (a, 2, A2, 10, ov()), (b, 2, B2, 10, ov())], \
            f"{a} won by {A1 + A2 - B1 - B2} runs"
    if kind == "wickets":
        target = A1 + A2 - B1
        B2 = target + int(rng.integers(1, 7)); w = int(rng.integers(0, 10))
        return [(a, 1, A1, 10, ov()), (b, 1, B1, 10, ov()), (a, 2, A2, 10, ov()), (b, 2, B2, w, ov())], \
            f"{b} won by {10 - w} wickets"
    return [(a, 1, A1, 10, ov()), (b, 1, B1, 10, ov()), (a, 2, A2, 7, ov()), (b, 2, min(B2, 180), 4, ov())], \
        "Match drawn"


def build_match(i: int, series_ids: list[str]) -> dict:
    fmt = str(rng.choice(["T20", "ODI", "Test"], p=[.5, .3, .2]))
    pool = WOMEN if (fmt != "Test" and rng.random() < .15) else MEN
    a, b = rng.choice(list(pool), 2, replace=False)
    a, b = str(a), str(b)
    innings, status = test_match(a, b) if fmt == "Test" else limited_overs(fmt, a, b)
    d = date(2018, 1, 1) + timedelta(days=int(rng.integers(0, 365 * 8)))
    toss = fmt != "Test" or rng.random() < .8
    rec = {
        "id": str(uuid.uuid5(NS, f"match-{i}")),
        "name": f"{a} vs {b}, {['1st', '2nd', '3rd'][int(rng.integers(0, 3))]} {fmt}",
        "matchType": fmt.lower(),
        "status": status,
        "venue": str(rng.choice(VENUES)),
        "date": d.isoformat(),
        "dateTimeGMT": f"{d.isoformat()}T09:30:00",
        "teams": [a, b],
        "teamInfo": [{"name": a, "shortname": SHORT[a]}, {"name": b, "shortname": SHORT[b]}],
        "score": [{"r": r, "w": w, "o": o, "inning": f"{t} Inning {k}"} for t, k, r, w, o in innings],
        "series_id": series_ids[int(rng.integers(0, len(series_ids)))],
        "matchStarted": True,
        "matchEnded": True,
    }
    if toss:
        rec["tossWinner"] = str(rng.choice([a, b]))
        rec["tossChoice"] = str(rng.choice(["bat", "bowl"]))
    return rec


def main(n_matches: int = 400) -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    series = [{"id": str(uuid.uuid5(NS, f"series-{k}")), "name": f"Sample Series {k + 1}",
               "startDate": f"{2018 + k % 8}-01-10", "endDate": f"{2018 + k % 8}-02-20",
               "odi": 3, "t20": 3, "test": 2, "squads": 4, "matches": 8} for k in range(12)]
    ids = [s["id"] for s in series]
    matches = [build_match(i, ids) for i in range(n_matches)]

    bad = []
    r = build_match(9001, ids); r["id"] = "not-a-guid"; bad.append(r)
    r = build_match(9002, ids); r["score"][0]["w"] = 11; bad.append(r)
    r = build_match(9003, ids); r["score"][0]["o"] = 19.7; bad.append(r)
    r = build_match(9004, ids); r["teams"] = ["India"]; bad.append(r)
    r = build_match(9005, ids); del r["date"]; bad.append(r)
    r = build_match(9006, ids); r["score"][1]["r"] = -5; bad.append(r)
    r = build_match(9007, ids); r["date"] = "1995-03-01"; bad.append(r)
    r = build_match(9008, ids); r["date"] = (date.today() + timedelta(days=60)).isoformat(); bad.append(r)
    duplicate = dict(matches[10])                       
    upcoming = build_match(9009, ids); upcoming.update(matchEnded=False, matchStarted=False, score=[],
                                                       status="Match not started")
    allm = matches + bad + [duplicate, upcoming]

    (SAMPLE_DIR / "matches_sample.json").write_text(json.dumps(allm, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "series_sample.json").write_text(json.dumps(series, indent=2), encoding="utf-8")
    print(f"Wrote {len(allm)} synthetic matches ({len(bad)} intentionally invalid) to {SAMPLE_DIR}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
