# 0019. The model reads the prompt, and code works out the rest
Date: 2026-11-28 · Status: accepted

## Context
A prompt like "Which insurance papers expire before June?" has to become a structured query: who, which types, which date field and which dates. A small local model reads language well enough, but it cannot be trusted with the parts that have one right answer. The M2 tuning had already shown this: when the model converted dates and amounts itself, it swapped day and month ([ADR 0017](0017-values-read-as-printed-and-the-spelling-snap.md)).

## Decision
**The model copies, code decides.** `qwen3:4b` through Ollama sees only the prompt and the fixed vocabulary (types, areas, askable fields, date roles), never a document. Under a fixed JSON schema it fills slots: the intent (look up one value, find a document, or list), people, types, the field asked, a date phrase and a place, each as the words the prompt used. Code then works out what they mean, from closed vocabularies:
- **People** from the household's names and aliases.
- **Dates** from a date parser that knows "before March", "this year", "FY 2025-26" and the year end. The model never works out a date.
- **Types** from the words each type is called.
- **The list cue** (which, all, every, a plural type word) with a question guard, so "Is all of Suresh's insurance paid?" stays a question.

Where the model leaves a slot empty or fills it with words the code cannot read, code fills the slot from the prompt's own words, with the same closed vocabularies. Where the model filled a slot and the words disagree, the model's slot stays and the conflict is counted (38 in the test run). Anything the code cannot read is shown to the person as "Couldn't read: before Diwali" and nothing is invented.

**The D-012 lesson, applied to search.** The M2 lesson was to copy as printed and convert in code. The same shape holds here: the model's job is to point at words, and code's job is to turn them into people and dates. Each rule is a closed vocabulary (the household, the stored place values, the type words, the list cue words), never a string taken from the questions I tuned on.

**Why `qwen3:4b` and not `qwen3:8b`.** I ran both on the validation questions with the same code. The larger model read the prompts about as well, and the small gaps went both ways. It was slower for every search, and it is a 5.2 GB model on a 16 GB Mac that already holds the vision model. Once code repaired the people slot, the accuracy argument for the larger model was gone, and the speed and memory arguments stayed. I chose the 4 billion model, and deleted the 8 billion one.

## Alternatives considered
- **Let the model resolve people and dates.** Faster to build, and wrong in the ways that matter: a day and month swap, or an invented person.
- **No model, rules only.** A prompt is free text with typos and synonyms, and rules alone could not cover it.
- **A bigger model.** See above.

## Consequences
On the test split of `search-v1` (`evals/results/2026-11-28_search_test_93a99db.json`), list prompts are read into the right people, types, date field, range and place for 82.5% of 40 (the target is 80%; 76.9% on the 26 that ask about eval-v1 documents and 92.9% on the 14 that ask about the extra ones). A full search takes a median of 3.24 s and 3.84 s at the 95th percentile, and the first search after loading the model took 8.5 s. Seven list prompts missed on a wrong slot, and six prompts were misread (`causes` in the results file). [Requirements](../requirements.md) says why the list target moved from 90% to 80%.

The reading prompt, the vocabulary words and every threshold were tuned on the validation split only, and the test split was run once, with no change to any of them afterwards.
