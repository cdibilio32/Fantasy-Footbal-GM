#!/usr/bin/env python3
"""
Trade proposal deep agent — a main agent plus one partner sub-agent per team.

Usage:
    python trade_agent.py [--league ID --team ID] [--week N]
    python trade_agent.py --ask "Sell Matthew Stafford for an RB" --targets "Michelle,Jason,Adrianna"

With no --league/--team, runs against every LEAGUE_<N>_ID / LEAGUE_<N>_TEAM_ID
pair found in .env.

Flow:
  1. The main agent gets the user's roster (and the top free agents) in its
     first message and writes a trade brief: context, weaknesses, trade
     capital, players to keep, replacement level.
  2. It calls evaluate_trade_partners(brief) once. That tool runs one partner
     sub-agent per other team (or per --targets team), in parallel. Each
     sub-agent sees the brief, the user's roster, and that one team's full
     roster, and reports whether there's a trade with that team, what it is,
     and why.
  3. The main agent ranks every opportunity the sub-agents found and returns
     the ranked list to the user.

--ask passes a specific request (e.g. a player you want to sell) to the main
agent, which folds it into the brief. --targets limits which teams get a
sub-agent; it matches owner first/full names or team names.

See CLAUDE.md at the repo root for when this agent should be run.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from common import build_system_prompt, format_available_players, format_roster, get_model, print_header, resolve_leagues
from espn_service import ESPNServiceError, espn

SUBAGENT_CONCURRENCY = int(os.environ.get("TRADE_SUBAGENT_CONCURRENCY", "4"))
FREE_AGENTS_PER_POSITION = 5

POSITION_RULE = """POSITION SURPLUS/DEFICIT RULE (apply this to judge ANY team's strength or weakness at a position — \
the user's or a partner's): weigh together, for every player that team rosters at the position: (a) how many \
players it rosters there, (b) each player's points scored to date this season, (c) each player's recent weekly \
trend and this week's projection, and (d) each player's season-total projection and prior-year total as a \
track-record signal. A DEFICIT is a position where the team rosters few players there AND/OR the players it has \
grade out low on those signals. A SURPLUS is a position where the team rosters more players than its lineup needs \
AND those extra players still grade out at a startable level — a high body count of replacement-level players is \
NOT a surplus."""

MAIN_PROMPT = f"""You are the lead fantasy football trade analyst for one team's manager. Your goal: find \
trades that make the user's team better AND that the other manager would realistically accept. You don't \
evaluate partners yourself — a partner sub-agent does that for each team in the league, working from the \
brief you write.

Your first message contains the user's roster, the best free agents at each position, and sometimes a \
specific request from the user. Never invent a player, team, points total, or ownership percentage — every \
number you cite must come from that message, a sub-agent report, or web search.

{POSITION_RULE}

PHASE 1 — WRITE THE TRADE BRIEF, from the user's roster only:
- CONTEXT: is the user a contender or a rebuilder, and why? A contender prioritizes immediate high-floor \
production and weeks 15-17 schedule strength; a rebuilder prioritizes youth, upside and long-term value.
- WEAKNESSES, most urgent first: positions that grade out as a deficit under the rule above, a starter whose \
actual output has trailed his projection across multiple weeks (check the weekly points, not one bad game), or \
a position carrying real injury/return-timeline risk with no reliable roster answer. Give the signal behind each.
- TRADE CAPITAL: players the user could trade away, from positions that grade out as a surplus. Give each one's \
points to date, this week's projection, season projection and weekly scores, and name what the user would start \
at that position after trading him. Flag SELL-HIGH on any player who has scored very well but whose underlying \
role (touchdown-dependent, contested target/carry share, unsustainable efficiency — check web search for \
role/usage news) doesn't support repeating it.
- KEEP: players who shouldn't be traded — a consistent weekly producer (low week-to-week variance) is harder to \
replace than his average suggests, as is the only reliable answer at a position.
- REPLACEMENT LEVEL: the best free agent at each position, with his numbers, from your first message. The partner \
sub-agents have no free-agent data and rely on this line to judge each player's value over a streamable option.
- USER REQUEST: if the user made a specific request, restate it here and make it the top priority.

Then call evaluate_trade_partners ONCE, passing the full brief. Do not propose trades before that call.

PHASE 2 — RANK. The tool returns one report per team, each from a sub-agent that saw your brief, the user's \
roster, and that team's full roster. Then:
- Discard any proposed trade that breaks the rules: a player not on that team's roster, a free agent, a draft \
pick, or a clearly lopsided value gap. Say briefly what you discarded and why.
- Rank the rest, best first, by: how much it fixes the user's most urgent weakness; how likely the other \
manager is to accept (value balance, how acute their need is); risk (injury, role security); and fit with \
contender/rebuilder context.
- If the same player of the user's appears in trades with different teams, say those are either/or.
- A report that starts with ERROR means that team wasn't evaluated — list it as such, don't guess.

FINAL RESPONSE FORMAT:
"RANKED TRADE OPPORTUNITIES
#[N] — [Team Name] (Team ID [N], owner [name]): TRADE [Your Player(s)] for [Their Player(s)]
  NUMBERS: [each player: pts to date / this week proj / season proj]
  WHY IT WORKS FOR BOTH SIDES: [your side's gain] / [their side's gain, tied to their actual roster]
  RISK: [the single biggest risk in this deal]
  HOW TO PITCH IT: [the offer to send first, and the counter to hold back if the sub-agent found more than one package]

NO OPPORTUNITY
[Team Name] (owner [name]) — [one-line reason]"

Repeat the "#[N]" block for each ranked trade. If no team has a real, value-balanced trade, say so plainly \
instead of forcing one."""

PARTNER_PROMPT = f"""You are a fantasy football trade analyst evaluating ONE possible trade partner for the \
user's team. The user's lead analyst has already assessed the user's roster; their brief (context, weaknesses, \
trade capital, players to keep, replacement level, and any specific user request) is in your first message, \
along with the user's full roster and the partner team's full roster. Take the brief's read of the user's team \
as given — your job is the partner.

Never invent a player, points total, or ownership percentage — every number you cite must come from your first \
message or web search. Every player you ask for must be copied verbatim from the partner's roster.

{POSITION_RULE}

PROCESS:
1. FIND A TWO-SIDED FIT: apply the rule above to the partner's roster. A real trade needs BOTH: the partner \
grades out as a surplus at a position from the brief's WEAKNESSES (so they can spare a piece there), AND they \
grade out as a deficit at a position from the brief's TRADE CAPITAL (so they'd want what the user is offering). \
Check injuries in particular: if the partner's starter at a trade-capital position is hurt (non-ACTIVE injury \
tag), web search his expected return. Compare their healthy fallback to the user's player — that gap is the \
user's leverage. A 1-2 week absence makes the user's player a short-term rental to them (lower the ask); a \
multi-week or season-ending absence raises it. If their fallback is about as good as the user's player, there's \
no real need. If only one side of the fit holds, there's no trade with this team — say so and stop.
2. PROPOSE UP TO THREE TRADES, escalating: (a) a fair 1-for-1; (b) a stretch ask for a better player, balanced \
with one of the user's bench pieces if needed; (c) a 2-for-2 or 2-for-1 if that's what makes value line up. \
Skip any that fails the value check rather than padding the list. For each, run this value check — do not skip it:
   a. State BOTH sides' actual numbers: points to date this season, this week's projection, and season-total \
projection.
   b. Reject any option where one side clearly gives up a far more valuable player (e.g. bench-caliber \
production for a clear weekly starter at a scarce position). A team has no reason to accept a trade that plainly \
downgrades them.
   c. Name the specific player on the partner's roster that the user's piece would start over. If it wouldn't \
crack their starting lineup, it isn't a real need for them — don't propose it.

Within every proposal, still apply:
- A replacement-level (VORP) lens, not raw points: a player's value is how far he beats the brief's \
REPLACEMENT LEVEL player at his position.
- Risk-adjustment for injury status/recency (an "Out" tag is a much bigger discount than "Questionable"; a \
recently-returned player carries workload-ramp risk beyond his tag) and role security (is his share locked in, \
or contested by a teammate?).
- The brief's contender/rebuilder context, and any USER REQUEST in it.
- Never offer a player the brief lists under KEEP.
- An explicit bias check: flag recency bias (over-indexing on the last 1-2 games), name-brand bias (draft \
pedigree over current role), or box-score fixation (crediting an unsustainable touchdown rate or garbage-time \
output as skill).

RESPONSE FORMAT: start with one line saying whether there's a trade opportunity with this team. Then, for each \
proposal:
"TRADE OPTION [a/b/c] — TRADE [User's Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z]) for [Their Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z])
VALUE CHECK: [the gap between the two sides — confirm it's close enough that the partner would realistically accept]
REPLACES: [the player on the partner's roster the user's piece would start over]
WHY IT WORKS FOR BOTH SIDES: [user's gain] / [partner's gain, tied to their actual roster]
RISK: [the single biggest risk-adjustment factor in this deal]"

If there's no trade, explain why in two or three sentences instead — which side of the fit fails, with the \
numbers behind it."""


def team_label(team: dict) -> str:
    owners = " & ".join(team.get("ownerNames", [])) or "unknown owner"
    return f"\"{team['teamName']}\" (Team ID {team['teamId']}, owner {owners})"


def run_partner_subagent(brief: str, my_roster_text: str, partner: dict, partner_roster_text: str) -> str:
    """
    One partner sub-agent: a single model call (with OpenRouter's web plugin
    for injury/role news) that evaluates a trade with one team. It needs no
    tools — everything it needs is in its first message.
    """
    message = (
        f"LEAD ANALYST'S TRADE BRIEF:\n{brief}\n\n"
        f"USER'S ROSTER:\n{my_roster_text}\n\n"
        f"PARTNER TEAM: {team_label(partner)}\n{partner_roster_text}\n\n"
        "Is there a trade opportunity with this team? If so, what is it and why?"
    )
    response = get_model().invoke(
        [SystemMessage(content=build_system_prompt(PARTNER_PROMPT, tool_guardrail=False)), HumanMessage(content=message)]
    )
    return response.content


def build_main_tools(league_id: str, my_roster_text: str, partners: list[dict]):
    @tool
    def evaluate_trade_partners(brief: str) -> str:
        """Send your full trade brief to one partner sub-agent per team. Returns each team's report: whether there's a trade, what it is, and why."""
        rosters: dict[int, str] = {}
        for team in partners:
            try:
                rosters[team["teamId"]] = format_roster(espn.get_team_roster(league_id, str(team["teamId"])).to_dict())
            except ESPNServiceError as exc:
                rosters[team["teamId"]] = f"ERROR: {exc}"

        reports: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=SUBAGENT_CONCURRENCY) as pool:
            futures = {
                pool.submit(run_partner_subagent, brief, my_roster_text, team, rosters[team["teamId"]]): team
                for team in partners
                if not rosters[team["teamId"]].startswith("ERROR")
            }
            for team in partners:
                if rosters[team["teamId"]].startswith("ERROR"):
                    reports[team["teamId"]] = f"ERROR: couldn't load roster — {rosters[team['teamId']]}"
            for future in as_completed(futures):
                team = futures[future]
                try:
                    reports[team["teamId"]] = future.result()
                except Exception as exc:  # one team's failure shouldn't sink the others
                    reports[team["teamId"]] = f"ERROR: sub-agent failed — {exc}"
                print(f"  [partner sub-agent] {team['teamName']} done ({len(reports)}/{len(partners)})", file=sys.stderr)

        return "\n\n".join(f"=== REPORT: {team_label(team)} ===\n{reports[team['teamId']]}" for team in partners)

    return [evaluate_trade_partners]


