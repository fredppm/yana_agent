---
name: capability-authoring
description: Guide for creating and evolving learned capabilities
---

# Capability Authoring

When your owner wants you to learn a new ability, you create a capability together. This guide tells you how to write, format, and register it.

## Capability Types

A capability can take several forms:

### Prompt (default)
A markdown file with guidance on what to achieve. Best for judgment-based tasks — analysis, coaching, research, review.

### Script
A Python script for deterministic tasks — calculations, file processing, API calls. Create the script alongside a short markdown file that describes when and how to use it.

### Multi-file
A folder with multiple files for complex capabilities — workflows with multiple steps, reference materials, templates.

## Prompt File Format

Every capability prompt file should have this frontmatter:

```markdown
---
name: {kebab-case-name}
description: {one line — what this does}
code: {2-letter menu code, unique across all capabilities}
added: {YYYY-MM-DD}
type: prompt | script | multi-file
---
```

The body should be **outcome-focused** — describe what success looks like. Include:

- **What Success Looks Like** — the outcome, not the process
- **Your Approach** — principles and constraints, not step-by-step
- **Memory Integration** — how to use MEMORY.md and BOND.md to personalize
- **After Use** — what to capture in the session log

## Creating a Capability (The Flow)

1. Owner says they want you to learn something new
2. Explore what they need through conversation — don't rush to write
3. Draft the capability prompt and show it to them
4. Refine based on feedback
5. Save to `capabilities/`
6. Update CAPABILITIES.md — add a row to the Learned table
7. Update INDEX.md — note the new file under "My Files"
8. Confirm: "I'll remember how to do this next session. You can trigger it with [{code}]."

## Good Candidates for New YANA Capabilities

- **Garmin Daily Summary** — pull and interpret HRV, sleep, and stress data from Garmin Connect
- **Home Assistant Command** — translate a plain-language home request into an HA action
- **Bureaucracy Tracker** — track multi-step document processes (like the Portugal docs)
- **Weekly Review** — synthesize the week across all facets and surface patterns
- **Communication Draft** — write messages for specific relationships (wife, boss, team)

## Refining Capabilities

After use, if feedback suggests improvement:
- Update the capability prompt with refined context
- Log the refinement in the session log

A capability refined 3-4 times is usually excellent. The first draft rarely is.
