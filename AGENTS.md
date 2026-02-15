# Aaron - Codex Desktop Operator Mode (Aggressive AF) - AGENTS.md v1.0

You are operating inside Codex Desktop for Aaron.
This repo must stay low-entropy: deterministic, minimal, runnable, and measurable.
If you can execute, execute. Ask one question only if truly blocked.

## 0) Prime Directive

Ship working outcomes fast with:
- minimal moving parts
- one-command run
- local-first state
- clear boundaries
- tests + logs + contracts

No fluff. No speculative scaffolding. No nice-to-haves unless asked.

## 1) Strict Output Contract (Non-Negotiable)

When delivering a build or change, output in this exact order:
1. Full runnable code / full file tree (complete files, not fragments)
2. Explanation (<= 1 paragraph)
3. Install + run (exact commands)
4. Why it works (1 line)
5. Quick fix if broken (most likely issue + fix)

If runnable output is blocked, state what is missing and still provide the smallest runnable baseline.

## 2) Defaults (One-Shot Success)

Language:
- Python 3.11+ by default

Stacks:
- UI: Streamlit default (if UI needed)
- API: Flask default, FastAPI only if asked

Persistence:
- JSONL + JSON snapshots default
- SQLite only if relational needs justify it

Config:
- `.env.example` always
- config-first behavior
- no hidden state

Required repo layout:
- `/core` logic
- `/data` local state
- `/tests` lightweight tests
- `README.md` fresh-clone run steps
- `AGENTS.md` / `AGENTS.override.md` instructions
- `.env.example` documented keys

Anti-patterns (unless explicitly requested):
- microservices, kubernetes, terraform, docker
- heavy frameworks and unused abstractions
- core-path TODO placeholders

## 11) Always End With Next Moves

End every build with:
- Next upgrades (3 max)
- mark the single highest-leverage upgrade
