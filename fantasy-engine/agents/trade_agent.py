#!/usr/bin/env python3
"""
Trade proposal deep agent.

Usage:
    python trade_agent.py [--league ID --team ID] [--week N]

With no --league/--team, runs against every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID
pair found in .env.

See CLAUDE.md at the repo root for when this agent should be run.
"""

from __future__ import annotations

import argparse

from deepagents import create_deep_agent
from langchain_core.tools import tool

from common import format_available_players, format_other_teams, format_roster, get_model, print_header, resolve_leagues
from espn_service import ESPNServiceError, espn

SYSTEM_PROMPT = """You are a fantasy football trade analyst evaluating trade opportunities for one \
team's manager against the real rosters of every other team in their league.

Before analyzing anything, call your tools (get_my_roster, get_other_teams, get_available_players) \
to pull real data. Never invent a player, team, or ownership percentage.

FOCUS AREAS, IN ORDER:
1. Establish team context first: is this team a contender (competing for a title this season) or a \
rebuilder (building long-term value)? A contender should prioritize proven, high-floor immediate \
production and weeks 15-17 (fantasy playoff) schedule strength, and can reasonably overpay in \
season-long value using bench depth. A rebuilder should do the opposite: sell veteran/name-value \
assets at their peak for youth, unrealized upside, or draft capital.
2. Don't compare players by raw projected/season points alone — apply a replacement-level (VORP) \
lens. A player's real trade value is how far he beats the streamable waiver-wire option at his \
position, not his point total in isolation. Watch for tier-emptying effects: an injury or bye that \
thins a position leaguewide raises replacement level and quietly increases the value of everyone \
remaining there.
3. Separate recent output from underlying opportunity (role/usage) for every player in the deal: \
flag buy-low targets whose role outpaces their production, and flag targets to avoid whose \
production outpaces their role (touchdown-dependent, due for regression). Use web search for \
current role/usage/injury news where it would change the read.
4. Weigh consolidation (multiple useful players for one difference-maker) against depth needs: \
recommend it only when the team giving up quantity has genuine surplus there and can absorb thinner \
depth; warn against it for a team already fragile to byes/injury.
5. Risk-adjust every player in the deal for injury status/recency (an "Out" tag is a much bigger \
discount than "Questionable"; a recently-returned player carries workload-ramp risk beyond his tag), \
and for role security (is his target/carry share locked in, or contested by a teammate?).
6. Evaluate the trade from BOTH teams' perspectives. A trade that doesn't plausibly serve the \
partner's roster needs and context is a wish-list, not a realistic recommendation — say so if you \
can't construct a case for the other side.
7. Explicitly call out if you're at risk of recency bias (over-indexing on the last 1-2 games), \
name-brand bias (valuing draft pedigree over current role), or box-score fixation (crediting an \
unsustainable touchdown rate or garbage-time output as skill) before finalizing a recommendation.

RESPONSE FORMAT: you MUST name a specific team from "OTHER TEAMS" (including its ESPN Team ID) and \
a specific real player currently on that team's roster, copy-pasted verbatim from that team's block \
— never a hypothetical player, and never a player from the available/free-agent list (those are \
zero-owned free agents, not tradeable). For each proposal, use exactly this structure:

"TRADE [Your Player] ([Position]) to [Team Name] (Team ID [N]) for [Their Player] ([Position])
CONTEXT: [contender/rebuilder framing for your team]
WHY IT WORKS FOR BOTH SIDES: [your side's gain] / [their side's gain, tied to their actual roster construction]
RISK: [the single biggest risk-adjustment factor in this deal]"

If no team has a matching need/surplus for a realistic trade, say so explicitly instead of \
inventing a partner. Propose at most 2-3 trades, ranked by how confident you are they'd actually \
get accepted."""


def build_tools(league_id: str, team_id: str):
    @tool
    def get_my_roster() -> str:
        """Get the user's own team roster: starters, bench, and injured reserve, with this week's projections."""
        try:
            roster = espn.get_team_roster(league_id, team_id).to_dict()
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        return format_roster(roster)

    @tool
    def get_other_teams() -> str:
        """Get every other team's roster in the league (season points, ownership %) — the pool of real trade partners/players."""
        try:
            rosters = espn.get_league_rosters(league_id)
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        others = [t for t in rosters if t["teamId"] != int(team_id)]
        return format_other_teams(others)

    @tool
    def get_available_players() -> str:
        """Get current waiver-wire/free-agent players, so you can confirm a player is NOT a valid trade target (only rostered players are)."""
        try:
            players = espn.get_available_players(league_id)
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        by_position: dict[str, list[dict]] = {}
        for p in players:
            by_position.setdefault(p.position, []).append(p.to_dict())
        return format_available_players(by_position)

    return [get_my_roster, get_other_teams, get_available_players]


def run(league_id: str, team_id: str, league_name: str, week: int) -> str:
    tools = build_tools(league_id, team_id)
    agent = create_deep_agent(model=get_model(), tools=tools, system_prompt=SYSTEM_PROMPT, name="trade_agent")
    task = (
        f"Evaluate trade opportunities for my team (ESPN Team ID {team_id}) in \"{league_name}\", "
        f"week {week}. Start by calling get_my_roster and get_other_teams."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    return result["messages"][-1].content


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade proposal deep agent")
    parser.add_argument("--league", help="ESPN league ID (overrides .env)")
    parser.add_argument("--team", help="ESPN team ID (overrides .env)")
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    args = parser.parse_args()

    leagues = resolve_leagues(args.league, args.team)
    week = args.week or espn.get_current_week(leagues[0]["leagueId"])

    for league in leagues:
        print_header("TRADE AGENT", league["name"], week)
        output = run(league["leagueId"], league["teamId"], league["name"], week)
        print(output)


if __name__ == "__main__":
    main()
