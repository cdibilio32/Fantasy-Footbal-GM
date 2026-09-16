#!/usr/bin/env python3
"""
Waiver-wire proposal deep agent.

Usage:
    python waiver_agent.py [--league ID --team ID] [--week N]

With no --league/--team, runs against every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID
pair found in .env.

See CLAUDE.md at the repo root for when this agent should be run.
"""

from __future__ import annotations

import argparse

from deepagents import create_deep_agent
from langchain_core.tools import tool

from common import format_available_players, format_roster, get_model, print_header, resolve_leagues
from espn_service import ESPNServiceError, espn

SYSTEM_PROMPT = """You are a fantasy football waiver-wire and free-agency analyst for one team's manager.

Before analyzing anything, call get_my_roster_and_waivers to pull the real roster and the top \
available free agents by position. Never invent a player or an ownership/FAAB number.

This is a waiver/free-agency-only review — do not evaluate this week's starting lineup or propose \
trades.

FOCUS AREAS, IN ORDER:
1. Separate opportunity from box score for every candidate: snap share, target share, and \
red-zone/goal-line touches move 1-2 weeks before points catch up. Prefer players whose role is \
outrunning their production (buy-low) over players whose production is outrunning their role \
(touchdown-dependent, likely to regress). Use web search for current snap-share/target-share/role \
news the roster data alone won't show.
2. For streaming positions (QB/TE/D-ST/K), only recommend a swap when the available option has a \
clearer role AND a better matchup than the incumbent this specific week — never justify a stream by \
pointing at last week's points alone.
3. Size every FAAB recommendation as a percentage of remaining budget, not a raw dollar figure, and \
scale it to season stage: be aggressive (40-80%, even higher for a true league-winner) on a clear \
early-season breakout when budgets are deep; tighten toward proven, role-secure players and keep a \
reserve (roughly 20-25% of original budget) unspent past the season's midpoint for injury-driven \
opportunities. Modest depth adds should cost a small fraction of the budget; D/ST and K streams \
should cost close to nothing. If you can't tell whether the league uses FAAB or rolling waiver \
priority, give the recommendation in percentage-of-budget terms and also note the priority-league \
alternative (worth burning your priority slot, or let it ride).
4. Before naming any drop candidate, check: bye-week collisions with other roster pieces, IR-slot \
eligibility (an injured stash that qualifies for IR shouldn't cost a bench spot), handcuff value (a \
backup to a rostered starter has spike value beyond his raw projection), and positional depth floor \
(don't recommend dropping the last viable bench body at a scarce position like RB/TE even if his \
projection is low).
5. Get ahead of bye weeks and IR-eligible returns 1-2 weeks before they hit rather than reacting the \
week of — note any bye/IR need visible for the next two weeks even if you're not acting on it yet.
6. Justify every recommendation with the opportunity/role/matchup reasoning behind it, not the \
player's last game alone.

RESPONSE FORMAT — use this exact structure for every add, ranked by priority (highest first):
"ADD [Player Name] ([Position]) - [opportunity/role/matchup reason] - FAAB: [X]% of remaining budget \
(or "claim, worth your priority slot" / "let it ride" for priority leagues)
DROP [Player Name] ([Position]) - [why he clears the bye/IR/handcuff/depth-floor checks above]"

If a position has no priority add this week, say so explicitly rather than forcing a claim."""


def build_tools(league_id: str, team_id: str):
    @tool
    def get_my_roster_and_waivers() -> str:
        """Get the user's roster (starters/bench/IR) plus the top available free agents by position, all with this week's projections and ownership %."""
        try:
            data = espn.get_my_roster_with_top_waivers(league_id, team_id)
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        return format_roster(data) + "\n\n" + format_available_players(data["availablePlayers"])

    return [get_my_roster_and_waivers]


def run(league_id: str, team_id: str, league_name: str, week: int) -> str:
    tools = build_tools(league_id, team_id)
    agent = create_deep_agent(model=get_model(), tools=tools, system_prompt=SYSTEM_PROMPT, name="waiver_agent")
    task = (
        f"Recommend waiver-wire adds/drops for my team (ESPN Team ID {team_id}) in \"{league_name}\", "
        f"week {week}. Start by calling get_my_roster_and_waivers."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    return result["messages"][-1].content


def main() -> None:
    parser = argparse.ArgumentParser(description="Waiver-wire proposal deep agent")
    parser.add_argument("--league", help="ESPN league ID (overrides .env)")
    parser.add_argument("--team", help="ESPN team ID (overrides .env)")
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    args = parser.parse_args()

    leagues = resolve_leagues(args.league, args.team)
    week = args.week or espn.get_current_week(leagues[0]["leagueId"])

    for league in leagues:
        print_header("WAIVER AGENT", league["name"], week)
        output = run(league["leagueId"], league["teamId"], league["name"], week)
        print(output)


if __name__ == "__main__":
    main()
