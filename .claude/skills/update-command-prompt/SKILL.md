---
name: update-command-prompt
description: Update the actual LLM system prompt (not just memories.md) for the thursday, sunday, monday, tuesday, or trade command based on feedback given after a run. Trigger on phrases like "update the trade/waiver/lineup command", "update the thursday/sunday/tuesday prompt", "tune that command based on my feedback", or "fix the prompt so it stops doing X" said after discussing that command's output. Distinct from remember-feedback: this edits the engineered system prompt in code, not the standing-preferences data file.
---

# Update Command Prompt

Turns feedback about a command's *behavior* — the wrong things it focused on,
a missing step, a bad output format, a tone that isn't landing — into an edit
of the actual engineered system prompt for that command, not a data file.

## Two different feedback destinations — pick the right one

This app has two places feedback can go, and they are not interchangeable:

- **`fantasy-engine/automation/memories.md`** (owned by the `remember-feedback`
  skill): standing *preference/fact* bullets injected as data into every
  prompt — "I always keep two kickers," "prioritize 2-for-1 consolidation."
  If the user's feedback is really this — a durable fact or preference about
  *their* team/league, not about how the AI reasons — stop and suggest (or
  invoke) `remember-feedback` instead. Don't edit code for this.
- **The engineered system prompt itself** (this skill): feedback about the
  *prompt engineering* — the AI focused on the wrong thing, skipped a step,
  used the wrong output format, was too hedgy/vague, ignored a factor it
  should always check, or the response structure needs to change. This is a
  change to instructions in code, which then applies to every future run
  regardless of team/league specifics.

A single piece of feedback can be both ("your trade prompt never asks about
bye weeks, and also I always want you to protect my two kickers" — the first
is a prompt fix, the second is a memory). Handle each half with the right
tool; don't force one into the other.

## Where each command's prompt actually lives

There are two prompt-authoring locations that must be kept in sync — the
first is the one that actually runs in production, the second is a parallel
implementation for the Claude Desktop MCP integration:

1. **`fantasy-engine/shared/src/tools/aiWorkflowOrchestrator.ts`**, function
   `getTaskInstructions(task, week)`. This is the live path — it's what
   `fantasy-ai thursday/sunday/monday/tuesday/trade` actually calls via
   `executeAIWorkflow`. Each `case` in the switch statement is one command's
   focused instructions + response format contract.
2. **`fantasy-engine/mcp-server/src/services/workflowContext.ts`**, method
   `getTaskSpecificSystemPrompt(task, week)`. Same four-plus-trade task
   split, used by the Claude Desktop MCP tool path. Update the matching case
   here too so the two don't drift apart.

Map the user's command name to the right case:
- "lineup" / "thursday" → `thursday_optimization`
- "lineup" / "sunday" (final check, or unspecified which lineup command and
  the feedback is about last-minute/pivot behavior) → `sunday_check`
- "waiver" / "tuesday" → `tuesday_waivers` (the deep waiver-strategy prompt);
  "monday" is a lighter post-game/early-waiver-scan pass — only touch it if
  the user names Monday specifically
- "trade" → `trade_analysis`

If it's ambiguous which command the user means (e.g. they just say "the
lineup command" with two candidates), ask which one rather than guessing —
these prompts have deliberately different framing (Thursday: bigger margin
to deviate, more hedging; Sunday: act decisively on confirmed info) and
editing the wrong one is a real regression, not a no-op.

## Process

1. **Find the feedback.** If the user's current message states the feedback
   directly, use that. If they say "update the command based on what I just
   said" or similar without repeating it, scan back through this
   conversation for: the run's output (pasted CLI/Discord output, or a
   `*_results.json` summary) and what the user said about it afterward —
   what was wrong, missing, or should be emphasized differently. If you
   can't find concrete feedback in the transcript, ask the user directly
   rather than inventing a change.

2. **Classify the feedback** using the two-destinations test above. Route
   pure standing-preference feedback to `remember-feedback` instead (or in
   addition, if it's a mixed case).

3. **Read before editing:**
   - The current `getTaskInstructions` case (or `getTaskSpecificSystemPrompt`
     case) for the target command, in both files above.
   - `fantasy-engine/docs/prompt-engineering/deepseek-v4-flash-prompting.md`
     — the model-level prompting rules every edit must keep following:
     numbered steps not prose, concrete criteria not vague verbs ("optimize"
     paired with what resolves it), one explicit Response Format contract,
     consistent register, no chain-of-thought requests (this model performs
     direct-answer, not deliberation-style prompting).
   - The matching domain research file for extra grounding if the feedback
     points at a decision-framework gap rather than a formatting one:
     `lineup-optimization-strategy.md` (thursday/sunday),
     `waiver-wire-strategy.md` (tuesday/monday), or
     `trade-analysis-strategy.md` (trade). These list frameworks already
     distilled into the current prompts — check whether the feedback is
     actually calling for one that's listed there but didn't make it into
     the prompt text, versus something genuinely new.

4. **Make the smallest edit that fixes the behavior.** Prefer:
   - Adding or sharpening one numbered focus-area line over rewriting the
     whole block.
   - Tightening the Response Format contract if the complaint is about
     output shape/structure.
   - Only restructure the full case when the feedback is about the command's
     fundamental framing, not a single missing consideration.
   Keep every edit consistent with the DeepSeek prompting rules above —
   don't introduce vague instructions, prose paragraphs, or an implicit
   format the parser/reader can't rely on.

5. **Apply the same edit to both files** (`aiWorkflowOrchestrator.ts` and
   `workflowContext.ts`) for the matching task case, so the two prompt paths
   don't diverge. Wording can differ slightly to fit each file's existing
   style, but the substantive instruction must match.

6. **Verify it compiles.** Run `cd fantasy-engine/shared && npm run build`
   (and `cd fantasy-engine/mcp-server && npm run build:local` if that
   package is in a buildable state at the time — check for pre-existing
   unrelated errors first with `git stash` if unsure, the same way this
   feature was originally built, rather than assuming a fail is yours).

7. **Show the user the before/after** of the changed instruction line(s) —
   don't just say "updated," quote the diff.

8. **Commit the change** (both files) with a message naming the command and
   the behavioral fix, e.g. `prompts: tighten trade_analysis bye-week risk
   check per feedback`. Invoking this skill is the explicit request to
   persist the change, so commit without asking first — but do **not**
   push. Tell the user it's committed locally and ask if they want it
   pushed now (GitHub Actions only runs on pushed commits).

9. **Confirm back in a few lines**: which command's prompt changed, the
   specific instruction added/modified (quote it), and whether any part of
   the feedback was routed to `remember-feedback` instead.
