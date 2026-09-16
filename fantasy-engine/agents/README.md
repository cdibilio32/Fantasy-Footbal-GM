# Fantasy Football Deep Agents

Three standalone [LangGraph deep agents](https://github.com/langchain-ai/deepagents),
one per decision: **trade proposals**, **waiver proposals**, and **lineup
optimization**. No MCP server, no GitHub Actions — just Python scripts you
run directly, backed by `espn_service.py` for ESPN data and OpenRouter for
the LLM.

## Setup

```bash
cd fantasy-engine/agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ESPN cookies, league id(s), OpenRouter key
```

## Running an agent

```bash
python trade_agent.py                       # all leagues from .env
python waiver_agent.py --league 12345 --team 3
python lineup_agent.py --week 6
```

Each agent prints its recommendation to stdout. See the root `CLAUDE.md`
for the trigger criteria — when each agent is meant to be run.

## How it's put together

- **`espn_service.py`** — the ESPN data layer. Each public method is a
  self-contained "endpoint" (roster, league rosters, available players,
  matchups, transactions) that returns just the shape of data one agent
  needs. See the module docstring and `AGENT_ENDPOINTS` at the bottom for
  which endpoints each agent uses.
- **`common.py`** — the shared OpenRouter model config and the plain-text
  formatters that turn ESPN data into prompt-ready sections.
- **`trade_agent.py` / `waiver_agent.py` / `lineup_agent.py`** — each
  defines its own system prompt (the decision framework) and a small set
  of tools (thin wrappers around the relevant `espn_service` endpoints,
  bound to the league/team being analyzed) and calls
  `deepagents.create_deep_agent(...)`.

Web search for injury news, weather, and Vegas lines is not a custom tool
— it's OpenRouter's hosted `web` plugin, enabled on every model call in
`common.get_model()`.
