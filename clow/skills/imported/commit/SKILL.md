---
name: "commit"
description: "Create structured git commits with proper message format and staged analysis"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /commit — Structured Git Commit

When the user invokes /commit, follow this exact procedure:

## Step 1: Gather Information (run in parallel)
- `git status` — see all untracked and modified files
- `git diff --cached` and `git diff` — see staged and unstaged changes
- `git log --oneline -5` — see recent commit style

## Step 2: Analyze Changes
- Classify the change: feat, fix, refactor, docs, style, test, chore
- Identify which files changed and why
- Note any files that should NOT be committed (.env, credentials, secrets)

## Step 3: Stage Files
- Stage relevant files by name: `git add <file1> <file2> ...`
- NEVER use `git add -A` or `git add .` — too risky
- Warn if any sensitive files are detected

## Step 4: Draft Commit Message
- Focus on WHY, not WHAT
- Keep it concise: 1-2 sentences
- Use imperative mood ("Add feature" not "Added feature")
- Match the project existing commit style if visible

## Step 5: Commit
Use HEREDOC format to ensure proper formatting:

```bash
git commit -m "$(cat <<'EOF'
<type>: <concise description of why>

Co-Authored-By: Clow <noreply@clow.com>
EOF
)"
```

## Rules
- NEVER amend existing commits unless the user explicitly asks
- NEVER use --no-verify or skip hooks
- If a pre-commit hook fails, fix the issue and create a NEW commit
- If there are no changes, say so — do not create empty commits
- After committing, run `git status` to confirm success
