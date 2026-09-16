# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESPN Fantasy Football AI Manager — three standalone LangGraph **deep agents**
that each make one kind of decision for a private ESPN Fantasy Football
league: trade proposals, waiver-wire proposals, and lineup optimization.
There is no MCP server, no GitHub Actions automation, and no web app — just
Python scripts you (or a Claude Code session) run directly, on demand.

## Tech Stack

**Agents**: Python, [`deepagents`](https://github.com/langchain-ai/deepagents) (LangGraph under the hood), `langchain-openai`
**Data**: `fantasy-engine/agents/espn_service.py` — a direct client for ESPN's private fantasy football read API (cookie auth, no Puppeteer)
**LLM**: OpenRouter only (`OPENROUTER_API_KEY` / `OPENROUTER_MODEL`), with OpenRouter's hosted `web` plugin standing in for a dedicated search tool

## Project Structure

```
fantasy-engine/
├── agents/
│   ├── espn_service.py    # ESPN data layer — one method per data "endpoint"
│   ├── common.py          # OpenRouter model config + prompt-formatting helpers
│   ├── trade_agent.py     # deep agent: trade proposals
│   ├── waiver_agent.py    # deep agent: waiver-wire proposals
│   ├── lineup_agent.py    # deep agent: lineup optimization
│   ├── memories.md        # standing preferences learned from feedback (see below)
│   ├── requirements.txt
│   └── .env.example
└── docs/prompt-engineering/   # research notes the agents' prompts are distilled from
```

## Essential Commands

```bash
cd fantasy-engine/agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ESPN cookies, league id(s), OPENROUTER_API_KEY

python trade_agent.py                      # every league configured in .env
python waiver_agent.py --league ID --team ID
python lineup_agent.py --week 6
```

### Running an agent from a Claude Code session

Run it the same way a human would, using the session's own environment
variables (`ESPN_S2`, `ESPN_SWID`, `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID`,
`OPENROUTER_API_KEY`):

```bash
cd fantasy-engine/agents
pip install -r requirements.txt
python trade_agent.py --league "$ESPN_LEAGUE_ID" --team "$ESPN_TEAM_ID"
# swap trade_agent.py for waiver_agent.py / lineup_agent.py as needed
```

Each agent prints its recommendation to stdout — nothing gets written back
to ESPN. A human still has to apply the lineup/waiver/trade changes
manually.

## Agent Trigger Criteria

Run these proactively when the situation below applies — don't wait to be
asked every time. All three are safe to re-run any time; each pulls live
ESPN data (and live web search for injury/weather/Vegas-line context) on
every run rather than caching anything.

### `trade_agent.py` — trade proposals

Run when:
- **Weekly, Monday–Tuesday**, once that week's scores are final — trade
  value shifts the most right after a week's performances land.
- A rostered player (yours or a league-mate's) suffers a notable injury,
  role change, or is traded/cut in real life — trade value just moved.
- The user is deciding whether to buy or sell before the league's trade
  deadline (typically weeks 9–12) — run it explicitly for a contender/
  rebuilder read.
- The user directly asks for trade ideas, or to evaluate a specific trade.

Don't run it once the league's trade deadline has passed for the season.

### `waiver_agent.py` — waiver-wire proposals

Run when:
- **Weekly, Tuesday**, after Monday Night Football completes and that
  week's waiver processing runs — this is the primary weekly waiver
  window for most leagues.
- A rostered starter is ruled out or lands on IR with no ready bench
  replacement — run it immediately rather than waiting for Tuesday.
- A bye week or an IR-eligible return is 1–2 weeks out at a thin position
  — get ahead of it instead of reacting the week it hits.
- The user directly asks who to pick up or drop.

### `lineup_agent.py` — lineup optimization

Run when:
- **Thursday**, once Thursday Night Football's injury reports are out —
  first full-roster pass, with the understanding that later injury/weather
  news can still change calls before Sunday.
- **Sunday morning, close to kickoff** — final check once inactives are
  official; treat this run's output as the one to trust over Thursday's
  wherever they disagree, since uncertainty has mostly resolved by then.
- Breaking injury news, a weather forecast, or a Vegas line move on any of
  the user's players' games — re-run to get an updated read rather than
  trusting a stale one.
- The user directly asks for a start/sit call.

## ESPN Data Endpoints (`espn_service.py`)

Auth is two cookies from a browser logged into fantasy.espn.com
(`ESPN_S2`, `ESPN_SWID`); only needed for private leagues.

| Endpoint | Returns | Used by |
|---|---|---|
| `get_league_info(league_id)` | League name, current scoring week, team list | all |
| `get_team_roster(league_id, team_id)` | One team's starters/bench/IR, weekly-reconciled projections | trade, lineup |
| `get_league_rosters(league_id)` | Every team's roster (season points, ownership) — real trade partners | trade |
| `get_available_players(league_id)` | Free agents / waiver-wire players, <50% owned | trade, waiver (via `get_my_roster_with_top_waivers`) |
| `get_my_roster_with_top_waivers(league_id, team_id)` | Own roster + top free agents per position | waiver |
| `get_matchups(league_id, week)` | That week's matchup schedule | lineup |
| `get_transactions(league_id)` | Recent adds/drops/trades | (available, currently unused by any agent) |
| `get_current_week(league_id)` | ESPN's own current scoring period (asks ESPN directly; not calendar-guessed) | all |

## Learned Preferences (`memories.md`)

`fantasy-engine/agents/memories.md` holds standing preferences and
corrections learned from user feedback on past recommendations (e.g. "this
league doesn't allow trading draft picks"). `common.py::load_memories()`
reads it and `build_system_prompt()` appends it to every agent's system
prompt, so an entry here changes behavior on every future run of any of the
three agents, not just in chat. It's maintained by the `remember-feedback`
Claude Code skill (`.claude/skills/remember-feedback/`) — trigger it with
feedback like "remember this" or a correction on an agent's output. Don't
hand-edit the file outside that skill unless fixing a bad entry.

## Development Guidelines

1. Every agent's tools call `espn_service.py` — never inline a raw ESPN API
   call inside an agent file. Add a new endpoint there if a prompt needs
   data none of the existing ones return.
2. Keep each agent's system prompt scoped to its one decision (lineup /
   waiver / trade) — resist folding a second decision type into one agent.
3. Don't reintroduce a second LLM provider path — OpenRouter only. Web
   search is OpenRouter's `web` plugin (`common.get_model()`), not a
   custom tool.
4. Test against a real league before calling a prompt change done —
   `python <agent>.py --league ID --team ID` with real `.env` values.
