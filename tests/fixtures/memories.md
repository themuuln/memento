# Test Memories

> Auto-captured learnings and preferences across all sessions.

---

## Hard Rules

- Never commit secrets to version control
- Always verify destructive operations before executing
- Run lsp_diagnostics on changed files before builds

---

## User Preferences

- Use conventional commits (feat:, fix:, chore:)
- Prefer pnpm over npm
- Prefer agent-browser CLI over Playwright MCP

---

## Project Conventions

### test-project
- **Stack**: Next.js 15 + Supabase
- **Testing**: Playwright

### another-project
- **Stack**: Flutter + BLoC
- **Patterns**: Feature-first architecture

---

## Tool Quirks

- `ln -sf` doesn't work reliably on macOS — use `rm -f` then `ln -s`
- Base UI Combobox inside Base UI Drawer causes Drawer to close

---

## Validated Approaches
  - [2026-07-01] we decided to use SQLite for local caching
  - [2026-07-02] we migrated from GetX to Riverpod

- Always unalias before defining a function with same name in zsh
- Don't test internal zsh completion helpers directly

---

## Key Learnings
- [2026-07-01] TDD reduces debugging time
- [2026-07-02] WAL mode is essential for read concurrency in SQLite

---

## Model Configuration

| Task | Model |
|------|-------|
| Default | MiMo V2.5 |
| Compaction | DeepSeek V4 Flash |

## Code Block Example

```python
def example():
    return "hello"
```

<!-- This is a comment that should be ignored -->
