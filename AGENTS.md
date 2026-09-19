# Hackathon Development Instructions

This repository is developed using the Hackathon Playbook.

Before starting substantial work, read:

docs/HACKATHON_PLAYBOOK.txt

## Required workflow

For every new hackathon case, follow this sequence:

CASE → VALUE → WOW → MVP → ARCH → SCORE → BUILD → DEMO

Do not jump directly from the case description to implementation.

## Before writing application code

First:

1. Analyze the original task.
2. Identify the concrete problem and target user.
3. Define the value proposition.
4. Define one strong 30–60 second demo scenario.
5. Split scope into MUST / SHOULD / WOW / LATER.
6. Define the architecture and data flow.
7. Explicitly separate:
   - AI responsibilities;
   - deterministic application logic.
8. Check the proposed solution against the hackathon evaluation criteria.
9. Create or update CASE.md.
10. Create or update PLAN.md.
11. Create the README skeleton.

Only after this analysis is reviewed may implementation begin.

## Implementation strategy

Build vertically.

Prefer:

Input
→ AI
→ Structured Data
→ Business Logic
→ Result
→ UI

Get one complete end-to-end scenario working before adding secondary features.

Do not over-engineer infrastructure that is not required for the demo.

## AI

AI should be used for tasks where it provides real value, such as:

- understanding unstructured content;
- extraction;
- classification;
- semantic similarity;
- generation;
- reasoning over natural language.

Use deterministic code for:

- formulas;
- validation;
- business rules;
- thresholds;
- counting;
- comparisons;
- reproducible decisions.

Always be able to answer:

"Why is AI necessary here?"

Avoid building a simple ChatGPT wrapper.

## Git

Do not commit or push unless explicitly requested.

Prefer small, meaningful milestones.

Each development phase should produce a verifiable result.

## Documentation

Never claim functionality in README that has not actually been implemented.

Track external materials honestly:
- AI models;
- libraries;
- datasets;
- templates;
- pre-existing code.

## Priority

A working, demonstrable end-to-end prototype is more important than
production-grade infrastructure or a large number of incomplete features.
