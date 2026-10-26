---
name: ship-task
description: Implement one task spec end to end, verify, review, and open a PR for Surya to merge.
disable-model-invocation: true
---
Implement the task spec at $ARGUMENTS.
1. Read the spec, DESIGN.md and CLAUDE.md. Present a plan; wait for
   approval unless run-queue invoked you.
2. Branch task/<spec-name> from an up-to-date main.
3. Build in the spec's order, one commit per layer. After each layer,
   run ruff, mypy and pytest on the files you touched only.
4. When every acceptance criterion has a passing test, use a subagent
   to review the diff against the spec. Fix correctness gaps only.
5. Run the invariant-auditor subagent on the diff; fix every finding.
6. Push and open a PR listing each acceptance criterion with its
   proving test, the decisions you made, and the review findings.
7. Stop. Never merge.
