"""
ESPN Fantasy Football data service.

A thin, dependency-free (besides `requests`) client around ESPN's private
fantasy football read API. Each public method below is a data "endpoint"
the three LangGraph deep agents (trade_agent, waiver_agent, lineup_agent)
call as tools — see AGENT_ENDPOINTS at the bottom of this file for the map
of which endpoints each agent uses.

Auth: ESPN private leagues require two cookies, read from the environment:
  ESPN_S2    - long session token
  ESPN_SWID  - user id, in curly braces, e.g. "{XXXXXXXX-XXXX-...}"
Get both from a browser's dev tools (Application -> Cookies) after logging
into fantasy.espn.com. Public leagues work without them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

# --- Position / lineup-slot mappings (ESPN's numeric IDs -> names) ---------

PLAYER_POSITIONS: dict[int, str] = {
    0: "QB", 1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST",
    6: "DT", 7: "DE", 8: "LB", 9: "DL", 10: "CB", 11: "S", 12: "DB", 13: "DP",
    14: "P", 15: "HC",
}

LINEUP_SLOT_NAMES: dict[int, str] = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE",
    7: "OP", 8: "DT", 9: "DE", 10: "LB", 11: "DL", 12: "CB", 13: "S",
    14: "DB", 15: "DP", 16: "D/ST", 17: "K", 18: "P", 19: "HC",
    20: "BENCH", 21: "IR", 22: "RESERVED", 23: "FLEX", 24: "UTIL",
    25: "SUPER_FLEX",
}

BENCH_SLOT = 20
IR_SLOT = 21
RESERVED_SLOT = 22

PRO_TEAM_ABBREVIATIONS: dict[int, str] = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA",
    27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}


def _is_starting_slot(slot_id: int) -> bool:
    return slot_id not in (BENCH_SLOT, IR_SLOT, RESERVED_SLOT) and slot_id in LINEUP_SLOT_NAMES


def _is_bench_slot(slot_id: int) -> bool:
    return slot_id == BENCH_SLOT


def _is_ir_slot(slot_id: int) -> bool:
    return slot_id == IR_SLOT


@dataclass
class Player:
    id: str
    full_name: str
    position: str
    pro_team: str
    points: float = 0.0
    projected_points: float = 0.0
    season_projected_points: float = 0.0
    season_points_to_date: float = 0.0
    season_points_previous_year: float = 0.0
    weekly_points: dict[int, float] = field(default_factory=dict)
    injury_status: str | None = None
    percent_started: float = 0.0
    percent_owned: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fullName": self.full_name,
            "position": self.position,
            "team": self.pro_team,
            "points": round(self.points, 1),
            "projectedPoints": round(self.projected_points, 1),
            "seasonProjectedPoints": round(self.season_projected_points, 1),
            "seasonPointsToDate": round(self.season_points_to_date, 1),
            "seasonPointsPreviousYear": round(self.season_points_previous_year, 1),
            "weeklyPoints": {week: round(pts, 1) for week, pts in sorted(self.weekly_points.items())},
            "injuryStatus": self.injury_status,
            "percentStarted": round(self.percent_started, 1),
            "percentOwned": round(self.percent_owned, 1),
        }


@dataclass
class TeamRoster:
    team_id: int
    team_name: str
    starters: list[Player] = field(default_factory=list)
    bench: list[Player] = field(default_factory=list)
    injured_reserve: list[Player] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "teamId": self.team_id,
            "teamName": self.team_name,
            "starters": [p.to_dict() for p in self.starters],
            "bench": [p.to_dict() for p in self.bench],
            "injuredReserve": [p.to_dict() for p in self.injured_reserve],
        }


class ESPNServiceError(RuntimeError):
    """Raised for any ESPN API failure, with a message safe to show an LLM."""


class ESPNService:
    """
    ESPN Fantasy Football read-only data service.

    Every method is one "endpoint": a focused call that returns exactly the
    shape of data one of the three agents needs, so a tool call never drags
    in an entire raw ESPN payload.
    """

    def __init__(self, season_year: int | None = None) -> None:
        self.season_year = season_year or int(os.environ.get("ESPN_SEASON_YEAR", "2025"))
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
        )
        espn_s2 = os.environ.get("ESPN_S2")
        espn_swid = os.environ.get("ESPN_SWID")
        if espn_s2 and espn_swid:
            self._session.headers["Cookie"] = f"espn_s2={espn_s2}; SWID={espn_swid}"
        self._week_cache: dict[str, int] = {}
        self._weekly_points_cache: dict[str, dict[str, dict[int, float]]] = {}

    # -- current week -------------------------------------------------------

    def get_current_week(self, league_id: str | None = None) -> int:
        """
        NFL scoring-period ("week") ESPN itself considers current. Asks ESPN
        directly when a league_id is given (authoritative — ESPN's own week
        rollover doesn't line up cleanly with a fixed day offset from
        kickoff), falling back to a Labor-Day-based estimate only if that
        call fails (e.g. no league configured yet).
        """
        if league_id is not None:
            cached = self._week_cache.get(str(league_id))
            if cached is not None:
                return cached
            try:
                data = self._get(str(league_id), params={"view": "mStatus"})
                week = data.get("scoringPeriodId") or data.get("status", {}).get("currentMatchupPeriod")
                if week:
                    self._week_cache[str(league_id)] = int(week)
                    return int(week)
            except ESPNServiceError:
                pass
        return self._estimate_week_from_date()

    def _estimate_week_from_date(self) -> int:
        """Fallback only: estimates the week from the Thursday after Labor Day."""
        import datetime

        sept1 = datetime.date(self.season_year, 9, 1)
        days_until_monday = (0 - sept1.weekday()) % 7  # Monday == 0
        labor_day = sept1 + datetime.timedelta(days=days_until_monday)
        week1_kickoff = labor_day + datetime.timedelta(days=3)
        today = datetime.date.today()
        if today < week1_kickoff:
            return 1
        return min((today - week1_kickoff).days // 7 + 1, 18)

    # -- request plumbing -----------------------------------------------------

    def _get(self, path: str, params: dict | None = None, extra_headers: dict | None = None) -> Any:
        url = f"{BASE_URL}/seasons/{self.season_year}/segments/0/leagues/{path}"
        try:
            resp = self._session.get(url, params=params, headers=extra_headers, timeout=20)
        except requests.RequestException as exc:
            raise ESPNServiceError(f"ESPN network error calling {url}: {exc}") from exc

        if resp.status_code == 401:
            raise ESPNServiceError(
                "ESPN authentication failed (401): ESPN_S2/ESPN_SWID cookies are missing, invalid, or expired."
            )
        if resp.status_code == 403:
            raise ESPNServiceError(f"ESPN access forbidden (403) for {url}: check league privacy / cookies.")
        if resp.status_code == 404:
            raise ESPNServiceError(f"ESPN resource not found (404): {url}")
        if not resp.ok:
            raise ESPNServiceError(f"ESPN API error ({resp.status_code}) for {url}: {resp.text[:300]}")

        if resp.text.strip().startswith("<"):
            raise ESPNServiceError("ESPN returned an HTML login page instead of JSON — cookies are invalid/expired.")

        return resp.json()

    def _position_name(self, position_id: int) -> str:
        return PLAYER_POSITIONS.get(position_id, f"UNKNOWN_POS_{position_id}")

    def _pro_team(self, team_id: int) -> str:
        return PRO_TEAM_ABBREVIATIONS.get(team_id, "FA")

    def _build_player(self, entry_or_player: dict, current_week: int, weekly_points_by_id: dict[str, dict[int, float]] | None = None) -> Player:
        player_data = entry_or_player.get("playerPoolEntry", {}).get("player") or entry_or_player.get("player") or entry_or_player
        stats = player_data.get("stats", [])

        weekly_projection = 0.0
        season_total = 0.0
        season_total_previous_year = 0.0
        season_total_to_date = 0.0
        actual_points = 0.0

        weekly_stat = next(
            (s for s in stats if s.get("statSourceId") == 1 and s.get("scoringPeriodId") == current_week), None
        )
        if weekly_stat:
            weekly_projection = weekly_stat.get("appliedTotal") or 0.0
        else:
            projection_stats = sorted(
                (s for s in stats if s.get("statSourceId") == 1 and (s.get("appliedTotal") or 0) > 0),
                key=lambda s: s["appliedTotal"],
            )
            if projection_stats:
                smallest = projection_stats[0]["appliedTotal"]
                if smallest < 50:
                    weekly_projection = smallest
                else:
                    largest = projection_stats[-1]["appliedTotal"]
                    weekly_projection = largest / 17

        actual_stat = next(
            (s for s in stats if s.get("statSourceId") == 0 and s.get("scoringPeriodId") == current_week), None
        )
        if actual_stat:
            actual_points = actual_stat.get("appliedTotal") or 0.0

        season_stat = next(
            (s for s in stats if s.get("statSourceId") == 1 and not s.get("scoringPeriodId")), None
        )
        if season_stat:
            season_total = season_stat.get("appliedTotal") or 0.0

        # Previous season's actual total — ESPN bundles this into the same
        # `stats` array as the current season's data, no extra request needed.
        previous_year_stat = next(
            (
                s
                for s in stats
                if s.get("statSourceId") == 0 and not s.get("scoringPeriodId") and s.get("seasonId") == self.season_year - 1
            ),
            None,
        )
        if previous_year_stat:
            season_total_previous_year = previous_year_stat.get("appliedTotal") or 0.0

        # This season's actual cumulative total so far (distinct from
        # season_projected_points, which is a projection, not what's
        # actually been scored yet).
        to_date_stat = next(
            (
                s
                for s in stats
                if s.get("statSourceId") == 0 and not s.get("scoringPeriodId") and s.get("seasonId") == self.season_year
            ),
            None,
        )
        if to_date_stat:
            season_total_to_date = to_date_stat.get("appliedTotal") or 0.0

        position = self._position_name(player_data.get("defaultPositionId", 0))
        weekly_max = {"QB": 50, "RB": 40, "WR": 40, "TE": 30, "D/ST": 35, "K": 25}.get(position, 35)
        looks_seasonal = season_total > 0 and weekly_projection > 0 and (weekly_projection / season_total * 100) > 30
        if weekly_projection > weekly_max and (looks_seasonal or weekly_projection > 100):
            if season_total == 0:
                season_total = weekly_projection
            weekly_projection = weekly_projection / 17
        weekly_projection = min(weekly_projection, 200)

        player_id = str(player_data.get("id", ""))
        return Player(
            id=player_id,
            full_name=player_data.get("fullName", "Unknown Player"),
            position=position,
            pro_team=self._pro_team(player_data.get("proTeamId", 0)),
            points=actual_points,
            projected_points=weekly_projection if weekly_projection > 0 else (season_total / 17 if season_total else 0.0),
            season_projected_points=season_total,
            season_points_to_date=season_total_to_date,
            season_points_previous_year=season_total_previous_year,
            weekly_points=(weekly_points_by_id or {}).get(player_id, {}),
            injury_status=player_data.get("injuryStatus"),
            percent_started=(player_data.get("ownership") or {}).get("percentStarted", 0.0),
            percent_owned=(player_data.get("ownership") or {}).get("percentOwned", 0.0),
        )

    def _get_weekly_points_by_player(self, league_id: str) -> dict[str, dict[int, float]]:
        """
        Actual fantasy points per rostered player, per completed week of the
        current season — e.g. {"4374302": {1: 8.5, 2: 39.2}}. Each roster
        request only returns a 2-week trailing window around the requested
        `scoringPeriodId`, so this strides by 2 (week 2 covers weeks 1-2,
        week 4 covers weeks 3-4, ...) to cover every played week in the
        fewest requests, and caches the result per league for this
        process's lifetime.
        """
        cached = self._weekly_points_cache.get(str(league_id))
        if cached is not None:
            return cached

        current_week = self.get_current_week(league_id)
        weeks_to_request: list[int] = list(range(2, current_week + 1, 2))
        if not weeks_to_request or weeks_to_request[-1] != current_week:
            weeks_to_request.append(current_week)

        result: dict[str, dict[int, float]] = {}
        for week in weeks_to_request:
            data = self._get(str(league_id), params={"view": "mRoster", "scoringPeriodId": week})
            for team in data.get("teams", []):
                for entry in (team.get("roster") or {}).get("entries", []):
                    player_data = entry.get("playerPoolEntry", {}).get("player", {})
                    player_id = str(player_data.get("id", ""))
                    if not player_id:
                        continue
                    for stat in player_data.get("stats", []):
                        if stat.get("statSourceId") == 0 and stat.get("scoringPeriodId"):
                            result.setdefault(player_id, {})[stat["scoringPeriodId"]] = stat.get("appliedTotal") or 0.0

        self._weekly_points_cache[str(league_id)] = result
        return result

    # -- ENDPOINT: league info -------------------------------------------------

    def get_league_info(self, league_id: str) -> dict[str, Any]:
        """League metadata: name, current scoring period, settings, team list."""
        data = self._get(str(league_id))
        return {
            "id": data.get("id"),
            "name": (data.get("settings") or {}).get("name", "Unknown League"),
            "seasonId": data.get("seasonId"),
            "currentWeek": data.get("scoringPeriodId", 1),
            "teams": [{"id": t.get("id"), "name": t.get("name")} for t in data.get("teams", [])],
        }

    # -- ENDPOINT: my team's roster --------------------------------------------

    def get_team_roster(self, league_id: str, team_id: str) -> TeamRoster:
        """Starters / bench / IR for one team, with weekly-reconciled projections."""
        current_week = self.get_current_week(league_id)
        data = self._get(str(league_id), params={"view": "mRoster", "scoringPeriodId": current_week})

        team = next((t for t in data.get("teams", []) if t.get("id") == int(team_id)), None)
        if team is None:
            available = ", ".join(str(t.get("id")) for t in data.get("teams", []))
            raise ESPNServiceError(f"Team {team_id} not found in league {league_id}. Available teams: {available}")

        weekly_points_by_id = self._get_weekly_points_by_player(league_id)

        starters: list[Player] = []
        bench: list[Player] = []
        ir: list[Player] = []

        for entry in (team.get("roster") or {}).get("entries", []):
            player = self._build_player(entry, current_week, weekly_points_by_id)
            slot_id = entry.get("lineupSlotId")

            if _is_ir_slot(slot_id):
                has_real_injury = player.injury_status and player.injury_status.upper() not in ("ACTIVE", "PROBABLE")
                (ir if has_real_injury else bench).append(player)
            elif _is_bench_slot(slot_id):
                bench.append(player)
            elif _is_starting_slot(slot_id):
                starters.append(player)
            else:
                bench.append(player)  # unknown slot -> bench, for safety

        return TeamRoster(team_id=int(team_id), team_name=team.get("name", f"Team {team_id}"), starters=starters, bench=bench, injured_reserve=ir)

    # -- ENDPOINT: every team's roster (trade partners) ------------------------

    def get_league_rosters(self, league_id: str) -> list[dict[str, Any]]:
        """
        Every team's roster in the league (season point totals, not weekly),
        for identifying real trade partners/players instead of hypothetical ones.
        """
        current_week = self.get_current_week(league_id)
        data = self._get(str(league_id), params={"view": ["mRoster", "mTeam"], "scoringPeriodId": current_week})

        results = []
        for team in data.get("teams", []):
            starters: list[dict[str, Any]] = []
            bench: list[dict[str, Any]] = []
            for entry in (team.get("roster") or {}).get("entries", []):
                player_data = entry.get("playerPoolEntry", {}).get("player", {})
                stats = player_data.get("stats", [])
                season_stat = next(
                    (s for s in stats if s.get("statSourceId") == 1 and not s.get("scoringPeriodId")), None
                )
                previous_year_stat = next(
                    (
                        s
                        for s in stats
                        if s.get("statSourceId") == 0 and not s.get("scoringPeriodId") and s.get("seasonId") == self.season_year - 1
                    ),
                    None,
                )
                to_date_stat = next(
                    (
                        s
                        for s in stats
                        if s.get("statSourceId") == 0 and not s.get("scoringPeriodId") and s.get("seasonId") == self.season_year
                    ),
                    None,
                )
                row = {
                    "fullName": player_data.get("fullName", "Unknown Player"),
                    "position": self._position_name(player_data.get("defaultPositionId", 0)),
                    "seasonPoints": round(season_stat.get("appliedTotal", 0.0) if season_stat else 0.0, 1),
                    "seasonPointsToDate": round(to_date_stat.get("appliedTotal", 0.0) if to_date_stat else 0.0, 1),
                    "seasonPointsPreviousYear": round(previous_year_stat.get("appliedTotal", 0.0) if previous_year_stat else 0.0, 1),
                    "percentOwned": round((player_data.get("ownership") or {}).get("percentOwned", 0.0)),
                }
                slot_id = entry.get("lineupSlotId")
                (starters if _is_starting_slot(slot_id) else bench).append(row)

            results.append({"teamId": team.get("id"), "teamName": team.get("name", f"Team {team.get('id')}"), "starters": starters, "bench": bench})
        return results

    # -- ENDPOINT: waiver wire / free agents ------------------------------------

    def get_available_players(self, league_id: str) -> list[Player]:
        """Free agent / waiver-wire players, filtered to those <50% owned."""
        current_week = self.get_current_week(league_id)
        headers = {"X-Fantasy-Filter": '{"players":{"filterStatus":{"value":["FREEAGENT","WAIVERS"]}}}'}
        try:
            data = self._get(str(league_id), params={"view": "kona_player_info", "scoringPeriodId": current_week}, extra_headers=headers)
            players = [self._build_player(p, current_week) for p in data.get("players", [])]
            return [p for p in players if (p.percent_owned or 0) < 50]
        except ESPNServiceError:
            data = self._get(str(league_id), params={"view": "kona_player_info", "scoringPeriodId": current_week})
            players = [self._build_player(p, current_week) for p in data.get("players", [])]
            return [p for p in players if (p.percent_owned or 0) < 95][:200]

    # -- ENDPOINT: my roster + top waiver targets by position -------------------

    def get_my_roster_with_top_waivers(self, league_id: str, team_id: str) -> dict[str, Any]:
        """
        Convenience endpoint combining get_team_roster + get_available_players,
        pre-trimmed to the top N free agents per position (what the lineup and
        waiver agents actually want, instead of the full free-agent pool).
        """
        roster = self.get_team_roster(league_id, team_id)
        available = self.get_available_players(league_id)

        limits = {"QB": 5, "RB": 8, "WR": 8, "TE": 5, "D/ST": 5, "K": 5}
        top_by_position: dict[str, list[dict[str, Any]]] = {}
        for position, limit in limits.items():
            candidates = sorted(
                (p for p in available if p.position == position),
                key=lambda p: p.projected_points or 0,
                reverse=True,
            )[:limit]
            top_by_position[position] = [p.to_dict() for p in candidates]

        return {
            "teamId": roster.team_id,
            "teamName": roster.team_name,
            "starters": [p.to_dict() for p in roster.starters],
            "bench": [p.to_dict() for p in roster.bench],
            "injuredReserve": [p.to_dict() for p in roster.injured_reserve],
            "availablePlayers": top_by_position,
        }

    # -- ENDPOINT: matchups -----------------------------------------------------

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """This week's (or any week's) matchup schedule."""
        data = self._get(str(league_id), params={"view": "mMatchup", "scoringPeriodId": week})
        return data.get("schedule", [])

    # -- ENDPOINT: transactions ---------------------------------------------------

    def get_transactions(self, league_id: str) -> list[dict[str, Any]]:
        """Recent league transactions (adds/drops/trades)."""
        url = f"{BASE_URL}/seasons/{self.season_year}/segments/0/leagues/{league_id}/transactions"
        try:
            resp = self._session.get(url, timeout=20)
        except requests.RequestException as exc:
            raise ESPNServiceError(f"ESPN network error calling {url}: {exc}") from exc
        if not resp.ok:
            raise ESPNServiceError(f"ESPN transactions API error ({resp.status_code}) for {url}")
        return resp.json().get("transactions", [])


espn = ESPNService()


# Which endpoints each of the 3 deep agents actually calls — see common.py's
# build_espn_tools(), which reads this map to attach only the relevant tools.
AGENT_ENDPOINTS: dict[str, list[str]] = {
    "trade": ["get_league_info", "get_team_roster", "get_league_rosters", "get_available_players"],
    "waiver": ["get_league_info", "get_my_roster_with_top_waivers"],
    "lineup": ["get_league_info", "get_team_roster", "get_matchups"],
}
