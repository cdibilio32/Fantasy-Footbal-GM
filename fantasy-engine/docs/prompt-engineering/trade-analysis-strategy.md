# Trade Analysis Strategy — Research Notes

This file distills established fantasy football trade-evaluation frameworks used by
serious analysts, to inform the system prompt for the `trade_analysis` task
(`workflowContext.ts::getTaskSpecificSystemPrompt`). The rule-based calculator in
`mcp-server/src/tools/trades.ts` already covers: projected-points value scoring,
ownership/injury multipliers, a 0–100 fairness rating, and basic positional-impact
text. The frameworks below are **additive** — layers of judgment an LLM should apply
on top of that raw number, not a restatement of it.

## Decision Frameworks

### 1. Redraft ROS value vs. dynasty/keeper value are different currencies
A player's rest-of-season (ROS) value (points expected through the remaining
weeks of *this* season) and their dynasty/keeper value (multi-year asset worth,
weighted toward age and draft capital) can diverge sharply — e.g., an aging
veteran can have strong ROS value but poor dynasty value, and a rookie can be
the reverse. Trade tools like RotoTrade explicitly keep separate value tracks for
redraft and dynasty leagues rather than one blended number. The LLM must first
identify which mode the league is in and value players accordingly, never mixing
the two currencies in the same evaluation. ([RotoTrade](https://www.rototrade.com/fantasy-football-trade-analyzer))

### 2. Value Over Replacement (VORP/VBD) as the fairness lens, not raw points
Raw projected points overstate value at deep positions and understate it at thin
ones. VORP = a player's projected points minus the replacement-level points
available at their position (e.g., the points a streamable free agent at that slot
would produce). A trade that looks even in total points can be lopsided in VORP —
e.g., RB12-for-WR8 may be unfair if a WR8-caliber replacement is available on
waivers but no comparable RB is. When a positional tier "empties" (an injury or
bye thins the position leaguewide), replacement level rises and remaining players
at that position gain value even without a stat change. ([FantasyPros VBD](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/), [Fantasy Analytics Authority](https://fantasyanalyticsauthority.com/value-over-replacement-player-fantasy))

### 3. Consolidation (2-for-1) vs. quantity trades — depth-for-star tradeoffs
"Consolidating" — trading multiple useful players for one difference-maker —
concentrates value into fewer roster spots, since only starters count and one
elite player can win a week outright; the flip side is thinner bench depth and
more exposure to a single injury. The correct call depends on roster context:
consolidate when a team has genuine surplus at the position(s) given up and can
absorb the depth loss; go the other way (trade a star for quantity/multiple
starters) when a team is bye-week- or injury-fragile and needs redundancy more
than a ceiling play. Trading from a position of roster strength to fill a
genuine weakness is the one pattern that reliably improves a team either
direction. ([Footballguys](https://www.footballguys.com/article/2023-ultimate-guide-to-trades), [FantasyLife](https://www.fantasylife.com/articles/dynasty/dynasty-fantasy-football-2-for-1-trade-strategy))

### 4. Buy-low / sell-high: trade on role and opportunity, not last week's box score
Buy-low targets are players whose usage (snap share, target share, red-zone
role) remains strong but whose points haven't caught up yet, typically after a
slow start, negative touchdown regression, or one bad game — the market
overreacts to the score line while the underlying opportunity says production
is coming. Sell-high targets are the inverse: name value or a hot streak built
on unsustainable touchdown rate or a plus matchup, with a market price above what
the underlying role supports. The evaluation should explicitly separate "what
happened" (recent points) from "what is likely to keep happening" (role/target
share trend), and weight the latter more heavily. ([RotoWire](https://www.rotowire.com/football/article/fantasy-football-trade-targets-players-to-buy-low-sell-high-98607), [Oddsmyth](https://oddsmyth.ai/guides/fantasy-football-trade-strategy))

### 5. Contender vs. rebuilder framing changes what "fair value" means
The single most important context variable is whether a team is competing this
season or building for next season — it should be established before any other
judgment is applied. A contender should prioritize proven, high-floor immediate
production and be willing to overpay in ROS value using bench depth or a
future pick, because a losing season has no consolation prize. A rebuilder
should do the opposite: sell veterans and name-value players at their market
peak for youth, unrealized upside, or draft capital, prioritizing long-term
value over a few extra points this month. The same trade can be correctly
"accept" for one team and "reject" for the other with an identical value
delta. ([DynastyNerds](https://www.dynastynerds.com/dynasty/week-12-fantasy-football-trade-advice-buy-sell/), [Fantasy Football Foundry](https://fantasyfootballfoundry.com/articles/dynasty-strategy-trading-as-a-contender))

### 6. Risk-adjust every player, don't just average projections
Trade value should be discounted for: (a) injury status/recency — an "Out"
tag is a much larger discount than "Questionable," and a recently-returned
player carries re-injury and workload-ramp risk beyond the raw status flag;
(b) role security — a player's points depend on a target/carry share that can
be taken by a returning teammate or a coaching change, which is a materially
different risk than a locked-in workhorse producing the same point total; and
(c) bye weeks and remaining-schedule strength, especially strength of schedule
during the fantasy playoffs (typically weeks 15–17), which matters more than
early-season schedule for a contender. A genetic-algorithm trade-optimization
study formalizes this by applying disproportionately higher weight to
projected points in playoff weeks when scoring trade fitness, rather than
weighting all remaining weeks equally. ([arXiv:2511.17535](https://arxiv.org/pdf/2511.17535), [FantasySP](https://www.fantasysp.com/nfl_trade_analyzer/))

### 7. Guard against known evaluator biases
Named failure modes to explicitly check for before recommending a trade:
- **Recency bias** — judging a player mainly on the last 1–2 games rather than a
  3–4 week trend plus underlying usage.
- **Name-brand/prior-expectation bias** — treating a former top pick or
  well-known player as more valuable than current role/production supports,
  or panic-selling a slumping former stud rather than evaluating current role.
- **Raw box-score fixation** — crediting garbage-time yards, one long
  touchdown, or a plus-matchup outlier as sustainable skill rather than
  checking snap/target share and red-zone usage.
- **One-sided framing** — evaluating only "what do I gain" and ignoring
  whether the trade partner's needs are actually served; a trade proposal that
  doesn't also make sense for the other team's context/roster construction is
  unlikely to be accepted and isn't a realistic recommendation.
([RotoWire](https://www.rotowire.com/football/article/common-fantasy-football-rankings-biases-117058), [The Trade Scouter](https://www.thetradescouter.com/news/common-trade-mistakes), [FantasyPros](https://www.fantasypros.com/2026/06/beginners-guide-understanding-fantasy-football-trades/))

## Distilled for the system prompt

- Before valuing any player, establish league mode (redraft vs. dynasty/keeper) and team context (contender vs. rebuilder) — every downstream judgment depends on these two facts.
- Don't just compare raw projected points: apply a replacement-level (VORP) lens — a player's value is what they beat the streamable/waiver option at their position by, not their point total in isolation.
- Watch for tier-emptying effects: an injury or bye that thins a position raises replacement level and quietly increases the value of everyone remaining at that position.
- Weigh consolidation (multiple players for one star) against depth needs: recommend it when the team has real surplus at the position(s) given up, and warn against it when the team is already fragile to bye weeks/injury.
- Separate recent box-score output from underlying opportunity (snap share, target share, red-zone role); flag buy-low candidates whose role outpaces their points, and sell-high candidates whose points outpace their role.
- For a contender, weight immediate/high-floor production and playoff-week (weeks 15–17) schedule strength heavily, and allow overpaying in season-long value to win now. For a rebuilder, weight youth, draft capital, and long-term upside over immediate points, and favor selling name-value/veteran assets at their peak.
- Explicitly risk-adjust for injury status/recency, workload-ramp risk after a return, and role security (is the touch/target share contractually/scheme-guaranteed or contested by a teammate).
- Always evaluate the trade from both teams' perspectives — a trade that doesn't plausibly serve the partner's roster needs and context is not a realistic recommendation, only a wish-list.
- Explicitly guard against and call out: recency bias (over-indexing on 1-2 games), name-brand bias (valuing draft pedigree over current role), and box-score fixation (crediting unsustainable touchdown/garbage-time output as skill).

## Sources

- [RotoBaller — Dynasty Trade Value Chart (Aug 2026)](https://www.rotoballer.com/dynasty-fantasy-football-trade-value-chart-august-updates-2026/1908927)
- [RotoTrade — Trade Value Chart & Trade Analyzer](https://www.rototrade.com/fantasy-football-trade-analyzer)
- [FantasyPros — NFL Trade Value Chart](https://www.fantasypros.com/content/nfl/dynasty-nfl/nfl-trade-value-chart/)
- [FantasyPros — Value-Based Drafting (VORP/VOLS/VONA)](https://www.fantasypros.com/2025/06/fantasy-football-draft-strategy-value-based-drafting-vorp-vols-vona/)
- [Fantasy Analytics Authority — VORP in Fantasy Sports](https://fantasyanalyticsauthority.com/value-over-replacement-player-fantasy)
- [Footballguys — The Ultimate Guide to Fantasy Football Trades](https://www.footballguys.com/article/2023-ultimate-guide-to-trades)
- [FantasyLife — Dynasty 2-for-1 Trade Strategy](https://www.fantasylife.com/articles/dynasty/dynasty-fantasy-football-2-for-1-trade-strategy)
- [RotoWire — Buy Low, Sell High Trade Targets](https://www.rotowire.com/football/article/fantasy-football-trade-targets-players-to-buy-low-sell-high-98607)
- [Oddsmyth — Fantasy Football Trade Strategy](https://oddsmyth.ai/guides/fantasy-football-trade-strategy)
- [DynastyNerds — Trade Advice for Contenders & Rebuilders](https://www.dynastynerds.com/dynasty/week-12-fantasy-football-trade-advice-buy-sell/)
- [Fantasy Football Foundry — Trading as a Contender](https://fantasyfootballfoundry.com/articles/dynasty-strategy-trading-as-a-contender)
- [arXiv:2511.17535 — A Genetic Algorithm for Optimizing Fantasy Football Trades with Playoff Biasing](https://arxiv.org/pdf/2511.17535)
- [FantasySP — Trade Analyzer](https://www.fantasysp.com/nfl_trade_analyzer/)
- [RotoWire — Common Fantasy Football Rankings Biases](https://www.rotowire.com/football/article/common-fantasy-football-rankings-biases-117058)
- [The Trade Scouter — 7 Common Trade Mistakes](https://www.thetradescouter.com/news/common-trade-mistakes)
- [FantasyPros — Beginner's Guide to Understanding Trades](https://www.fantasypros.com/2026/06/beginners-guide-understanding-fantasy-football-trades/)
