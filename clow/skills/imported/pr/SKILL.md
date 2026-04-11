---
name: "pr"
description: "Create pull requests with summary, test plan, and proper gh commands"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /pr — Create Pull Request

When the user invokes /pr, follow this exact procedure:

## Step 1: Understand Branch State (run in parallel)
- `git status` — check for uncommitted changes
- `git branch --show-current` — get current branch name
- `git log --oneline main..HEAD` or `git log --oneline master..HEAD` — commits to include
- `git diff main...HEAD` or `git diff master...HEAD` — full diff from base
- Check if remote tracking branch exists: `git rev-parse --abbrev-ref @{upstream} 2>/dev/null`

## Step 2: Handle Uncommitted Changes
- If there are uncommitted changes, ask the user if they want to commit first
- If yes, follow the /commit procedure first

## Step 3: Draft PR
- **Title**: Under 70 characters, concise summary of the change
- **Body**: Use this exact format:

```markdown
## Summary
- <1-3 bullet points explaining what and why>

## Test plan
- [ ] <specific testing steps>

Generated with [Clow](https://clow.com)
```

## Step 4: Push and Create
```bash
# Push with upstream tracking
git push -u origin <branch-name>

# Create PR using gh
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
- <bullets>

## Test plan
- [ ] <steps>

Generated with [Clow](https://clow.com)
EOF
)"
```

## Rules
- NEVER force push
- Title must be under 70 chars
- Always include ## Summary and ## Test plan sections
- Return the PR URL when done
