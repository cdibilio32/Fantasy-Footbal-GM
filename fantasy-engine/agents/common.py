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
        model=os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash"),
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=api_key,
        temperature=0.7,
        # Hidden-reasoning models can burn an entire token budget on invisible
        # reasoning and return zero visible content (finish_reason "length",
        # completion made entirely of reasoning tokens) on the trade agent's
        # longer, multi-step prompts — verified live. Capping reasoning well
        # under the overall budget guarantees room left for the actual answer.
        max_tokens=16000,
        extra_body={"plugins": [{"id": "web"}], "reasoning": {"max_tokens": 6000}},
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


TOOL_GUARDRAIL = (
    "\n\nYou have access to filesystem tools (ls, read_file, write_file, grep, etc.) and a task/"
    "subagent tool as part of the deep-agent framework you're running in — this task doesn't need "
    "them. There are no useful files to read and no reason to write or search any. Go straight to "
    "your named data tools (get_my_roster, etc.) and, once you've called them, answer directly — "
    "don't explore the filesystem first."
)


def build_system_prompt(base_prompt: str) -> str:
    """Every agent's system prompt, with the filesystem-tool guardrail and memories.md appended."""
    return base_prompt + TOOL_GUARDRAIL + load_memories()


def format_player_line(p: dict[str, Any]) -> str:
    proj = p.get("projectedPoints", 0)
    season = p.get("seasonProjectedPoints", 0)
    season_note = f" | season total proj {season} pts" if season and abs(season - proj) > 10 else ""
    injury = f" | INJURY: {p['injuryStatus']}" if p.get("injuryStatus") else ""

    to_date = p.get("seasonPointsToDate", 0)
    to_date_note = f" | {to_date} pts to date this season" if to_date else ""

    prev_year = p.get("seasonPointsPreviousYear", 0)
    prev_year_note = f" | last year: {prev_year} season pts" if prev_year else ""

    weekly = p.get("weeklyPoints") or {}
    weekly_note = ""
    if weekly:
        recent_weeks = sorted(weekly.items())[-4:]  # last few played weeks, not the whole season, to keep prompts tight
        weekly_note = " | this season by week: " + ", ".join(f"wk{wk} {pts}" for wk, pts in recent_weeks)

    return (
        f"- {p['fullName']} ({p['position']}, {p.get('team', 'FA')}) — "
        f"{proj} proj pts this week{to_date_note}{season_note}{prev_year_note}{weekly_note} | "
        f"{p.get('percentOwned', 0)}% owned | {p.get('percentStarted', 0)}% started{injury}"
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


def _injury_note(p: dict[str, Any]) -> str:
    status = p.get("injuryStatus")
    return f", INJURY: {status}" if status and status.upper() != "ACTIVE" else ""


def format_other_teams(other_teams: list[dict[str, Any]]) -> str:
    lines = [
        "OTHER TEAMS IN THE LEAGUE (real trade partners — when you propose a trade, name one of "
        "these teams, including its ESPN Team ID, and one of its ACTUAL rostered players below, "
        "copied verbatim. Never a hypothetical player, and never a player from the waiver/free-agent "
        "list — those are unrostered and cannot be traded for.)"
    ]
    for team in other_teams:
        owners = f", owned by {' & '.join(team['ownerNames'])}" if team.get("ownerNames") else ""
        lines.append(f"\nTeam \"{team['teamName']}\" (ESPN Team ID {team['teamId']}{owners}):")
        by_position: dict[str, list[dict[str, Any]]] = {}
        for p in team["starters"] + team["bench"]:
            by_position.setdefault(p["position"], []).append(p)
        for position, players in sorted(by_position.items()):
            top = sorted(players, key=lambda p: p.get("seasonPointsToDate", 0), reverse=True)[:3]
            names = ", ".join(
                f"{p['fullName']} ({p.get('seasonPointsToDate', 0)} pts to date, season proj {p['seasonPoints']}, "
                f"last year {p.get('seasonPointsPreviousYear', 0)}, {p['percentOwned']}% owned{_injury_note(p)})"
                for p in top
            )
            lines.append(f"  {position} ({len(players)} rostered): {names}")
    return "\n".join(lines)


def print_header(agent_name: str, league_name: str, week: int) -> None:
    print(f"\n{'=' * 70}\n{agent_name} — {league_name} (Week {week})\n{'=' * 70}\n")
