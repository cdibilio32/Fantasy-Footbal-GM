# Prompting DeepSeek V4 Flash

Research notes on how to write system/user prompts that get the best results
from **DeepSeek V4 Flash**, the model this app's LLM-driven commands
(`thursday`, `sunday`, `tuesday`, `workflow --task trade_analysis`) target via
the `openrouter` and `deepseek` providers in
`fantasy-engine/shared/src/services/llm/`.

## What the model actually is

- Mixture-of-Experts: 284B total params, ~13B activated per token.
- 1,048,576-token (1M) context window — headroom is not the constraint;
  clarity and structure are.
- **Non-reasoning / "Flash" variant**: optimized for fast, direct answers
  rather than long internal deliberation. This is the opposite design point
  from `deepseek-reasoner` (R1-family) — do not prompt it like a reasoning
  model.
- Supports native `tools` / `tool_choice` function calling and structured
  JSON output via `response_format` — both of which this app already relies
  on (`getFantasyTools()` in `llm/manager.ts`).
- Priced with a steep cache-read discount (~75-97% off input cost on a
  cache hit), which rewards keeping the system prompt byte-for-byte stable
  across calls.

Sources:
[DeepSeek V4 Flash — OpenRouter](https://openrouter.ai/deepseek/deepseek-v4-flash),
[DeepSeek V4 Prompting Techniques — Lightrains](https://lightrains.com/blogs/deepseek-ai-prompting-techniques/),
[DeepSeek Prompting Techniques — datastudios.org](https://www.datastudios.org/post/deepseek-prompting-techniques-strategies-limits-best-practices-etc)

## Rules to design prompts around

1. **Use the system prompt to lock in persona, constraints, and output
   format.** Unlike the R1 reasoning family (where instructions belong in
   the user turn because a system prompt fights the hidden chain-of-thought),
   V4-class chat/flash models respond well to a detailed system prompt that
   defines role, domain expertise, and rules. This app's existing pattern
   (`workflowContext.ts::buildSystemPrompt`) is already directionally right
   — keep it that way.

2. **Don't ask for step-by-step deliberation — ask for the answer, already
   structured.** V4-Flash performs best with direct-answer prompts, not
   open-ended "think it through" instructions (save that framing for a
   `-pro`/reasoning tier). Replace "explain your reasoning" style asks with
   an explicit output contract: numbered recommendation, confidence score,
   one-line justification. Structure does the work that chain-of-thought
   would otherwise do.

3. **Structure the prompt like CO-STAR, not like prose.** Context, Objective,
   Style/format, Tone, Audience, Response shape — as labeled sections, not a
   paragraph. Concretely: a "Current Context" block, a numbered "Focus Areas"
   list, a "Key Principles" list, and a "Response Format" block. The current
   system prompts already do most of this; the gap is that some task
   branches (trade especially) skip the explicit Response Format section.

4. **Be concrete, never vague.** "Make good lineup calls" underperforms
   "Compare each starter against their best bench alternative at the same
   position; flag any gap where the bench player's projection exceeds the
   starter's by more than 2 points." Ambiguous verbs ("optimize", "consider")
   should be paired with the concrete criterion that resolves them.

5. **One language, one register, per prompt.** Mixing tester slang, all-caps
   emphasis headers, and formal analyst language in the same prompt measurably
   hurts consistency. Keep the emphatic ALL-CAPS section labels (they act as
   structural markers, which V4-Flash uses well) but keep sentence-level tone
   consistent and plain.

6. **Give a numbered task list, not a wall of bullets.** Numbered steps read
   as a decomposed task the model executes in order; unordered bullets read
   as optional flavor. Every "Focus on:" section in this codebase should be
   numbered (most already are).

7. **State the output contract explicitly, every time.** Always end the
   system prompt with an explicit "Response Format" section: what sections
   to produce, in what order, and any required fields (confidence 1-10,
   FAAB $ amount, START/BENCH/ADD/DROP/TRADE keyword so
   `llmManager.parseRecommendations()` can regex-extract it — see
   `manager.ts:377-398`). The parser is keyword-driven, so the prompt's
   output contract is not just style guidance, it's a functional dependency.

8. **Keep the system prompt static across calls in the same task family.**
   Interpolate week number / league names / task name, but don't rewrite the
   instructional text itself per call — that's what makes the KV-cache
   discount apply and keeps behavior consistent run over run. Put anything
   that changes every single call (roster data, this week's injury list) in
   the **user** message, not the system message.

9. **Function calling: describe tools like part of the plan, not an
   afterthought.** V4-Flash calls tools well when the system prompt states
   *when* to call each one ("Always start by calling `get_roster` for each
   league before making any recommendation") rather than just listing them.
   The existing "WORKFLOW REQUIREMENT" line in `workflowContext.ts` is the
   right pattern — keep and sharpen it per task.

10. **Treat it as more jailbreak/injection-susceptible than GPT/Claude-class
    models.** Because this app feeds live, external, semi-untrusted text
    into prompts (opponent trade offers, ESPN news blurbs, player names),
    the system prompt should explicitly scope the model to *advice only*
    ("You recommend actions; you do not execute transactions") and should
    not treat any data payload as instructions. This matters most for the
    trade prompt, which is the one place another human's freeform input
    (a trade offer) flows into the model's context.

## Anti-patterns found in this codebase (fixed as part of this work)

- `trade_analysis` had no dedicated system-prompt branch at all — it fell
  through to `'General fantasy football analysis focusing on optimal
  decision-making.'`, which violates almost every rule above (no context,
  no output contract, no numbered focus areas).
- None of the four task prompts had an explicit final "Response Format"
  contract lining up with what `parseRecommendations()` actually greps for
  (`START:` / `BENCH:` / `ADD:` / `DROP:` / a `%` confidence).
- `getFocusAreas()` lists exist in `aiWorkflowOrchestrator.ts` but aren't
  threaded into the system prompt itself — the prompt and the metadata
  describing it had drifted apart.
