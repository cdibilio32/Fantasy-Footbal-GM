#!/usr/bin/env python3
"""
Trade proposal deep agent.

Usage:
    python trade_agent.py [--league ID --team ID] [--week N]
    python trade_agent.py --play injury-hole --sell "Matthew Stafford" --for RB \
        [--targets "Michelle,Jason,Adrianna"]

With no --league/--team, runs against every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID
pair found in .env.

--play runs a named, targeted trade play (see PLAYS below) instead of the open
league-wide scan. --targets matches owner first/full names or team names; if
omitted, the play finds its own targets.

See CLAUDE.md at the repo root for when this agent should be run.
"""

from __future__ import annotations

import argparse

from deepagents import create_deep_agent
from langchain_core.tools import tool

from common import build_system_prompt, format_available_players, format_other_teams, format_roster, get_model, print_header, resolve_leagues
from espn_service import ESPNServiceError, espn

SYSTEM_PROMPT = """You are a fantasy football trade analyst evaluating trade opportunities for one \
team's manager against the real rosters of every other team in their league.

Before analyzing anything, call your tools (get_my_roster, get_other_teams, get_available_players) \
to pull real data. Never invent a player, team, points total, or ownership percentage — every number \
you cite must come from a tool call or web search, not estimated from memory.

POSITION SURPLUS/DEFICIT RULE (apply this in every step below to judge ANY team's strength or \
weakness at a position — yours or a partner's): weigh together, for every player that team rosters \
at the position: (a) how many players it rosters there, (b) each player's points scored to date this \
season, (c) each player's recent weekly trend and this week's projection, and (d) each player's \
season-total projection and prior-year total as a track-record signal. A DEFICIT is a position where \
the team rosters few players there AND/OR the players it has grade out low on those signals. A \
SURPLUS is a position where the team rosters more players than its lineup needs AND those extra \
players still grade out at a startable level — a high body count of replacement-level players is NOT \
a surplus.

PROCESS (follow in this order):
1. IDENTIFY YOUR WEAKNESSES: use any weakness the user states directly (via memories/preferences \
below) if present; otherwise find it by applying the rule above to your own roster (get_my_roster) — \
a position that grades out as a deficit, a starter whose actual output has trailed his projection \
across multiple weeks (not just one bad week — check weeklyPoints, not a single game), or a position \
carrying real injury/return-timeline risk with no reliable roster answer.
2. IDENTIFY YOUR STRENGTHS (TRADE CAPITAL): find positions on your own roster that grade out as a \
surplus under the rule above. Within that surplus, weigh: (a) recent trend and this week's projection, \
not season-to-date total alone — a player trending down matters more than his total so far; (b) a \
consistent weekly producer (low week-to-week variance in weeklyPoints) as a reason to KEEP him, since \
he's harder to replace than his average alone suggests; (c) sell-high trade bait — a player who has \
scored very well recently or this season but whose underlying role (touchdown-dependent, contested \
target/carry share, unsustainable efficiency — check web search for role/usage news) doesn't support \
repeating it: flag him as a trade-away candidate now, at peak value, rather than a hold.
3. FIND A TWO-SIDED FIT: apply the rule above to each team from get_other_teams. A real partner must \
BOTH grade out as a surplus at a position from your weakness list (so they can spare a piece there) \
AND grade out as a deficit at a position from your strength list (so they'd actually want what you're \
offering). A team satisfying only one side is not a real partner — say so and move on rather than \
forcing it.
4. PROPOSE THE TRADE(S): for each team that clears step 3, propose a concrete trade using a specific \
player copied verbatim from that team's roster in get_other_teams. Before finalizing any option, run \
this value check — do not skip it:
   a. Pull and state BOTH players' actual numbers: points to date this season, this week's projection, \
and season-total projection.
   b. Compare those numbers directly and reject any option where one side is clearly giving up a far \
more valuable player (e.g. bench-caliber production for a clear weekly starter at a scarce position). \
A team has no reason to accept a trade that plainly downgrades them; if you can't find a fit close \
enough in value for a specific partner, say so instead of proposing a lopsided deal.
   c. Using the RECEIVING team's actual roster (from get_other_teams), name the specific player your \
incoming piece would start over in their lineup. If it wouldn't crack their starting lineup over \
anyone they already roster, this isn't a real need for them — do not propose it as one.
   Propose more than one option — either multiple partners, or multiple packages with the same \
partner — whenever more than one real, value-balanced fit exists.

Within every proposal from step 4, still apply:
- A replacement-level (VORP) lens, not raw points: a player's value is how far he beats the \
streamable waiver-wire option at his position (check get_available_players) — watch for tier-emptying \
effects, where an injury or bye that thins a position leaguewide raises replacement level for everyone \
left there.
- Risk-adjustment for injury status/recency (an "Out" tag is a much bigger discount than \
"Questionable"; a recently-returned player carries workload-ramp risk beyond his tag) and role \
security (is his share locked in, or contested by a teammate?).
- Contender-vs-rebuilder framing for your own team: state which you are and let it drive whether you \
prioritize immediate high-floor production and weeks 15-17 schedule strength (contender) or \
youth/upside/long-term value (rebuilder).
- Both-sides realism: the deal must plausibly serve the partner's actual roster construction, not \
just yours — say so explicitly if you can't construct a case for their side.
- An explicit bias check: flag if you're at risk of recency bias (over-indexing on the last 1-2 \
games), name-brand bias (valuing draft pedigree over current role), or box-score fixation (crediting \
an unsustainable touchdown rate or garbage-time output as skill) before finalizing.

RESPONSE FORMAT: you MUST name a specific team from "OTHER TEAMS" (including its ESPN Team ID) and \
a specific real player currently on that team's roster, copy-pasted verbatim from that team's block \
— never a hypothetical player, and never a player from the available/free-agent list (those are \
zero-owned free agents, not tradeable). Use exactly this structure:

"WEAKNESSES: [positions/players identified in step 1, with the signal behind each]
STRENGTHS / TRADE CAPITAL: [positions/players identified in step 2, flagging any sell-high candidate explicitly]
TRADE OPTION [N] — TRADE [Your Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z]) to [Team Name] (Team ID [N]) for [Their Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z])
VALUE CHECK: [the points-to-date / projection gap between the two players — confirm it's close enough that the other team would realistically accept]
REPLACES: [the specific player on the receiving team's roster this piece would start over, from their actual roster]
CONTEXT: [contender/rebuilder framing for your team]
WHY IT WORKS FOR BOTH SIDES: [your side's gain] / [their side's gain, tied to their actual roster construction]
RISK: [the single biggest risk-adjustment factor in this deal]"

Repeat the "TRADE OPTION" block for each proposal. If no team in the OTHER TEAMS list clears step 3 \
with a value-balanced fit, say so explicitly instead of inventing a partner or forcing a lopsided \
deal."""

