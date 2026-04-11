---
name: "compact"
description: "Force context compaction to free up token space"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: core
---

# /compact — Context Compaction

When the user invokes /compact, perform context compaction:

## What It Does
Summarize the current conversation into a compact form to free token space.

## Procedure
1. Review the entire conversation history
2. Identify:
   - What task is being worked on
   - What files have been modified and why
   - What decisions were made
   - What is the current state (what works, what is pending)
   - Any errors or blockers encountered
3. Produce a compact summary in this format:

```
## Context Summary

**Task**: <what we are working on>

**Completed**:
- <action>: <result>

**Current State**:
- <file>: <status>

**Pending**:
- <next steps>

**Key Decisions**:
- <decision and reasoning>
```

4. This summary replaces the full conversation context going forward

## Rules
- Never lose critical information (file paths, error messages, decisions)
- Keep it factual and actionable
- Prioritize: current task > recent actions > older context
- If the user provides a custom prompt with /compact, focus the summary on that topic
