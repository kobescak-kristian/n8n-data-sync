# n8n Data Sync

@AGENTS.md

## Session mechanics (Claude-specific)
- Boot: read STATE.md before writing to this tree.
- Environment fingerprint before any write (pwd + git config user.email).
- Close: commit -> push origin main -> verify origin/main..HEAD empty.