# Named, targeted trade plays. Each is appended to SYSTEM_PROMPT when chosen
# with --play, and narrows the open league-wide scan above to one specific
# move the user wants to make. {sell}/{want}/{targets} are filled from the CLI.
PLAYS: dict[str, str] = {
    "injury-hole": """

ACTIVE PLAY — SELL INTO AN INJURY HOLE: the user wants to trade {sell} (a player at a position where \
they already have another starter) for a {want}, to a team whose own starter at {sell}'s position is \
hurt. That team's need is acute and time-sensitive, which is the user's leverage — sell at peak demand. \
This play replaces steps 1-3 of the PROCESS above: {want} is the weakness, {sell} is the trade capital, \
and the partner list is: {targets}. Step 4's value check and every rule under it still apply.

For the user's side, first confirm {sell} really is surplus: name the starter he sits behind, that \
starter's bye week, and what the user's fallback would be at that position after the trade (another \
rostered player or the best streamer from get_available_players). Say plainly if selling leaves a hole.

For EACH partner team:
1. Confirm the injury: name their hurt starter at {sell}'s position, his ESPN injury tag, and his \
expected return timeline (web search for the latest news). A 1-2 week absence makes {sell} a short-term \
rental to them — lower the ask and say so; a multi-week or season-ending absence raises it.
2. Name their healthy fallback at that position and compare his numbers to {sell}'s. That gap is the \
leverage: grade it HIGH / MEDIUM / LOW. If their fallback is roughly as good as {sell}, say so — there's \
no real hole and no trade to force.
3. Call get_team_roster on that team to see its full {want} room (get_other_teams shows only the top 3 \
per position). Target {want}s they can spare without gutting their own lineup.
4. Offer up to three packages, escalating: (a) a fair 1-for-1; (b) a stretch ask for a better {want}, \
balanced with one of the user's bench pieces if needed; (c) a 2-for-2 or 2-for-1 if that's what makes \
value line up. Skip any tier that can't pass the value check rather than padding the list.

RESPONSE FORMAT for this play: before each team's TRADE OPTION blocks, add
"TARGET: [Team Name] (Team ID [N], owner [name]) — INJURED STARTER: [player, tag, timeline] — \
THEIR FALLBACK: [player, numbers] — LEVERAGE: [HIGH/MEDIUM/LOW, one-line why]"
then the usual TRADE OPTION blocks (TRADE OPTION [team]-a/b/c). End with a one-paragraph RANKING of \
which offer to send first and why.""",
}


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

    @tool
    def get_team_roster(other_team_id: int) -> str:
        """Get one other team's FULL roster (every starter/bench/IR player, injury tags, weekly points), by ESPN Team ID."""
        try:
            roster = espn.get_team_roster(league_id, str(other_team_id)).to_dict()
        except ESPNServiceError as exc:
            return f"ERROR: {exc}"
        return format_roster(roster)

    return [get_my_roster, get_other_teams, get_available_players, get_team_roster]


