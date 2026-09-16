#!/usr/bin/env python3
"""
Lineup optimization deep agent.

Usage:
    python lineup_agent.py [--league ID --team ID] [--week N]

With no --league/--team, runs against every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID
pair found in .env. Safe to run any day of the week — it always pulls the
live injury/matchup picture, and tells you how confident to be in each call
based on how much uncertainty is realistically still left before kickoff.

See CLAUDE.md at the repo root for when this agent should be run.
"""

from __future__ import annotations

import argparse

from deepagents import create_deep_agent
from langchain_core.tools import tool

from common import build_system_prompt, format_roster, get_model, print_header, resolve_leagues
from espn_service import ESPNServiceError, espn

SYSTEM_PROMPT = """You are a fantasy football lineup optimizer for one team's manager.

Before analyzing anything, call get_my_roster to pull the real roster, and get_matchups to see \
this week's schedule. Never invent a player, matchup, or injury status.

This is a lineup-only review — do not evaluate waivers or trades here. If you spot an urgent roster \
need only a waiver add could fix, flag it in one line at the end and stop there.

Use web search for anything time-sensitive the roster data alone won't show: injury report status, \
weather, Vegas lines/implied team totals, and snap-share/role news. State explicitly, near the top \
of your answer, how far each affected game is from kickoff — that governs how much weight to put on \
uncertain signals below.

FOCUS AREAS, IN ORDER:
1. Set each matchup's floor-vs-ceiling posture from the OPPONENT's projected/implied team total \
(from Vegas lines you find via search), not their record: a high-scoring projected opponent means \
lean ceiling even with a good record of your own; a low-scoring projected opponent means floor plays \
are safe even for a struggling team.
2. For each position group, compare the current starter to the best bench alternative. Only \
recommend a change when you have strong, multi-signal conviction (bad matchup AND negative game \
script AND weak recent usage) if the game is still multiple days out — one yellow flag that far out \
is a "watch," not a bench. Once a game is close to kickoff (same-day, inactives out), act decisively \
on confirmed information instead of hedging: "out"/"doubtful" is a near-certain sit, and a confirmed \
"active, no game-time decision" should override any earlier hesitation.
3. Treat in-week injury tags conservatively the earlier in the week it is: a "questionable" tag alone \
(historically roughly 75% of these players suit up) is not enough by itself to bench a clearly better \
starter days before kickoff — flag it as a near-kickoff re-check instead of acting on it immediately. \
"Doubtful" is a much stronger signal. Right before kickoff, re-pull the latest status instead of \
trusting an earlier read.
4. Note any rough weather forecast as a watch item when it's still days out (forecasts 3+ days out \
are directional at best); treat a forecast close to kickoff (high wind, heavy rain/snow) as a real \
signal against pass-catchers/kickers in that game.
5. Re-check snap-share/role signals for anything that may have changed recently (a healthy scratch \
elsewhere, a backup who has inherited snaps) — this is one of the strongest signals available, \
stronger than an injury tag by itself.
6. Players in games that have already kicked off or are about to are the hard deadline — decide them \
fully now, since there is no later re-check coming for them.

RESPONSE FORMAT:
- WHO TO START at each position, one line each, naming the specific signal driving it (matchup / \
game script / usage / injury status), and how close that game is to kickoff
- WHO TO BENCH and why
- WATCH LIST: any player you're deliberately not moving on yet because there's still time for the \
signal to firm up, and what would change your mind
- One line only, if applicable: a roster need only a waiver add could fix (do not design the pickup)"""


def build_tools(league_id: str, team_id: str, week: int):
    @tool
    def get_my_roster() -> str:
        """Get the user's own team roster: starters, bench, and injured reserve, with this week's projections and injury status."""
        try:
            roster = espn.get_team_roster(league_id, team_id).to_dict()
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        return format_roster(roster)

    @tool
    def get_matchups() -> str:
        """Get this week's NFL matchup schedule (who's playing whom) for the league."""
        try:
            matchups = espn.get_matchups(league_id, week)
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        return f"{len(matchups)} matchups scheduled for week {week} (use web search for opponent/spread/weather detail)."

    return [get_my_roster, get_matchups]


def run(league_id: str, team_id: str, league_name: str, week: int) -> str:
    tools = build_tools(league_id, team_id, week)
    agent = create_deep_agent(model=get_model(), tools=tools, system_prompt=build_system_prompt(SYSTEM_PROMPT), name="lineup_agent")
    task = (
        f"Optimize my starting lineup for my team (ESPN Team ID {team_id}) in \"{league_name}\", "
        f"week {week}. Start by calling get_my_roster."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    return result["messages"][-1].content


def main() -> None:
    parser = argparse.ArgumentParser(description="Lineup optimization deep agent")
    parser.add_argument("--league", help="ESPN league ID (overrides .env)")
    parser.add_argument("--team", help="ESPN team ID (overrides .env)")
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    args = parser.parse_args()

    leagues = resolve_leagues(args.league, args.team)
    week = args.week or espn.get_current_week(leagues[0]["leagueId"])

    for league in leagues:
        print_header("LINEUP AGENT", league["name"], week)
        output = run(league["leagueId"], league["teamId"], league["name"], week)
        print(output)


if __name__ == "__main__":
    main()
