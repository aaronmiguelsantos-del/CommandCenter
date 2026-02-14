# Aaron Command Center — Agent Rules

## Operating Philosophy
- Ship the smallest working version first.
- Prefer clarity over cleverness.
- No overengineering.
- Every feature must be runnable locally.

## Execution Loop
1. Read relevant files.
2. Propose a short plan (3–5 bullets).
3. Execute in small diffs.
4. Run a basic validation.
5. Output:
   - Summary
   - Files changed
   - How to run
   - Known limitations

## Guardrails
- No destructive actions unless explicitly requested.
- Never commit secrets.
- Keep dependencies minimal.
- Avoid spawning unnecessary files.