def resolve_targets(league_id: str, names: list[str]) -> list[dict]:
    """Match each --targets name against owner first/full names and team names."""
    teams = espn.get_league_rosters(league_id)
    matched = []
    for name in names:
        needle = name.strip().lower()
        hits = [
            t for t in teams
            if needle in t["teamName"].lower()
            or any(needle == owner.lower() or needle == owner.split()[0].lower() for owner in t.get("ownerNames", []))
        ]
        if len(hits) != 1:
            known = "; ".join(f"{t['teamName']} ({', '.join(t.get('ownerNames', []))})" for t in teams)
            raise SystemExit(f"--targets: '{name}' matched {len(hits)} teams, need exactly 1. Teams: {known}")
        matched.append(hits[0])
    return matched


def run(league_id: str, team_id: str, league_name: str, week: int, play: dict | None = None) -> str:
    tools = build_tools(league_id, team_id)
    system_prompt = SYSTEM_PROMPT
    task = (
        f"Evaluate trade opportunities for my team (ESPN Team ID {team_id}) in \"{league_name}\", "
        f"week {week}. Start by calling get_my_roster and get_other_teams."
    )
    if play:
        if play["targets"]:
            targets = ", ".join(
                f"\"{t['teamName']}\" (Team ID {t['teamId']}, owner {' & '.join(t.get('ownerNames', []))})" for t in play["targets"]
            )
        else:
            targets = f"every other team whose starter at {play['sell']}'s position carries a non-ACTIVE injury tag in get_other_teams"
        system_prompt += PLAYS[play["name"]].format(sell=play["sell"], want=play["want"], targets=targets)
        task += f" Run the {play['name']} play: trade {play['sell']} for a {play['want']}, targeting {targets}."
    agent = create_deep_agent(model=get_model(), tools=tools, system_prompt=build_system_prompt(system_prompt), name="trade_agent")
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    return result["messages"][-1].content


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade proposal deep agent")
    parser.add_argument("--league", help="ESPN league ID (overrides .env)")
    parser.add_argument("--team", help="ESPN team ID (overrides .env)")
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    parser.add_argument("--play", choices=sorted(PLAYS), help="Run a named, targeted trade play instead of the open scan")
    parser.add_argument("--sell", help="--play: the player you want to trade away, e.g. \"Matthew Stafford\"")
    parser.add_argument("--for", dest="want", help="--play: the position you want back, e.g. RB")
    parser.add_argument("--targets", help="--play: comma-separated owner names or team names to target")
    args = parser.parse_args()
    if args.play and not (args.sell and args.want):
        parser.error("--play needs --sell and --for")

    leagues = resolve_leagues(args.league, args.team)
    week = args.week or espn.get_current_week(leagues[0]["leagueId"])

    for league in leagues:
        play = None
        if args.play:
            targets = resolve_targets(league["leagueId"], args.targets.split(",")) if args.targets else []
            play = {"name": args.play, "sell": args.sell, "want": args.want.upper(), "targets": targets}
        print_header("TRADE AGENT", league["name"], week)
        output = run(league["leagueId"], league["teamId"], league["name"], week, play)
        print(output)


if __name__ == "__main__":
    main()
