---
name: retro
description: >
  Brutally honest retrospective on the user's working session. Analyzes conversation history,
  git activity, and file changes to identify habits, blind spots, and the single highest-impact
  improvement. Triggered ONLY by explicit slash commands: /retro or /review-my-work.
  Also supports /retro {commit-hash} to review a specific commit's work session.
  Do NOT trigger from general questions about work quality or vague "how am I doing" queries
  unless the exact slash command is used.
---

# Session Retrospective

Deliver a blunt, structured retrospective on the user's recent work. No flattery, no softening.
The goal is to surface patterns the user can't see themselves because they're inside the work.

## Before You Start: Gather Evidence

The retrospective must be grounded in observable facts. Before writing anything, collect:

1. **Conversation history** - the full session up to this point. This is your primary source.
2. **Git activity** - run `git log --oneline -20` and `git diff --stat` to see what changed.
3. **If a commit hash is provided** (e.g. `/retro abc1234`): run `git show --stat {hash}` and
   `git log --oneline {hash}~5..{hash}` to reconstruct the surrounding work session.
4. **File change patterns** - look at which files were touched, how many times, in what order.

If the conversation is fewer than ~5 substantive exchanges AND no commit hash is provided,
refuse politely: "Not enough material for a meaningful retro. Give me a commit hash or keep
working and ask again later."

Use judgment: a short conversation with a commit hash is fine. A 2-message conversation
where the user just asked a question and got an answer is not.

## Output Structure

Use exactly this structure. No preamble, no closing remarks.

### Work Characteristics

Identify 3-5 observable habits or patterns from this session. Include both productive patterns
and counterproductive ones. Each should cite a specific moment: what the user did, said, or
chose. Focus on patterns that repeat or that reveal an underlying tendency.

### Blind Spots

At least 3. These are things the user likely didn't notice about their own process.
Each blind spot must include:
- What the blind spot is
- A concrete example from the session (quote the exchange, name the step, cite the commit)
- Why it matters (the cost of not noticing)

### The One Thing to Change

If only one habit could change, which yields the largest improvement? Be specific about
the mechanism: what does the user do now, what should they do instead, and why the delta
is large.

### Next Time

One concrete, actionable adjustment. Not a principle, not a mindset shift. A specific
behavior change that can be executed immediately next session. Frame it as an instruction:
"Before X, do Y" or "When you notice X, stop and do Y instead."

### Evidence Transparency

Throughout the entire output, distinguish clearly between:
- **Observed fact**: something you can point to in the conversation or git history
- **Inference**: a conclusion you're drawing from the evidence

Mark inferences explicitly. Use language like "This suggests..." or "[Inference]".
When uncertain, say so. Never present a guess as an observation.

## Tone Calibration

- Direct. No hedging, no "you might consider", no "it could be helpful to".
- Specific. Every claim backed by a concrete moment.
- Respectful but not gentle. The user explicitly asked for no face-saving.
- Actionable. Every observation connects to something the user can actually change.
- Dense. Say more in fewer words. No filler paragraphs.

## What Makes a Good Retro

A good retro surprises the user. If every point is something they already know, the retro
failed. Look for:
- Contradictions between what the user says and what they do
- Time sinks that went unnoticed
- Assumptions that were never validated
- Patterns across multiple decisions that reveal an underlying bias
- Moments where the user's process served them well (these are worth naming too,
  so the user knows to keep doing them deliberately rather than by accident)

## What to Avoid

- Generic advice that could apply to anyone ("plan before you code")
- Complimenting the user to soften criticism
- Restating what the user already explicitly said about themselves
- Armchair psychology about motivation or personality
- Recommendations that require large lifestyle changes
