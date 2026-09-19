"""
Shared plumbing for the three fantasy-football deep agents (trade_agent.py,
waiver_agent.py, lineup_agent.py): the OpenRouter-backed model, league
resolution from env vars, and small formatting helpers the agents' tools
use to turn espn_service data into prompt-ready text.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

MEMORIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memories.md")


def get_model() -> ChatOpenAI:
    """
    The single LLM every agent uses: whatever model OPENROUTER_MODEL names,
    called through OpenRouter. OpenRouter's hosted `web` plugin is enabled
    on every call so the model can pull in current injury/weather/Vegas-line
    context itself — no separate web-search tool or provider needed.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set — copy .env.example to .env and fill it in.")
    return ChatOpenAI(
        model=os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash"),
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=api_key,
        temperature=0.7,
        extra_body={"plugins": [{"id": "web"}]},
    )


def resolve_leagues(league_arg: str | None, team_arg: str | None) -> list[dict[str, str]]:
    """
    Leagues to run the agent against. Either a single --league/--team pair,
    or every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID / LEAGUE_<N>_NAME triple
    found in the environment (supports multiple leagues, same as before).
    """
    if league_arg and team_arg:
        return [{"leagueId": league_arg, "teamId": team_arg, "name": os.environ.get("LEAGUE_NAME", "My League")}]

    leagues = []
    n = 1
    while True:
        league_id = os.environ.get(f"LEAGUE_{n}_ID")
        team_id = os.environ.get(f"LEAGUE_{n}_TEAM_ID")
        if not (league_id and team_id):
            break
        leagues.append({"leagueId": league_id, "teamId": team_id, "name": os.environ.get(f"LEAGUE_{n}_NAME", f"League {n}")})
        n += 1

    if not leagues:
        raise RuntimeError(
            "No league configured. Pass --league/--team, or set LEAGUE_1_ID/LEAGUE_1_TEAM_ID (and "
            "optionally LEAGUE_1_NAME) in .env."
        )
    return leagues


def get_current_week_words(week: int) -> str:
    return str(week)


def load_memories() -> str:
    """
    Standing preferences/corrections accumulated from past user feedback
    (written by the `remember-feedback` Claude Code skill) so every agent
    run applies what you've already told it, not just the current roster
    snapshot.
    """
    if not os.path.exists(MEMORIES_PATH):
        return ""
    content = open(MEMORIES_PATH, encoding="utf-8").read().strip()
    if not content:
        return ""
    return f"\n\nLEARNED PREFERENCES (from your past feedback — apply these when making recommendations):\n{content}\n"


def build_system_prompt(base_prompt: str) -> str:
    """Every agent's system prompt, with memories.md appended."""
    return base_prompt + load_memories()


def format_player_line(p: dict[str, Any]) -> str:
    proj = p.get("projectedPoints", 0)
    season = p.get("seasonProjectedPoints", 0)
    season_note = f" | season total {season} pts" if season and abs(season - proj) > 10 else ""
    injury = f" | INJURY: {p['injuryStatus']}" if p.get("injuryStatus") else ""

    prev_year = p.get("seasonPointsPreviousYear", 0)
    prev_year_note = f" | last year: {prev_year} season pts" if prev_year else ""

    weekly = p.get("weeklyPoints") or {}
    weekly_note = ""
    if weekly:
        recent_weeks = sorted(weekly.items())[-4:]  # last few played weeks, not the whole season, to keep prompts tight
        weekly_note = " | this season by week: " + ", ".join(f"wk{wk} {pts}" for wk, pts in recent_weeks)

    return (
        f"- {p['fullName']} ({p['position']}, {p.get('team', 'FA')}) — "
        f"{proj} proj pts this week{season_note}{prev_year_note}{weekly_note} | {p.get('percentOwned', 0)}% owned | "
        f"{p.get('percentStarted', 0)}% started{injury}"
    )


def format_roster(roster: dict[str, Any]) -> str:
    lines = [f"TEAM: {roster.get('teamName', 'My Team')}", "", "STARTERS:"]
    lines += [format_player_line(p) for p in roster.get("starters", [])] or ["(none)"]
    lines += ["", "BENCH:"]
    lines += [format_player_line(p) for p in roster.get("bench", [])] or ["(none)"]
    ir = roster.get("injuredReserve", [])
    if ir:
        lines += ["", "INJURED RESERVE:"]
        lines += [format_player_line(p) for p in ir]
    return "\n".join(lines)


def format_available_players(available: dict[str, list[dict[str, Any]]]) -> str:
    lines = ["AVAILABLE WAIVER WIRE / FREE AGENT PLAYERS BY POSITION:"]
    for position, players in available.items():
        lines.append(f"\n{position}:")
        lines += [format_player_line(p) for p in players] or ["  (none available)"]
    return "\n".join(lines)


def format_other_teams(other_teams: list[dict[str, Any]]) -> str:
    lines = [
        "OTHER TEAMS IN THE LEAGUE (real trade partners — when you propose a trade, name one of "
        "these teams, including its ESPN Team ID, and one of its ACTUAL rostered players below, "
        "copied verbatim. Never a hypothetical player, and never a player from the waiver/free-agent "
        "list — those are unrostered and cannot be traded for.)"
    ]
    for team in other_teams:
        lines.append(f"\nTeam \"{team['teamName']}\" (ESPN Team ID {team['teamId']}):")
        by_position: dict[str, list[dict[str, Any]]] = {}
        for p in team["starters"] + team["bench"]:
            by_position.setdefault(p["position"], []).append(p)
        for position, players in sorted(by_position.items()):
            top = sorted(players, key=lambda p: p["seasonPoints"], reverse=True)[:3]
            names = ", ".join(
                f"{p['fullName']} ({p['seasonPoints']} season pts, last year {p.get('seasonPointsPreviousYear', 0)}, {p['percentOwned']}% owned)"
                for p in top
            )
            lines.append(f"  {position} ({len(players)} rostered): {names}")
    return "\n".join(lines)


def print_header(agent_name: str, league_name: str, week: int) -> None:
    print(f"\n{'=' * 70}\n{agent_name} — {league_name} (Week {week})\n{'=' * 70}\n")
