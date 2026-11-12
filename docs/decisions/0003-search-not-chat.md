# 0003. Search, not chat
Date: 2026-11-11 · Status: accepted

## Context
The goal is to stop digging for papers. A chat window would answer in paragraphs I would have to check against the source, and it invites follow-ups the app would have to remember. What I want is a short prompt that lands on the exact file, page and lines.

## Decision
Finding a document works like search. A search box is the home screen; results update as I type; every prompt stands alone, with no thread and no chat window. A local model turns the prompt into a structured query under a fixed JSON schema, and retrieval combines filters on extracted fields, keyword search and vector search. A lookup shows the answer beside the page with the supporting lines outlined. A list prompt shows how the app read it, as a sentence with dropdowns that I can change without another model call. When the evidence is weak the app says "No direct answer" and shows the closest files.

## Alternatives considered
- **A chat interface.** Rejected: slower to verify, and it hides where an answer came from.
- **Drive's own search.** No extracted fields, no filing, no reminders.

## Consequences
Every answer has a citation to a page and line positions, so the reader has to keep line boxes for every page. There is no memory between prompts, which keeps the model's job small and the evals simple: a question set with expected files and cited lines. A person who wants to talk to their papers will not find that here.
