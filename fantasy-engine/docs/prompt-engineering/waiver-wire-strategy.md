# Waiver Wire & FAAB Decision Frameworks

This file distills established fantasy-football waiver-wire / free-agency decision
frameworks used by respected analysts, for use in engineering the LLM system prompt
for the `tuesday_waivers` (and `monday_analysis` waiver-prep) commands
(`fantasy-engine/mcp-server/src/services/workflowContext.ts`).

The rule-based scorer in `fantasy-engine/mcp-server/src/tools/waiver.ts` already
computes: projected points, percent owned/started delta, position scarcity (RB/TE),
FAAB suggestion tiers, and drop candidates (injury status + low projection/usage).
Everything below is meant to add reasoning layers *on top of* those signals, not
restate them.

## Decision Frameworks

**1. FAAB bid-as-percentage-of-remaining-budget, not fixed dollars.** Think in
percentages of total/remaining budget so guidance holds across $100 or $1,000
leagues: reserve ~50–60% of budget through the first month, but go big (40–80%,
even "worth 100%" for a true league-winner) on a clear early-season breakout,
since unspent FAAB has zero value if it sits unused ([4for4](https://www.4for4.com/2025/preseason/ultimate-guide-waiver-wire-faab-strategy-2025),
[Fantasy Footballers](https://www.thefantasyfootballers.com/analysis/fantasy-football-101-faab-strategies/)).
Modest depth/streaming adds should cost far less (~1–12% of budget); defense/kicker
streams should cost near-zero (a few dollars or $0 bids).

**2. Bid curve shifts with season stage.** Early season (weeks 1–4) rewards
aggression on unproven breakouts because sample sizes are thin and price is still
low; mid/late season bidding should tighten toward proven, role-secure players and
increasingly weigh playoff-schedule fit over raw talent ([4for4](https://www.4for4.com/2025/preseason/ultimate-guide-waiver-wire-faab-strategy-2025)).
Keep a reserve (~20–25% of original budget) unspent past the midpoint for injury-driven
opportunities rather than exhausting the budget on early depth.

**3. Streaming is a role/matchup search, not a name search.** Stream QB/TE/DST/K
only when the free-agent option has a clearer *role and matchup* than the incumbent
this specific week — not because of last week's box score. For DST, target defenses
facing a weak/backup/rookie QB, a struggling O-line, or a shorthanded offense,
preferably at home; rotate weekly rather than committing budget to one unit
([RotoWire](https://www.rotowire.com/football/article/fantasy-football-defense-streaming-strategy-tips-95749),
[Athlon](https://athlonsports.com/fantasy/fantasy-football-streaming-strategy-advice)).
Common streaming mistake to flag: chasing the prior week's points instead of the
upcoming matchup.

**4. Opportunity precedes production — buy low on role, not results.**
Snap share, route participation, target share, and red-zone/goal-line touches shift
1–2 weeks *before* fantasy points catch up. A player with rising usage but points
that haven't followed yet is a buy-low; a player scoring from a small workload via
long/garbage-time touchdowns is a regression/sell-high candidate ([RotoWire](https://www.rotowire.com/football/article/fantasy-football-trade-targets-players-to-buy-low-sell-high-97949)).
This directly extends the existing `percentStarted > percentOwned` signal in
`waiver.ts` — the reasoning should explicitly separate "role is improving" from
"last week's score was good."

**5. Waiver-priority leagues vs. FAAB leagues need different advice.** In
rolling-priority leagues there's no bid sizing decision — the only lever is
*whether this claim is worth burning your priority slot* (which resets to the
bottom on a successful claim), so recommendations should rank "worth it" vs. "let
it ride" rather than dollar amounts. In FAAB leagues the lever is bid amount
relative to remaining budget and competitors' likely remaining budget ([FantasyPros](https://www.fantasypros.com/2026/06/beginners-guide-understanding-fantasy-football-waiver-wires/)).
The system prompt should ask which system the league uses before giving numeric
bid advice, or hedge output as percentage-of-budget language.

**6. Roster-construction tradeoffs drive drop candidates as much as player quality
does.** Before recommending a drop, check: (a) bye-week collision — do surviving
players at that position share a bye with something else on the roster; (b) IR-slot
eligibility — an injured stash that qualifies for IR shouldn't cost a bench spot;
(c) handcuff value — a backup RB to a rostered starter has spike value the raw
projection understates; (d) positional depth floor — don't drop the last viable
bench body at a scarce position (RB/TE) even if its projection is low ([RotoWire glossary](https://www.rotowire.com/fantasy/football/glossary),
[FantasyPros](https://www.fantasypros.com/2025/11/fantasy-football-waiver-wire-advice-pickups-to-target-stash-drop-week-13-adds/)).

**7. Timing: get ahead of bye weeks and injury news, don't react to it.**
Bye-week shortfalls should be addressed 1–2 weeks before they hit, not the week
of, since waiver priority/FAAB competition spikes right before a heavy bye week
([RotoWire glossary](https://www.rotowire.com/fantasy/football/glossary)). For
weekly processing cadence: Tuesday overnight waivers reward pre-committed priority
claims/bids on players whose value is already known; Wednesday-onward free agency
is a lower-stakes, first-come pool best used for reactive pickups (injury fallout,
Monday-night breakouts) that emerged too late for the Tuesday run.

**8. Process over outcome — evaluate the decision, not the last result.**
A good decision (correct read on role, opportunity, matchup) that produced a bad
outcome is not evidence the process was wrong, and vice versa. When justifying a
recommendation, cite the underlying opportunity/role/matchup factors rather than
last week's fantasy points alone, and be explicit when a recommendation is a
"process bet" that may not pay off immediately ([Decidership](https://www.decidership.com/p/decision-skills-fantasy-sports),
[Athlon](https://athlonsports.com/fantasy/fantasy-football-draft-strategy-tips-for-success)).

**9. Bid to just beat the market, not to overpay for certainty.** The efficient
bid is a few dollars/percent above what you estimate the next-highest bidder will
offer — not your max valuation — except for the rare must-have player, where
paying a premium to guarantee the claim is correct because a near-miss costs the
asset entirely while overpaying only costs budget ([Fantasy Footballers](https://www.thefantasyfootballers.com/analysis/fantasy-football-101-faab-strategies/),
[Tackle Fantasy Football](https://www.tacklefantasyfootball.com/faab-bidding-strategy-how-much-to-bid/)).

## Distilled for the system prompt

- Frame FAAB recommendations as a **percentage of remaining budget**, not a raw
  dollar figure; scale that percentage to season stage (aggressive weeks 1–4 on
  clear breakouts, conservative and reserve-building after the midpoint).
- Distinguish **role/opportunity signals** (snap share, target share, red-zone
  touches, snap/route trend) from **box-score results** — recommend buy-low adds
  where role is outrunning production, and flag drop/sell candidates whose
  production is outrunning role (touchdown-dependent, low-volume scorers).
- For streaming positions (QB/TE/DST/K), only recommend a swap when the
  alternative has a **clearer role and better matchup this week** than the
  incumbent — never justify a stream by pointing at last week's points.
- Before naming a drop candidate, check **bye-week collisions, IR eligibility,
  handcuff value, and positional depth floor** at scarce positions (RB/TE) — not
  projected points alone.
- Ask or infer whether the league uses **waiver priority or FAAB**; priority
  leagues get a binary "claim it or hold your spot" recommendation, FAAB leagues
  get a percentage-of-budget bid recommendation.
- Address bye weeks and IR needs **1–2 weeks ahead of time**, not the week they
  hit.
- Justify every recommendation by **opportunity/role/matchup reasoning**, not
  the outcome of the player's last game — a good process can lose and a lucky
  play can win.
- Reserve near-zero bids for streaming depth (DST/K); reserve meaningful budget
  spend for players with a real path to a weekly starting role.

## Sources

- [4for4 — The Ultimate Guide to Waiver Wire & FAAB Strategy](https://www.4for4.com/2025/preseason/ultimate-guide-waiver-wire-faab-strategy-2025)
- [The Fantasy Footballers — FAAB Strategies 101](https://www.thefantasyfootballers.com/analysis/fantasy-football-101-faab-strategies/)
- [Tackle Fantasy Football — FAAB Bidding Strategy](https://www.tacklefantasyfootball.com/faab-bidding-strategy-how-much-to-bid/)
- [RotoWire — Streaming Defenses Explained](https://www.rotowire.com/football/article/fantasy-football-defense-streaming-strategy-tips-95749)
- [Athlon — What is Streaming in Fantasy Football](https://athlonsports.com/fantasy/fantasy-football-streaming-strategy-advice)
- [RotoWire — Buy Low / Sell High Trade Targets](https://www.rotowire.com/football/article/fantasy-football-trade-targets-players-to-buy-low-sell-high-97949)
- [FantasyPros — Beginner's Guide to Waiver Wires](https://www.fantasypros.com/2026/06/beginners-guide-understanding-fantasy-football-waiver-wires/)
- [FantasyPros — Waiver Wire Advice: Pickups, Stashes & Drops](https://www.fantasypros.com/2025/11/fantasy-football-waiver-wire-advice-pickups-to-target-stash-drop-week-13-adds/)
- [RotoWire — Fantasy Football Glossary (handcuff, bye week, IR, stash)](https://www.rotowire.com/fantasy/football/glossary)
- [Decidership — Decision Skills Beat Football Knowledge in Fantasy](https://www.decidership.com/p/decision-skills-fantasy-sports)
- [Athlon — Draft Strategy: Process, Not Prediction](https://athlonsports.com/fantasy/fantasy-football-draft-strategy-tips-for-success)
