# Multi-Agent Coordination Protocol (AGENTS.md)

This document establishes the asynchronous multi-agent coordination protocol for the **Agent Reach** repository. It defines team roles, task claiming, conflict prevention, communication standards, and safety boundaries for autonomous and semi-autonomous AI agents collaborating on this codebase.

> **Applicability**: This protocol applies to all AI agents operating in this repository. Practical compliance depends on each agent's configured tools, runtime permissions, and operational capabilities.

---

## 1. Team Roles and Specializations

Roles represent primary domains of expertise rather than rigid exclusivity. Always verify current GitHub activity before claiming work.

- **Google Antigravity / Gemini** — *Implementation Engineer*: General engineering, feature delivery, frontend/backend integration, debugging and regression fixes, focused implementation PRs.
- **Claude Sonnet 5.5 Medium** — *Editorial Intelligence Engineer*: Summary and news quality, editorial evaluation benchmarks, evidence and source analysis, ranking quality and continuity evaluation, read-only quality assessments, focused benchmark PRs.
- **Claude Backend** — *Architecture Engineer*: Ingestion pipelines, clustering and event intelligence, publisher and registry architecture, foundational backend systems.
- **Meta Muse** — *Autonomous Operations & QA*: Scheduled 30-minute heartbeats, CI and GitHub monitoring, production reliability checks, regression detection, small isolated fixes, PR reconciliation and task coordination.
- **ChatGPT** — *Independent Reviewer & Coordinator*: Cross-agent architecture and PR review, risk assessment, priority recommendations, assisting the human owner with coordination.
- **Human Owner** — *Final Authority*: Sole approver for PR merges into `main`, production deployments, ownership conflict arbitration, and major roadmap decisions.

---

## 2. GitHub as the Communication Hub

All agent-to-agent and agent-to-human coordination occurs asynchronously through GitHub. Do not establish external chat platforms, proprietary communication channels, or paid messaging APIs.

- **GitHub Issues**: Primary tracking for tasks, bug reports, and claimed assignments.
- **Pull Requests**: Focused units of code change, reviews, and technical discussions.
- **Comments**: Structured handoffs and coordination notes attached to existing Issues/PRs.
- **GitHub Actions**: Deterministic source of truth for CI build, test, and lint status.
- **AGENTS.md**: Durable protocol rules (this file).

---

## 3. Event-Driven Handoff Protocol

Agents communicate only on actionable events. Routine successful heartbeats or clean automated runs must never trigger broadcast messages to other agents.

### When to Post a Coordination Comment
Post only when:
1. A confirmed P0 or P1 defect is discovered.
2. An actionable task requires another agent's designated domain expertise.
3. A pull request is validated and ready for review.
4. A blocking merge or branch conflict is detected.
5. An important regression is confirmed with reproducible evidence.
6. A decision requires explicit human owner authorization.

### Standard Handoff Format
When handing off or requesting action, use this compact format:

```text
AGENT HANDOFF
- Task: <concise task summary>
- Priority: <P0 | P1 | P2>
- From: <Agent Name>
- To: <Agent Name | All | Human Owner>
- GitHub issue/PR: <#number or URL>
- Evidence: <commit SHA, log snippet, reproduction path>
- Requested action: <specific required action>
- Current owner: <Agent Name>
- Status: <Proposed | Blocked | In Progress | Ready for Review>
```

### Communication Rules
- **No conversational loops**: Never reply with mere acknowledgments (e.g., "Understood", "Working on it").
- **Single accountability**: Every active handoff must have exactly one accountable owner.
- **Thread continuity**: Reuse existing issues and PRs instead of creating duplicate threads.
- **No activation assumption**: Posting a GitHub message does not immediately invoke another agent; handoffs are picked up via each agent's configured schedule, triggers, or human prompts. Never claim live webhooks or real-time connectivity exist unless explicitly configured and verified.

---

## 4. Task Lifecycle and Ownership

Before starting implementation, every agent must follow this 9-step workflow:

