---
name: Feature Request
about: Suggest a new feature or enhancement for agent-browser
title: "[Feature] "
labels: enhancement
assignees: ''
---

## Feature Description

A clear and concise description of the feature you would like to see.

## Use Case / Motivation

Why is this feature needed? Describe the problem it solves or the workflow it enables.

## Proposed API or Behavior Change

Describe how you envision this feature working. Include:

- **API changes** (if any): new functions, parameters, config options, etc.
- **Configuration changes** (if any): new environment variables, YAML keys, etc.
- **Behavior changes** (if any): how existing behavior should differ

Example:

```python
# Proposed API usage
async with create_session(mode="local") as session:
    await session.new_feature(arg="value")
```

## Alternatives Considered

Have you explored other ways to achieve the same goal? Describe any workarounds or alternative approaches you have tried.

## Additional Context

- Links to related issues or discussions
- References to similar features in other projects (e.g., browser-use, Playwright)
- Mockups, diagrams, or other supporting materials
- Any implementation ideas or willingness to contribute a PR
