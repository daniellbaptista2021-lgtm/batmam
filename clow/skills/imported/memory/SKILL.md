---
name: "memory"
description: "Manage persistent memory files for cross-session context"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /memory — Persistent Memory Management

When the user invokes /memory, manage persistent memory stored in CLAUDE.md files.

## Commands

### /memory list
Show all memory files and their contents:
- Project-level: `./CLAUDE.md`
- User-level: `~/.claude/CLAUDE.md`
- Parent directories: `../CLAUDE.md`, etc.

### /memory add <text>
Add a new memory entry to the project CLAUDE.md:
- Append to the appropriate section
- If CLAUDE.md does not exist, create it with /init first
- Format as a bullet point under the right heading

### /memory remove <text>
Remove a memory entry:
- Search for matching text in CLAUDE.md
- Confirm with the user before removing
- Remove the matching line

### /memory search <query>
Search across all memory files for matching content.

## Memory File Hierarchy (highest priority first)
1. `./CLAUDE.md` — project-specific rules and context
2. `~/.claude/CLAUDE.md` — user-level global preferences
3. Parent directory CLAUDE.md files — workspace/org level

## What to Store in Memory
- Project conventions and code style rules
- Common commands (build, test, deploy)
- Architecture decisions
- Known gotchas and workarounds
- User preferences for this project

## Rules
- Always show the user what changed
- Never delete memory without confirmation
- Keep entries concise and actionable
- Avoid duplicates — check before adding