1. **Refresh `main`**: Ensure the local environment is current (`git fetch origin main`).
2. **Inspect GitHub**: Review open PRs and issues for related ongoing work.
3. **Verify ownership**: Confirm no other agent is actively working on the target problem.
4. **Identify file overlap**: Determine if planned changes intersect with open branches.
5. **Claim the task**:
   - Use labels where available: `agent:gemini`, `agent:sonnet`, `agent:claude`, `agent:muse`, with `priority:p0|p1|p2`.
   - **Fallback**: If labels are unavailable or cannot be applied, post a clear claim comment on the issue/PR before making edits.
   - Do not automatically reassign an existing claim simply because an agent has not replied immediately.
6. **Isolate implementation**: Work strictly in a dedicated branch (e.g., `feature/...`, `fix/...`, `docs/...`) or isolated git worktree.
7. **Validate thoroughly**: Run local test suites and linters (`pytest`, `pyflakes`) per [`CLAUDE.md`](CLAUDE.md#commands).
8. **Open a focused PR**: Keep diffs minimal and scoped to the claimed task.
9. **Record results**: Update tracking issues or handoff notes with final commit SHAs and validation status.

---

## 5. Conflict Prevention and Prohibitions

To prevent duplicate work and repository corruption, agents must strictly follow these rules:

### Prohibited Actions
- **No competing PRs**: Do not open an uncoordinated PR for an already claimed defect.
- **No force-pushing shared branches**: Never `git push --force` to another agent's branch.
- **No rebasing active branches**: Never rebase or alter history on branches under active use.
- **No relying on stale state**: Never treat outdated local repository state as authoritative.
- **No suppressing tests for CI**: Never delete, disable, or weaken tests solely to make CI green.
- **No blind reverts**: Never revert code without understanding and documenting its original purpose.
- **No autonomous merging**: Never auto-merge PRs into `main`.
- **No autonomous deployment**: Never trigger or push production deployments independently.

### Reconciliation Rule
If overlapping work or a branch collision is discovered: **halt overlapping edits immediately**, compare actual diffs against the existing branch/PR, and coordinate resolution via the active PR thread.

---

## 6. Token, Compute, and Context Efficiency

Conserve model and computation budgets by avoiding redundant chatter and heavy context dumps:

- **No idle conversation**: Do not post greetings, status polls, or pleasantries.
- **No whole-file pasting**: Reference short links, commit SHAs, line numbers, or minimal diff snippets (<20 lines).
- **Deterministic checks first**: Run static analyzers (`pyflakes`), unit tests (`pytest`), and diff inspections before launching multi-agent or model-intensive diagnostic passes.
- **No redundant full scans**: Check specific files and targeted test cases instead of scanning the full repository repeatedly.
- **Avoid repeated handoffs**: If an issue cannot be resolved after two agent handoffs, escalate directly to the Human Owner with concise evidence.

---

## 7. Safety, Governance, and Authority Boundaries

Agents may independently inspect code, run offline benchmarks/tests, create scoped branches, commit changes, and open PRs within their tool permissions.

### Actions Requiring Explicit Human Authorization
Agents must **never** execute the following without direct human approval:
1. Merging pull requests into `main` or moving the `stable` production release pointer.
2. Pushing production deployments or triggering release workflows.
3. Modifying credentials, tokens, DPAPI access keys, or secrets.
4. Spending financial resources or modifying paid account configurations.
5. Disabling or altering security controls, guardrails, or safety gates.
6. Deleting datasets, user local data, or shared repository history.

---

## 8. Related Project Documentation

This protocol complements existing repository documentation:
- [`CLAUDE.md`](CLAUDE.md): Permanent development conventions, local Windows environment specs, test commands, and file maps.
- [`HANDOFF.md`](HANDOFF.md): Current operational sprint state, active branches, and resume pointers.
- [`BUILD.md`](BUILD.md): Project roadmap, phase definitions, and acceptance criteria.
- [`README.md`](README.md): Product architecture, reader features, and user setup.
- [`docs/`](docs/): Deep technical specifications (e.g., [`EVENT-IDENTITY.md`](docs/EVENT-IDENTITY.md), [`PUBLISHING.md`](docs/PUBLISHING.md), [`architecture.md`](docs/architecture.md)).
