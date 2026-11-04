from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import config

_FORMAT_MAP = {"test": "Test", "odi": "ODI", "t20": "T20"}


class InningScore(BaseModel):
    """One innings: runs / wickets / overs (e.g. 187/5 in 20 overs)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    r: int = Field(ge=0, le=1000, description="Runs scored")
    w: int = Field(ge=0, le=config.MAX_WICKETS, description="Wickets lost")
    o: float = Field(ge=0, le=250, description="Overs faced, cricket notation (19.4 = 19 overs 4 balls)")
    inning: str = Field(min_length=3, description="Label such as 'India Inning 1'")

    @field_validator("o")
    @classmethod
    def balls_part_must_be_0_to_5(cls, v: float) -> float:
        balls = round((v - int(v)) * 10)
        if balls > 5:
            raise ValueError(f"invalid overs '{v}': an over has only 6 balls (.0 to .5)")
        return v


class TeamInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    shortname: str | None = None


class RawMatch(BaseModel):
    """A match exactly as the /matches endpoint describes it."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: UUID
    name: str = Field(min_length=3)
    matchType: str
    status: str = ""
    venue: str | None = None
    date: dt.date
    dateTimeGMT: dt.datetime | None = None
    teams: list[str] = Field(default_factory=list)
    teamInfo: list[TeamInfo] = Field(default_factory=list)
    score: list[InningScore] = Field(default_factory=list)
    series_id: UUID | None = None
    matchStarted: bool = False
    matchEnded: bool = False
    tossWinner: str | None = None
    tossChoice: str | None = None
    matchWinner: str | None = None

    @field_validator("matchType", mode="before")
    @classmethod
    def standardise_format(cls, v) -> str:
        """'odi' / 'ODI ' / 'Odi' -> 'ODI'; anything unknown -> 'Other'."""
        return _FORMAT_MAP.get(str(v).strip().lower(), "Other")

    @field_validator("teams")
    @classmethod
    def drop_blank_teams(cls, v: list[str]) -> list[str]:
        return [t.strip() for t in v if t and t.strip()]

    @field_validator("date")
    @classmethod
    def date_within_api_coverage(cls, v: dt.date) -> dt.date:
        if v.year < config.FIRST_CRICKET_YEAR:
            raise ValueError(f"date {v} is before API coverage ({config.FIRST_CRICKET_YEAR})")
        return v

    @model_validator(mode="after")
    def business_rules(self) -> "RawMatch":
        if self.matchEnded:
            if len(set(self.teams)) != 2:
                raise ValueError("a completed match must have exactly two distinct teams")
            if self.date > dt.date.today():
                raise ValueError("a completed match cannot have a future date")
        return self


class RawSeries(BaseModel):
    """A series/tournament from the /series endpoint."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: UUID
    name: str = Field(min_length=2)
    startDate: str | None = None
    endDate: str | None = None
    odi: int = Field(default=0, ge=0)
    t20: int = Field(default=0, ge=0)
    test: int = Field(default=0, ge=0)
    squads: int = Field(default=0, ge=0)
    matches: int = Field(default=0, ge=0)


def _validate(model: type[BaseModel], records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run every record through `model`. Returns (valid_dicts, rejected_rows)."""
    valid: list[dict] = []
    rejected: list[dict] = []
    for rec in records:
        try:
            valid.append(model.model_validate(rec).model_dump(mode="python"))
        except ValidationError as exc:
            reasons = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'record'}: {err['msg']}"
                for err in exc.errors()
            )
            rejected.append({"id": rec.get("id"), "name": rec.get("name"), "reasons": reasons})
    return valid, rejected


def validate_matches(records: list[dict]) -> tuple[list[dict], list[dict]]:
    return _validate(RawMatch, records)


def validate_series(records: list[dict]) -> tuple[list[dict], list[dict]]:
    return _validate(RawSeries, records)