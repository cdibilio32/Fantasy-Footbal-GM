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
     and why. Every trade must pass check_lineup_impact (both teams' best
     starting lineups project higher this week) and must not have the user
     giving more value than they get.
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
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
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
pick, a failed or missing lineup check (BOTH teams' starting lineups must project higher this week), or the \
user giving more value than they get back. Say briefly what you discarded and why.
- Rank the rest, best first, by: how much it fixes the user's most urgent weakness; how little the user gives \
up (prefer the cheapest trade that does the job); how likely the other manager is to accept (their lineup gain, \
how acute their need is); risk (injury, role security); and fit with contender/rebuilder context.
- If the same player of the user's appears in trades with different teams, say those are either/or.
- A report that starts with ERROR means that team wasn't evaluated — list it as such, don't guess.

FINAL RESPONSE FORMAT:
"RANKED TRADE OPPORTUNITIES
#[N] — [Team Name] (Team ID [N], owner [name]): TRADE [Your Player(s)] for [Their Player(s)]
  NUMBERS: [each player: pts to date / this week proj / season proj]
  LINEUP IMPACT: [your starting lineup before → after; theirs before → after]
  WHY IT WORKS FOR BOTH SIDES: [your side's gain] / [their side's gain, tied to their actual roster]
  RISK: [the single biggest risk in this deal]
  HOW TO PITCH IT: [the opening offer to send first, and the walk-away offer — the most to give — if the sub-agent found one. Never suggest going past it.]

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
2. PROPOSE AT MOST TWO OPTIONS: (a) an OPENING OFFER that tilts slightly toward the user — the least the user \
can reasonably give for what they want; and, only if it differs, (b) the WALK-AWAY OFFER — the most the user \
should give, which is an even trade and never more. Skip (b) if (a) is already even. For each, run these checks \
— do not skip them:
   a. STARTING LINEUP CHECK: call check_lineup_impact with the exact player names. BOTH teams' best starting \
lineups must project higher this week. If the tool says FAILS, rework the trade or drop it — never propose a \
trade that fails it. If it notes a side doesn't go up on the season-rate lens, say so: that side is only \
getting a short-term gain.
   b. DON'T OVERPAY: state BOTH sides' actual numbers (points to date this season, this week's projection, \
season-total projection) and value over the brief's replacement level. The user must NOT give more value than \
they get back. Don't add sweeteners (extra players) to get a deal done, don't propose 2-for-1s where the user \
gives the two, and don't give up a starter for a bench piece. When the partner's need is acute (e.g. their \
starter is hurt with a weak fallback), that's leverage: use it to ask for more, never to justify giving more. \
If the partner won't plausibly accept an even trade, there's no trade — say so rather than raising the offer.
   c. Name the specific player on the partner's roster that the user's piece would start over (the lineup \
check shows it). If it wouldn't crack their starting lineup, it isn't a real need for them — don't propose it.

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
"[OPENING OFFER / WALK-AWAY OFFER] — TRADE [User's Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z]) for [Their Player] ([Position], pts to date: [X], this week proj: [Y], season proj: [Z])
LINEUP IMPACT: [user's lineup before → after, partner's lineup before → after, from check_lineup_impact]
VALUE CHECK: [the value gap — confirm the user isn't giving more than they get, and why the partner would still accept]
REPLACES: [the player on the partner's roster the user's piece would start over]
WHY IT WORKS FOR BOTH SIDES: [user's gain] / [partner's gain, tied to their actual roster]
RISK: [the single biggest risk-adjustment factor in this deal]"

If there's no trade, explain why in two or three sentences instead — which side of the fit fails, with the \
numbers behind it."""


# Which player positions can fill each starting slot. A slot not listed here is
# a dedicated slot, filled only by the position of the same name (QB, RB, K...).
FLEX_SLOTS: dict[str, set[str]] = {
    "RB/WR": {"RB", "WR"},
    "WR/TE": {"WR", "TE"},
    "FLEX": {"RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
# Players with these tags are counted as 0 for this week's projection.
UNAVAILABLE_TAGS = {"OUT", "DOUBTFUL", "INJURY_RESERVE", "SUSPENSION"}
SEASON_GAMES = 17


def this_week_value(p: dict) -> float:
    return 0.0 if (p.get("injuryStatus") or "").upper() in UNAVAILABLE_TAGS else p.get("projectedPoints", 0.0)


def season_rate_value(p: dict) -> float:
    return p.get("seasonProjectedPoints", 0.0) / SEASON_GAMES


def best_lineup(players: list[dict], slots: dict[str, int], value) -> tuple[float, dict[str, str]]:
    """
    The highest-projected starting lineup a roster can field: dedicated slots
    first, then flex slots from whoever's left. Returns (total, {player: slot}).
    """
    pool = sorted(players, key=value, reverse=True)
    used: set[str] = set()
    lineup: dict[str, str] = {}
    ordered = [s for s in slots if s not in FLEX_SLOTS] + [s for s in FLEX_SLOTS if s in slots]
    for slot in ordered:
        eligible = FLEX_SLOTS.get(slot, {slot})
        for _ in range(slots[slot]):
            pick = next((p for p in pool if p["fullName"] not in used and p["position"] in eligible), None)
            if pick:
                used.add(pick["fullName"])
                lineup[pick["fullName"]] = slot
    return round(sum(value(p) for p in players if p["fullName"] in lineup), 1), lineup


def all_players(roster: dict) -> list[dict]:
    return roster["starters"] + roster["bench"] + roster["injuredReserve"]


def lineup_change(before: dict[str, str], after: dict[str, str]) -> str:
    joined = [f"{name} ({slot})" for name, slot in after.items() if name not in before]
    left = [name for name in before if name not in after]
    if not joined and not left:
        return "no change to the starting lineup"
    return f"starts {', '.join(joined) or 'nobody new'}; no longer starts {', '.join(left) or 'nobody'}"


def lineup_impact(my_roster: dict, partner_roster: dict, slots: dict[str, int], user_gives: list[str], user_gets: list[str]) -> str:
    """Before/after starting-lineup projections for both teams if the user gives `user_gives` for `user_gets`."""
    mine = {p["fullName"].lower(): p for p in all_players(my_roster)}
    theirs = {p["fullName"].lower(): p for p in all_players(partner_roster)}
    missing = [n for n in user_gives if n.lower() not in mine] + [n for n in user_gets if n.lower() not in theirs]
    if missing:
        return f"ERROR: not found on the right roster: {', '.join(missing)}. Copy names exactly as listed (user_gives from the user's roster, user_gets from the partner's)."

    gives = [mine[n.lower()] for n in user_gives]
    gets = [theirs[n.lower()] for n in user_gets]
    my_after = [p for p in mine.values() if p not in gives] + gets
    their_after = [p for p in theirs.values() if p not in gets] + gives

    lines, verdicts = [], []
    for lens, value in (("THIS WEEK (ESPN weekly projection; OUT/DOUBTFUL/IR count as 0)", this_week_value),
                        ("SEASON RATE (season projection ÷ 17; ignores this week's injuries)", season_rate_value)):
        lines.append(lens)
        for side, before_players, after_players in (("User", list(mine.values()), my_after), ("Partner", list(theirs.values()), their_after)):
            before_total, before_lineup = best_lineup(before_players, slots, value)
            after_total, after_lineup = best_lineup(after_players, slots, value)
            delta = round(after_total - before_total, 1)
            lines.append(f"  {side}: {before_total} → {after_total} ({delta:+}) — {lineup_change(before_lineup, after_lineup)}")
            verdicts.append((lens.split(" (")[0], side, delta))
    this_week = [v for v in verdicts if v[0] == "THIS WEEK"]
    if all(delta > 0 for _, _, delta in this_week):
        lines.append("RESULT: both starting lineups project higher this week.")
    else:
        worse = " and ".join(side for _, side, delta in this_week if delta <= 0)
        lines.append(f"RESULT: FAILS — {worse} starting lineup doesn't project higher this week. Don't propose this trade.")
    season_worse = [side for lens, side, delta in verdicts if lens == "SEASON RATE" and delta <= 0]
    if season_worse:
        lines.append(f"NOTE: {' and '.join(season_worse)} lineup doesn't go up on the season-rate lens — for that side it's a short-term gain only; say so.")
    return "\n".join(lines)


def team_label(team: dict) -> str:
    owners = " & ".join(team.get("ownerNames", [])) or "unknown owner"
    return f"\"{team['teamName']}\" (Team ID {team['teamId']}, owner {owners})"


def run_partner_subagent(brief: str, my_roster: dict, partner: dict, partner_roster: dict, slots: dict[str, int]) -> str:
    """
    One partner sub-agent: evaluates a trade with one team. Everything it
    needs is in its first message; its one tool, check_lineup_impact, checks
    each candidate trade against both teams' best starting lineups. Web
    search comes from OpenRouter's plugin.
    """

    @tool
    def check_lineup_impact(user_gives: list[str], user_gets: list[str]) -> str:
        """Before/after projected starting-lineup totals for BOTH teams if the user trades user_gives (names from the user's roster) for user_gets (names from the partner's roster)."""
        return lineup_impact(my_roster, partner_roster, slots, user_gives, user_gets)

    message = (
        f"LEAD ANALYST'S TRADE BRIEF:\n{brief}\n\n"
        f"USER'S ROSTER:\n{format_roster(my_roster)}\n\n"
        f"PARTNER TEAM: {team_label(partner)}\n{format_roster(partner_roster)}\n\n"
        f"STARTING LINEUP SLOTS: {', '.join(f'{slot} x{n}' for slot, n in slots.items())}\n\n"
        "Is there a trade opportunity with this team? If so, what is it and why?"
    )
    agent = create_agent(
        model=get_model(),
        tools=[check_lineup_impact],
        system_prompt=build_system_prompt(PARTNER_PROMPT, tool_guardrail=False),
    )
    result = agent.invoke({"messages": [HumanMessage(content=message)]})
    return result["messages"][-1].content


def build_main_tools(league_id: str, my_roster: dict, partners: list[dict]):
    slots = espn.get_lineup_slots(league_id)

    @tool
    def evaluate_trade_partners(brief: str) -> str:
        """Send your full trade brief to one partner sub-agent per team. Returns each team's report: whether there's a trade, what it is, and why."""
        rosters: dict[int, dict | str] = {}
        for team in partners:
            try:
                rosters[team["teamId"]] = espn.get_team_roster(league_id, str(team["teamId"])).to_dict()
            except ESPNServiceError as exc:
                rosters[team["teamId"]] = f"ERROR: couldn't load roster — {exc}"

        reports: dict[int, str] = {t["teamId"]: r for t in partners if isinstance(r := rosters[t["teamId"]], str)}
        with ThreadPoolExecutor(max_workers=SUBAGENT_CONCURRENCY) as pool:
            futures = {
                pool.submit(run_partner_subagent, brief, my_roster, team, rosters[team["teamId"]], slots): team
                for team in partners
                if team["teamId"] not in reports
            }
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
    my_roster = espn.get_team_roster(league_id, team_id).to_dict()

    by_position: dict[str, list[dict]] = {}
    for p in sorted(espn.get_available_players(league_id), key=lambda p: p.projected_points, reverse=True):
        players = by_position.setdefault(p.position, [])
        if len(players) < FREE_AGENTS_PER_POSITION:
            players.append(p.to_dict())

    others = [t for t in espn.get_league_rosters(league_id) if t["teamId"] != int(team_id)]
    partners = resolve_targets(others, targets) if targets else others

    task = (
        f"My team is ESPN Team ID {team_id} in \"{league_name}\", week {week}.\n\n"
        f"MY ROSTER:\n{format_roster(my_roster)}\n\n"
        f"{format_available_players(by_position)}\n\n"
        f"TEAMS THE PARTNER SUB-AGENTS WILL EVALUATE: {', '.join(team_label(t) for t in partners)}"
    )
    if ask:
        task += f"\n\nMY REQUEST: {ask}"

    agent = create_deep_agent(
        model=get_model(),
        tools=build_main_tools(league_id, my_roster, partners),
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
