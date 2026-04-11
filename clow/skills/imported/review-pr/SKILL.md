---
name: "review-pr"
description: "Review pull requests thoroughly for bugs, security, and code quality"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /review-pr — Code Review

When the user invokes /review-pr [number|url], follow this procedure:

## Step 1: Get PR Information
```bash
# If PR number provided
gh pr view <number> --json title,body,files,additions,deletions
gh pr diff <number>

# If no number, review current changes
git diff main...HEAD
```

## Step 2: Review Checklist
Analyze the diff for each of these categories:

### Bugs & Logic Errors
- Off-by-one errors, null/undefined access, race conditions
- Missing error handling, unchecked return values
- Incorrect boolean logic, wrong comparisons

### Security (OWASP Top 10)
- SQL injection, XSS, CSRF vulnerabilities
- Hardcoded secrets, exposed credentials
- Missing input validation, improper auth checks

### Performance
- N+1 queries, unnecessary loops, missing indexes
- Large memory allocations, blocking operations
- Missing pagination, unbounded queries

### Code Quality
- Dead code, duplicated logic, unclear naming
- Missing types/documentation on public APIs
- Overly complex functions (break them down)

### Tests
- Are new features covered by tests?
- Are edge cases tested?
- Do tests actually assert meaningful behavior?

## Step 3: Output Format
```
## PR Review: <title>

### Summary
<1-2 sentence overview of what the PR does>

### Issues Found
**Critical** (must fix):
- <issue with file:line reference>

**Suggestions** (should consider):
- <improvement with code example>

**Nits** (optional):
- <minor style/naming suggestions>

### Verdict
APPROVE / REQUEST_CHANGES / COMMENT
```

## Rules
- Always reference specific file:line for issues
- Provide fix suggestions with code examples
- Be constructive, not just critical
- Focus on real issues, not style preferences
