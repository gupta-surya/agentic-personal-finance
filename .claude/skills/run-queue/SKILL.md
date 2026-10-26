---
name: run-queue
description: Work through approved task specs for one stream on your own — implement each, open a PR, continue to the next — until a stop condition.
disable-model-invocation: true
---
Work through the build queue for the stream named in $ARGUMENTS (for example
`backend` or `frontend`). Surya steers by approving specs and brakes by merging,
or not merging, PRs.

**Where the docs live.** CLAUDE.md, DESIGN.md, ROADMAP.md, the generative-UI doc
and every spec are private and live outside this repo. `CLAUDE.md` in the repo
root is a symlink into that folder, so the folder is
`dirname "$(readlink -f CLAUDE.md)"`; call it `$DOCS`. Specs are
`$DOCS/specs/*.md`. Read them there; never copy them into the repo or commit
them.

**Approved means the spec says so.** A spec counts as approved only if its header
contains the line `Status: approved` and a `Stream:` line naming your stream.
Only Surya changes the Status line; never edit it yourself. Never implement a
spec in any other state.

Loop:
1. Pick the next approved spec for your stream, in `$DOCS/ROADMAP.md` order, that
   has no open or merged PR.
2. Branch from `main`. If the spec depends on work that isn't merged yet,
   branch from that work's branch instead and open your PR against it.
3. Follow `.claude/skills/ship-task/SKILL.md`, with one change: don't wait for
   plan approval. Put the plan at the top of the PR description and proceed.
4. Update "Where we are" in `$DOCS/ROADMAP.md` directly. It is not in the repo, so
   there is no branch or commit for it. It's how the next task, and Surya, know
   what happened.
5. Before starting the next task, check your open PRs. If a branch you built
   on was squash-merged, move your work onto main with
   `git rebase --onto main <last commit of the merged branch> <your branch>`,
   then push with `--force-with-lease`.

Stop and summarize where things stand when any of these is true:
- You have 2 open, unmerged PRs in this stream.
- No approved spec is left. Draft the next one from `$DOCS/ROADMAP.md` as a file
  in `$DOCS/specs/` with `Status: draft`, then stop.
- You need a decision outside your autonomy (see "How we work" in CLAUDE.md).
- CI fails twice on the same problem.
