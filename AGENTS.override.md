# Aaron — Codex Desktop Operator Mode (Aggressive AF) — AGENTS.override.md v1.0

You are operating inside Codex Desktop for Aaron.
This repo (and all repos) must stay low-entropy: deterministic, minimal, runnable, and measurable.
If you can execute, execute. Ask one question only if truly blocked.

────────────────────────────────────────────────────────
0) PRIME DIRECTIVE
────────────────────────────────────────────────────────
Ship working outcomes fast with:
- minimal moving parts
- one-command run
- local-first state
- clear boundaries
- tests + logs + contracts
No fluff. No speculative scaffolding. No “nice-to-haves” unless asked.

────────────────────────────────────────────────────────
1) STRICT OUTPUT CONTRACT (NON-NEGOTIABLE)
────────────────────────────────────────────────────────
When delivering a build or change, output in this exact order:

1) Full runnable code / full file tree (complete files, not fragments)
2) Explanation (≤ 1 paragraph)
3) Install + run (exact commands)
4) Why it works (1 line)
5) Quick fix if broken (most likely issue + fix)

If you can’t deliver runnable output, you MUST say what’s missing and provide the smallest runnable baseline anyway.

────────────────────────────────────────────────────────
2) DEFAULTS (CHOSEN FOR ONE-SHOT SUCCESS)
────────────────────────────────────────────────────────
Language:
- Default Python 3.11+ unless UI forces JS.
Stacks:
- UI: Streamlit (default) or minimal React only if required
- API: Flask (small) / FastAPI only if asked
Persistence:
- JSONL + JSON snapshots default; SQLite ok for relational needs
Config:
- .env.example always; config-first behavior; no hidden state
Repo layout (required):
- /core  (logic)
- /data  (local state)
- /tests (lightweight tests)
- README.md (fresh-clone run steps)
- AGENTS.md / AGENTS.override.md (instructions)
- .env.example (documented keys)

Anti-patterns (do not do unless asked):
- microservices, k8s, terraform, docker (unless explicitly requested)
- heavy frameworks, unused abstractions, placeholders
- “TODO: implement later” for core paths

────────────────────────────────────────────────────────
... (same content as the original aggressive template up to the end) ...
────────────────────────────────────────────────────────
11) ALWAYS END WITH NEXT MOVES
────────────────────────────────────────────────────────
End every build with:
- “Next upgrades (3 max)”
- mark the single highest-leverage upgrade

That’s it. Ship.
