# Memories

Standing preferences and corrections learned from feedback on past recommendations.
This file is read automatically by every agent (trade_agent.py / waiver_agent.py /
lineup_agent.py, via `common.py::load_memories()`) and appended to the system
prompt — keep entries short, durable, and general rather than one-off complaints
about a single player/week.

Maintained by the `remember-feedback` skill (`.claude/skills/remember-feedback/`).
Do not hand-edit unless you're correcting a bad entry — let the skill do the merging.

<!-- Entries go below this line, oldest first. -->
- This league does not allow trading draft picks. Never include a draft pick (e.g. "+ a 2nd-round pick") as part of a suggested trade package — trade proposals must be player-for-player only.
- When a proposed trade names a player being given up, list that player's season average points, positional ranking, and last year's variance-to-average (consistency), not just this week's/current points — the recipient needs the fuller value picture to judge the trade.
