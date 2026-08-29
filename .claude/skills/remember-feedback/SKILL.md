---
name: remember-feedback
description: Capture feedback about the Fantasy Football AI Manager's recommendations (waiver, trade, lineup, or intelligence output) into fantasy-engine/automation/memories.md so future CLI runs apply it. Trigger on phrases like "remember this", "add that to memory", "update memory/memories", "learn from that/this feedback", or when the user corrects, praises, or states a standing preference about a recommendation the CLI (monday/tuesday/thursday/sunday/workflow/intelligence) just produced.
---

# Remember Feedback

Turns a piece of user feedback into a durable, distilled entry in
`fantasy-engine/automation/memories.md`. That file is read on every AI workflow
call (`aiWorkflowOrchestrator.ts::loadMemories()`) and injected into the LLM
prompt as a "LEARNED PREFERENCES" section — so an entry written here changes
behavior on every future `monday`/`tuesday`/`thursday`/`sunday`/`workflow`/
`intelligence` run, not just in chat.

## When this triggers

- Explicit asks: "remember this", "add to memory", "update memories.md", "learn
  from that feedback", "learn from my comments"
- Implicit feedback on a recommendation the CLI just produced or that's being
  discussed: a correction ("don't suggest streaming defenses, I always keep
  one"), a standing preference ("I'd rather take upside over floor in best-ball
  weeks"), or praise for a pattern worth reinforcing ("that trade logic was
  right, keep prioritizing 2-for-1 consolidation")

Don't trigger on feedback about something unrelated to the fantasy app's
recommendations (e.g. feedback on this session's code changes) — that's normal
conversation, not a memory entry.

## Process

1. **Find the feedback.** Use the current turn if it's the feedback itself.
   If the user says "learn from my comments/the comments" without repeating
   them, scan back through this conversation to find the relevant exchange —
   look for the CLI output/recommendation being discussed and what the user
   said about it afterward.

2. **Distill, don't transcribe.** Write one short, general, durable bullet —
   not a verbatim quote, not tied to one specific player or week unless the
   preference is genuinely that narrow. Ask: will this still be useful advice
   in 5 weeks? If the feedback is purely a one-off reaction with no reusable
   preference in it, say so and skip writing an entry rather than forcing one.

3. **Read `fantasy-engine/automation/memories.md`.** Create it from this
   template if it's missing:
   ```
   # Memories

   Standing preferences and corrections learned from feedback on past recommendations.
   This file is read automatically on every AI workflow call (Monday/Tuesday/Thursday/
   Sunday/workflow/intelligence) and injected into the prompt — keep entries short,
   durable, and general rather than one-off complaints about a single player/week.

   Maintained by the `remember-feedback` skill (`.claude/skills/remember-feedback/`).
   Do not hand-edit unless you're correcting a bad entry — let the skill do the merging.

   <!-- Entries go below this line, oldest first. -->
   ```

4. **Merge, don't just append.** Read the existing bullets first:
   - If the new feedback contradicts an existing entry, replace that entry
     rather than leaving both (a stale + a new preference confuses the LLM).
   - If it's a near-duplicate of an existing entry, tighten/merge instead of
     adding a second, similar bullet.
   - Otherwise, append it as a new `- ` bullet at the end of the list.
   - If the file is growing long (a few dozen entries), take the opportunity
     to consolidate obviously-related bullets into one — the whole file gets
     re-sent on every LLM call, so keep it tight.

5. **Commit the change.** Stage and commit just `fantasy-engine/automation/memories.md`
   with a message describing the learned preference (e.g. `memories: prefer 2-for-1
   trade consolidation over 1-for-1`). Invoking this skill is the explicit request
   to persist the change, so commit without asking first — but do **not** push.
   GitHub Actions only sees pushed commits, so tell the user the entry is
   committed locally and ask if they want it pushed now (or note that it'll go
   out with their next normal push) — don't push on their behalf.

6. **Confirm back in one or two lines**: what you captured (the actual bullet
   text), and whether anything existing was merged/replaced.
