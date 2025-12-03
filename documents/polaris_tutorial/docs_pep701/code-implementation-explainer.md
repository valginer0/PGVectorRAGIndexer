---
name: code-implementation-explainer
description: Explain code implementations, PRs, and technical changes at a high conceptual level without line-by-line diffs. Use when users ask to understand how a PR/implementation works, what changes were made to a codebase, how components work together, or want architectural explanations of code changes (e.g., "explain the PEP 701 implementation", "how does PR #1234 work", "what does this commit do architecturally").
---

# Code Implementation Explainer

Explain code implementations at a high conceptual level, focusing on architecture, problem-solving approach, and how components work together—without getting lost in line-by-line diffs.

## Research Process

Follow this systematic approach to understand and explain implementations:

### 1. Gather Context

**Search for the implementation:**
- Search for the PR/issue/commit using specific identifiers (PR numbers, issue numbers, PEP numbers, commit hashes)
- Include project name, repository, and relevant keywords
- Example queries: "Black PR 3822", "CPython issue 12345", "PEP 701 implementation"

**Fetch primary sources:**
- Use `web_fetch` to retrieve the full PR/issue page for detailed information
- Look for linked discussions, design documents, or specifications
- Find the original problem statement or feature request

**Understand the broader context:**
- Search for related specifications (PEPs, RFCs, design docs)
- Find explanatory articles or blog posts about the feature
- Look for related issues or discussions that provide background

### 2. Identify Key Information

Extract these essential elements from your research:

**The Problem:**
- What limitation, bug, or missing feature prompted the change?
- What were users unable to do before?
- What pain points existed in the old implementation?

**The Solution Approach:**
- What is the high-level strategy for solving the problem?
- What architectural decisions were made?
- What tradeoffs were considered?

**The Implementation:**
- What are the major components or modules involved?
- How do these components interact?
- What new abstractions or patterns were introduced?
- What existing code was modified or replaced?

**Technical Details:**
- What algorithms or data structures are central to the solution?
- Are there performance considerations?
- What edge cases are handled?

## Explanation Structure

Organize explanations using this clear structure:

### Opening Context (1-2 paragraphs)
- Briefly describe what changed and why it matters
- Reference the specification/feature being implemented (with citation)
- Set the stage for the technical explanation

### The Core Problem (1 paragraph)
- Explain what wasn't working or what limitation existed
- Use specific examples if helpful (with citation)
- Avoid excessive background—focus on the immediate problem

### The Solution Approach (2-3 paragraphs)
- Describe the architectural strategy at a high level
- Explain the key insight or pattern that makes the solution work
- Mention major design decisions and why they matter

### Implementation Details (3-5 paragraphs)
Break down the implementation into digestible components:

**Component 1: [Name]**
- What it does and why it's needed
- How it works conceptually
- What it interacts with

**Component 2: [Name]**
- What it does and why it's needed
- How it works conceptually
- What it interacts with

**Integration:**
- How the components work together
- What the data flow looks like
- How the pieces fit into the larger system

### Benefits/Impact (1 paragraph)
- What this implementation enables
- Why the approach is effective
- What improvements users will see

## Writing Guidelines

**Focus on conceptual understanding:**
- Explain the "what" and "why" before the "how"
- Use architecture-level descriptions, not implementation minutiae
- Describe patterns and strategies, not specific variable names

**Avoid line-by-line details:**
- Don't enumerate individual code changes
- Don't quote code snippets unless they're exceptionally illustrative
- Don't describe specific line numbers or file paths unless crucial for understanding

**Use clear, technical language:**
- Be precise but accessible
- Define technical terms when first used
- Use analogies sparingly and only when they genuinely clarify

**Structure for scannability:**
- Use descriptive headers for each component
- Keep paragraphs focused on one concept
- Bold key terms when introducing them

**Cite appropriately:**
- Always cite specific claims from search results
- Use citations to support technical assertions
- Follow the citation format: `paraphrased claim`

## Example Explanation Patterns

**Pattern 1: New feature implementation**
```
Context: [Feature name] was added in [version] to address [problem]

Problem: Before this, users couldn't [limitation], which meant [consequence]

Approach: The implementation uses [strategy] by [high-level method]

Key Components:
- [Component A]: Handles [responsibility] by [mechanism]
- [Component B]: Manages [responsibility] through [mechanism]
- Integration: [How A and B work together]

Result: This enables [benefit] while maintaining [constraint]
```

**Pattern 2: Architecture refactor**
```
Context: The [system] was refactored to [goal]

Problem: The old architecture had [limitation] because [reason]

New Architecture: The solution introduces [new pattern] with [key insight]

Major Changes:
- [Change 1]: Replaces [old approach] with [new approach] to [benefit]
- [Change 2]: Extracts [abstraction] to [benefit]
- [Change 3]: Reorganizes [component] for [benefit]

How It Works: [Flow description showing component interaction]

Benefits: [Performance/maintainability/capability improvements]
```

**Pattern 3: Bug fix implementation**
```
Context: [Bug description] was fixed in [PR/commit]

Root Cause: The issue occurred because [underlying problem]

Solution: The fix [approach] by [mechanism]

Implementation:
- [Detection]: How the problem condition is identified
- [Correction]: What change is applied to fix it
- [Prevention]: What ensures it doesn't happen again

Result: [What now works correctly]
```

## Common Pitfalls to Avoid

**Don't:**
- Get lost in code syntax or specific variable names
- List every file that changed
- Describe every function call in sequence
- Focus on test changes unless they reveal important behavior
- Include code snippets that just show syntax

**Do:**
- Explain the architectural pattern or strategy
- Describe how major components collaborate
- Identify the key insight that makes the solution work
- Show how the implementation solves the original problem
- Mention clever techniques or notable design decisions

## Research Quality Guidelines

**Aim for multiple sources:**
- Use 2-5 searches depending on complexity
- Prioritize: (1) Official PR/issue, (2) Specification docs, (3) Explanatory articles
- Fetch full pages for detailed context, not just search snippets

**Verify technical claims:**
- Don't invent architectural details—cite or acknowledge uncertainty
- If the implementation approach isn't clear from available sources, say so
- Distinguish between what the sources say and what you infer

**Balance depth and clarity:**
- Provide enough detail to understand the approach
- Don't overwhelm with implementation minutiae
- Adjust depth based on the change's complexity
