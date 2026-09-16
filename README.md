# Fantasy Football AI Manager

Three standalone [LangGraph deep agents](https://github.com/langchain-ai/deepagents),
one per decision: **trade proposals**, **waiver-wire proposals**, and
**lineup optimization** — for a private ESPN Fantasy Football league. No
MCP server, no GitHub Actions, no web app. Just Python scripts you run
directly.

## Quick start

```bash
cd fantasy-engine/agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ESPN cookies, league id(s), OpenRouter key

python trade_agent.py     # trade proposals
python waiver_agent.py    # waiver-wire proposals
python lineup_agent.py    # start/sit lineup optimization
```

Each prints its recommendation to stdout. Nothing is written back to
ESPN — you still apply the lineup/waiver/trade change yourself.

See [`fantasy-engine/agents/README.md`](./fantasy-engine/agents/README.md)
for how the agents are put together, and [`CLAUDE.md`](./CLAUDE.md) for
when each one should be run.
