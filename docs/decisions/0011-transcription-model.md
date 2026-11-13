# 0011. Visits are transcribed with Parakeet, and medicine names are checked before a note is saved
Date: 2026-11-13 · Status: accepted

## Context
In M5 the app turns a recorded doctor's visit, always in English, into a checkup note, so medicine names and doses have to be right. The M1 spike rendered five synthetic visits (a BP follow-up, a diabetes review, a child's fever, a post-surgery check and an eye check, with 22 medicines, 20 of them with a dose) using the Mac's Indian English voices and light room noise, and ran two local models three times each. The rule set before the run was the lowest word error rate among models that find every medicine in at least 4 of 5 visits at a real-time factor under 0.5. Method and numbers: `docs/spikes/transcription.md`; results: `spikes/transcription/results/2026-11-12_*_4e9ae6b_r*.json`.

| Model | Word error rate | Medicines found, name and dose | Visits with every medicine | Real-time factor | Peak memory |
|---|---|---|---|---|---|
| Parakeet TDT 0.6B v2 (parakeet-mlx) | 4.18% | 16 of 22 | 0 of 5 | 0.017 to 0.018 | 961 to 1,025 MiB |
| Whisper large-v3-turbo (mlx-whisper) | 3.71% | 14 of 22 | 0 of 5 | 0.032 to 0.036 | 1,818 to 1,857 MiB |

Neither model met the rule. Both are far faster than needed, and both misspell medicine names even when they hear the dose ("atovastatin" for atorvastatin, in both).

## Decision
Parakeet TDT 0.6B v2 transcribes visits, and no medicine reaches a saved note on the transcript's word alone. Each medicine name in the draft note is matched against that visit's prescription, when one is filed, and against a list of known medicine names. A name that matches neither is shown to me to confirm or correct before the note is saved. The target is no wrong medicine saved without my OK.

The spike does not settle which model is better: Whisper has the lower word error rate and Parakeet finds more medicines. I chose Parakeet because the medicines matter more than the other words in a checkup note, it uses about half the memory, and in the earlier runs that were replaced after a dataset fix (results at commit 85795a4) Whisper repeated phrases and varied from run to run, while Parakeet did not.

## Alternatives considered
- **Whisper large-v3-turbo.** Lower word error rate, but two fewer medicines, and the replaced runs showed it looping.
- **I confirm every medicine by hand.** The safest, but a step on every visit even when the prescription agrees.
- **Save the note as heard, with medicines marked unchecked.** The fastest, but a note could be read before anyone checks it.
- **Steer the model with a medicine vocabulary** (Whisper's initial prompt). Not tried; Parakeet takes no prompt.

## Consequences
- M5 needs an openly licensed list of medicine names, generic and Indian brand names, and a matcher that is measured on this visit set before it is relied on.
- The check leans on the visit's prescription being filed. When there is none, more names come to me.
- The voices are text to speech, cleaner and more regular than a real clinic, and there are only five visits on one machine. A real recording made for the purpose is the check that matters.
- The visit audio is not in the repo, because Apple's licence for its voices does not cover public sharing; `make visits` recreates it on a Mac.
