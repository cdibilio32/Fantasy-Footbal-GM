# Lineup Optimization Strategy Research

This file distills established start/sit and lineup-construction frameworks used by
serious fantasy analysts, for use in the system prompts that back the
`thursday_optimization` and `sunday_check` MCP workflow tasks
(`fantasy-engine/mcp-server/src/services/workflowContext.ts`,
`getTaskSpecificSystemPrompt`). The existing prompts name good high-level focus areas
(injury analysis, weather, matchups, ceiling vs. floor) but don't give the LLM concrete
*criteria* for applying them — and the rule-based fallback optimizer
(`fantasy-engine/mcp-server/src/tools/lineup.ts`) only ranks by raw `projectedPoints`.
The frameworks below are the "beyond raw projections" layer the LLM should add.

## Decision Frameworks

**1. Floor vs. ceiling calibrated to matchup context, not just record.** Don't apply
one risk posture to a whole roster. For each lineup slot ask: what does *this* team need
this week? A team favored to win comfortably should default to floor (safe, consistent
scorers); a team that needs a big week to survive should chase ceiling, because a low
floor is irrelevant if losing ends the matchup anyway. The sharper version of this rule
uses the *opponent's projected score*, not team record, as the trigger — if the opponent
projects to 130+, take upside even with a good record; if they project to ~85, floor
plays are safe even for a struggling team. ([RotoWire](https://www.rotowire.com/football/article/fantasy-football-start-em-sit-em-strategy-99605), [4for4](https://www.4for4.com/fantasy-football-rankings/half-ppr-rankings/lineup))

**2. Vegas implied team totals as a volume proxy.** Derive each team's implied point
total from the spread and over/under (`(total + spread)/2` for the favorite,
`(total - spread)/2` for the underdog). Higher implied totals correlate with more
offensive plays and more scoring opportunities for that team's skill players — useful as
a tiebreaker between two similarly-projected players, and as an early red flag when a
team's implied total drops sharply (line movement, likely-blowout game). ([SharpFootballAnalysis](https://www.sharpfootballanalysis.com/fantasy/nfl-implied-team-totals-tool/), [TheGameSnap](https://thegamesnap.com/articles/how-to-use-vegas-implied-team-totals-a-2026-fantasy-and-betting-playbook))

**3. Game script — spread direction predicts *which* skill position benefits.**
Positive game script (team leading) favors early-down/goal-line running backs as the
offense runs out the clock; negative game script (team trailing) favors receivers and
pass-catching backs as the offense abandons the run to catch up ("garbage time" volume).
Large spreads (>7) are the strongest signal: a big favorite's bell-cow RB gains, a big
underdog's WRs/pass-catching RB gain from volume even in a likely loss. Not all RBs are
equally game-script-dependent — pure between-the-tackles runners lose the most in
negative script; three-down backs with receiving work are more script-neutral. ([PFF](https://www.pff.com/news/fantasy-football-metrics-that-matter-gamescript-dependent), [Fantasy Points](https://www.fantasypoints.com/nfl/articles/2020/how-game-script-affects-fantasy), [SI](https://www.si.com/fantasy/2021/08/10/football-game-script-impact-running-backs))

**4. Matchup quality beyond "defense rank."** Aggregate positional defense rank (e.g.
"points allowed to RBs") is noisy and lags — it's built on whoever that defense has
faced, not underlying scheme quality. Prefer usage-first signals: a player's own target
share (28-32%+ signals a true focal point regardless of matchup) and air yards/aDOT
establish whether he's even in a position to exploit a good matchup; only then layer in
opponent tendency (yards/target allowed, DVOA-style efficiency, whether the defense's
weak spot — e.g. linebackers vs. pass-catching backs and TEs — aligns with the player's
specific role). Fantasy points allowed per game is the sanity-check stat, but shouldn't
be used alone. ([FantasyPros glossary](https://www.fantasypros.com/fantasy-football-deep-stat-analysis-glossary-guide/), [Matchup Analytics](https://matchupanalytics.com/advanced-metrics-in-matchup-analysis/), [Footballguys forums](https://forums.footballguys.com/threads/do-starts-and-sits-really-work.818576/))

**5. Shadow/man coverage as a WR discount, applied selectively.** When a team's top
cornerback is confirmed to shadow (follows one receiver across the formation on the
majority of snaps, not just when aligned on one side), it measurably suppresses that
receiver's fantasy output — but shadow assignments vary game to game and by corner
quality, and no CB can shadow effectively into the slot. Only apply this discount when
shadow coverage is specifically reported for the week, and discount less for receivers
who play heavily from the slot. ([PFF: shadow coverage impact](https://www.pff.com/news/fantasy-football-the-impact-of-shadow-coverage-on-receivers-fantasy-production), [PFF: shadow report](https://www.espn.com/fantasy/football/insider/story/_/id/41302075/fantasy-football-wide-receiver-cornerback-matchups-upgrades-nfl-week-3))

**6. QB-pass catcher correlation raises ceiling, lowers floor — use only when
ceiling is the goal.** Rostering a QB with his own WR/TE means their outcomes move
together: when the QB has a big game the pass-catcher usually does too (stacked upside),
but a QB down game usually drags the pass-catcher down with it (correlated bust). This is
a DFS/tournament concept, weaker in season-long formats — don't bench a clearly better
player just to force a stack. It's a legitimate *tiebreaker* specifically in must-win,
ceiling-seeking weeks (framework #1), not a standing preference. ([RotoGrinders](https://rotogrinders.com/articles/pairing-a-qb-with-his-receiver-s-481544), [Establish The Run](https://establishtherun.com/deep-dive-stacking-in-season-long-fantasy/))

**7. Weather thresholds are graduated, not binary.** "Bad weather" isn't a single
flag — wind is the dominant fantasy-relevant variable, not rain/cold alone:
sustained wind ≥15 mph starts to measurably suppress completion percentage and kicker
accuracy; ≥20 mph is a meaningful passing/kicking penalty; ≥25 mph produces a sharp drop
in QB yards/attempt (roughly -18%) and should trigger real caution on
QB/WR/kicker ceiling and a lean toward the run game. Heavy rain/snow has a similar but
milder run-funneling effect. Check gusts as well as sustained speed, and check again
close to kickoff — forecasts move. ([PFN weather report](https://www.profootballnetwork.com/fantasy-hq/weather-report), [Fantasy Life](https://www.fantasylife.com/articles/best-ball/does-wind-matter-in-fantasy-football))

**8. Injury designation is a weak signal; practice trend and snap-share are the
strong ones.** "Questionable" players have historically played in roughly 75% of
games (and "probable," before it was retired, in ~95%) — so the label alone is closer to
a coin-flip-plus than a real warning. What matters is the trajectory across the
practice week (DNP → limited → full is trending toward playing; full → limited → DNP is
trending toward sitting) and, once a player does suit up, his post-injury snap share —
a real usage signal that often persists even after the injury is no longer a story.
When a backup has inherited a starter's snap share during an injury, that snap-share
data point is more predictive of upcoming role than the returning starter's own health
tag. ("Doubtful" is a much stronger signal than "questionable" and should be treated as
closer to out.) ([ESPN injury report explainer](https://www.espn.com/blog/nflnation/post/_/id/215133/how-to-decode-the-nfls-new-injury-report-designations), [Footballguys: chance to play](https://www.footballguys.com/article/2024-injury-index-chance-to-play-questionable-vs-doubtful), [Draft Sharks snap counts](https://www.draftsharks.com/article/nfl-snap-counts))

**9. Game-theory leverage against your specific opponent, not the field.** In
head-to-head fantasy (unlike DFS tournaments), the only opponent that matters is the one
you're facing that week. If your opponent already has a stronger player locked in at a
position, matching a marginal alternative doesn't help — you need separation, which
means it's sometimes correct to start a bench-quality but high-variance player specifically
*because* you're already going to lose that positional battle on paper and need the
upside swing. This only applies to the matchup at hand — it is not a reason to bench a
clear stud. ([RotoWire](https://www.rotowire.com/football/article/fantasy-football-start-em-sit-em-strategy-99605))

## Distilled for the system prompt

### Thursday-early lock (`thursday_optimization`) — more uncertainty remains, require a bigger margin to deviate from the safe/projected play

- Set the overall floor/ceiling posture for the week now, using the opponent's
  *projected* score and your matchup situation (framework #1) — this is a strategic call
  that should be made early and referenced again Sunday for consistency.
- Pull Vegas lines and implied totals now as the first-pass signal for expected
  workload/game script (frameworks #2-3); treat these as provisional since lines can
  move materially by Sunday.
- For players with in-week injury designations, do not overreact to Wednesday/Thursday
  "questionable" tags alone (framework #8) — flag them for re-check, but don't bench a
  clearly superior starter on a Thursday DNP/limited alone; require either a stated high
  bench probability or a full week of downward practice trend before pivoting off him
  this early.
- Weather forecasts 3+ days out are directional at best; note a rough-forecast game as a
  watch item (framework #7) rather than a hard start/sit trigger yet.
- Bigger bar for change than Sunday: only override the higher-projection default when a
  framework gives strong, multi-signal conviction (e.g., bad matchup *and* negative game
  script *and* weak recent usage) — Thursday's job is to lock in a strong default lineup
  and flag genuine question marks for Sunday follow-up, not to make every close call now.
- TNF players are the one true Thursday-only hard deadline — they must be fully decided
  now; treat every other position as "decide with current-best info, revisit Sunday."

### Sunday-late pivot (`sunday_check`) — most uncertainty has resolved, act decisively on confirmed information

- Re-pull injury/inactive lists as the primary input; a player ruled out or listed
  "doubtful" is a near-certain sit, and a confirmed "active/no game-time decision" late
  Sunday morning should override any lingering Thursday hesitation (framework #8).
- Re-check snap-share/role signals if any new information (a healthy scratch, a
  surprise inactive elsewhere on the roster) emerged since Thursday — this is the
  strongest late signal available (framework #8).
- Re-check the Vegas line and weather forecast one more time — a line that moved 3+
  points, or a wind forecast that has climbed past 15-20 mph, changes the
  game-script/passing-game read from Thursday (frameworks #2-3, #7) and should be
  weighted over the Thursday snapshot.
- Compare against the Thursday analysis explicitly: only change a Thursday call when
  there's a specific, nameable piece of new information (news, weather, snap-share
  shift, line movement) — don't second-guess a sound Thursday call just because a
  close alternative exists; unlike Thursday, however, once that trigger exists, act on
  it fully rather than hedging, since there's little time left for the situation to
  change again.
- This is the point to weigh game-theory leverage against your specific opponent's
  already-set lineup, if visible (framework #9) — Thursday is too early for this since
  the opponent's lineup isn't locked yet.
- Ceiling/floor posture from Thursday (framework #1) should generally carry through
  unless the opponent's own last-minute inactives materially change their projected
  score.

## Sources

- [RotoWire — Fantasy Football Start 'Em/Sit 'Em Strategy Guide](https://www.rotowire.com/football/article/fantasy-football-start-em-sit-em-strategy-99605)
- [4for4 — Fantasy Football Start/Sit Tool](https://www.4for4.com/fantasy-football-rankings/half-ppr-rankings/lineup)
- [Footballguys forums — Do starts and sits really work?](https://forums.footballguys.com/threads/do-starts-and-sits-really-work.818576/)
- [Sharp Football Analysis — NFL Implied Team Totals Tool](https://www.sharpfootballanalysis.com/fantasy/nfl-implied-team-totals-tool/)
- [TheGameSnap — NFL Implied Team Totals: Formula, Examples, and Fantasy Uses](https://thegamesnap.com/articles/how-to-use-vegas-implied-team-totals-a-2026-fantasy-and-betting-playbook)
- [PFF — Metrics that Matter: Players most dependent on gamescript](https://www.pff.com/news/fantasy-football-metrics-that-matter-gamescript-dependent)
- [Fantasy Points — How Game Script Affects Fantasy](https://www.fantasypoints.com/nfl/articles/2020/how-game-script-affects-fantasy)
- [Sports Illustrated — Game Script Impact on Fantasy Football Production: RBs](https://www.si.com/fantasy/2021/08/10/football-game-script-impact-running-backs)
- [FantasyPros — Fantasy Football Deep Stat Analysis Glossary & Guide](https://www.fantasypros.com/fantasy-football-deep-stat-analysis-glossary-guide/)
- [Matchup Analytics — Advanced Metrics Used in Fantasy Matchup Analysis](https://matchupanalytics.com/advanced-metrics-in-matchup-analysis/)
- [PFF — The impact of shadow coverage on receivers' fantasy production](https://www.pff.com/news/fantasy-football-the-impact-of-shadow-coverage-on-receivers-fantasy-production)
- [ESPN — Fantasy Football Shadow Report: Key WR/CB matchups](https://www.espn.com/fantasy/football/insider/story/_/id/41302075/fantasy-football-wide-receiver-cornerback-matchups-upgrades-nfl-week-3)
- [RotoGrinders — Pairing a QB with his Receiver(s)](https://rotogrinders.com/articles/pairing-a-qb-with-his-receiver-s-481544)
- [Establish The Run — Deep Dive: Stacking in Season-Long Fantasy](https://establishtherun.com/deep-dive-stacking-in-season-long-fantasy/)
- [Pro Football Network — NFL Weather Report: Fantasy Impact Analysis](https://www.profootballnetwork.com/fantasy-hq/weather-report)
- [Fantasy Life — Does Wind Matter in Fantasy Football?](https://www.fantasylife.com/articles/best-ball/does-wind-matter-in-fantasy-football)
- [ESPN — How to decode the NFL's new injury report designations](https://www.espn.com/blog/nflnation/post/_/id/215133/how-to-decode-the-nfls-new-injury-report-designations)
- [Footballguys — Chance to Play: Questionable vs. Doubtful](https://www.footballguys.com/article/2024-injury-index-chance-to-play-questionable-vs-doubtful)
- [Draft Sharks — NFL Snap Counts in 2025: Trends to Watch For](https://www.draftsharks.com/article/nfl-snap-counts)
