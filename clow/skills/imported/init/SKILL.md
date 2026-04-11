---
name: "init"
description: "Initialize CLAUDE.md project configuration by scanning project structure"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /init — Initialize Project Configuration

When the user invokes /init, create a CLAUDE.md (or CLOW.md) at the project root.

## Step 1: Scan Project Structure
Gather information about the project:
- `ls -la` — top-level files and directories
- Check for package.json, requirements.txt, Cargo.toml, go.mod, etc.
- Check for .git, existing .claude/, existing CLAUDE.md
- Identify the tech stack (language, framework, package manager)
- Check for existing linting/formatting config (.eslintrc, .prettierrc, pyproject.toml)

## Step 2: Detect Key Patterns
- Build system (npm, yarn, pnpm, pip, cargo, go)
- Test framework (jest, pytest, go test, cargo test)
- Linting/formatting tools
- CI/CD configuration (.github/workflows, .gitlab-ci.yml)
- Monorepo structure (workspaces, packages/)

## Step 3: Generate CLAUDE.md
Create the file with this structure:

```markdown
# CLAUDE.md

## Project Overview
<1-2 sentences about what this project is>

## Tech Stack
- Language: <detected>
- Framework: <detected>
- Package Manager: <detected>

## Commands
- Build: `<command>`
- Test: `<command>`
- Lint: `<command>`
- Format: `<command>`

## Project Structure
<brief description of key directories>

## Code Style
- <detected conventions>

## Important Notes
- <any special patterns or gotchas detected>
```

## Rules
- If CLAUDE.md already exists, ask before overwriting
- Keep it concise — this is a reference, not documentation
- Only include information you can actually detect
- Use the project existing conventions, do not impose new ones