def resolve_targets(teams: list[dict], names: list[str]) -> list[dict]:
    """Match each --targets name against owner first/full names and team names."""
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


def run(league_id: str, team_id: str, league_name: str, week: int, ask: str | None = None, targets: list[str] | None = None) -> str:
    my_roster_text = format_roster(espn.get_team_roster(league_id, team_id).to_dict())

    by_position: dict[str, list[dict]] = {}
    for p in sorted(espn.get_available_players(league_id), key=lambda p: p.projected_points, reverse=True):
        players = by_position.setdefault(p.position, [])
        if len(players) < FREE_AGENTS_PER_POSITION:
            players.append(p.to_dict())

    others = [t for t in espn.get_league_rosters(league_id) if t["teamId"] != int(team_id)]
    partners = resolve_targets(others, targets) if targets else others

    task = (
        f"My team is ESPN Team ID {team_id} in \"{league_name}\", week {week}.\n\n"
        f"MY ROSTER:\n{my_roster_text}\n\n"
        f"{format_available_players(by_position)}\n\n"
        f"TEAMS THE PARTNER SUB-AGENTS WILL EVALUATE: {', '.join(team_label(t) for t in partners)}"
    )
    if ask:
        task += f"\n\nMY REQUEST: {ask}"

    agent = create_deep_agent(
        model=get_model(),
        tools=build_main_tools(league_id, my_roster_text, partners),
        system_prompt=build_system_prompt(MAIN_PROMPT),
        name="trade_agent",
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    return result["messages"][-1].content


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade proposal deep agent")
    parser.add_argument("--league", help="ESPN league ID (overrides .env)")
    parser.add_argument("--team", help="ESPN team ID (overrides .env)")
    parser.add_argument("--week", type=int, help="NFL week (defaults to the current week)")
    parser.add_argument("--ask", help="A specific request for this run, e.g. \"Sell Matthew Stafford for an RB\"")
    parser.add_argument("--targets", help="Comma-separated owner or team names — only these teams get a partner sub-agent")
    args = parser.parse_args()

    leagues = resolve_leagues(args.league, args.team)
    week = args.week or espn.get_current_week(leagues[0]["leagueId"])
    targets = args.targets.split(",") if args.targets else None

    for league in leagues:
        print_header("TRADE AGENT", league["name"], week)
        output = run(league["leagueId"], league["teamId"], league["name"], week, args.ask, targets)
        print(output)


if __name__ == "__main__":
    main()
