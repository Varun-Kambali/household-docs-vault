# Transcription spike: which speech-to-text model writes a doctor's visit down

## Question

In v1 the owner records a doctor's visit (always in English) and the app writes the checkup
note from the transcript, so the transcriber has to get medicine names and doses right. This
spike measures two local models on five synthetic visits and applies the pick rule: the lowest
word error rate (WER) among candidates that find every medicine in at least 4 of 5 visits, with
a real-time factor under 0.5.

## Method

- Data: `evals/datasets/visits-v0`, five scripted visits (blood pressure follow-up, diabetes
  review, child with fever, post-surgery check, eye check). Each is 589 to 645 words, 210 to
  248 seconds of audio, and names 4 or 5 medicines with doses and one test: 21 medicines in all.
  People are fictional; medicine names are real generic or common Indian brand names on
  purpose, since recognising them is the point.
- Audio: macOS `say` voices Rishi, Aman and Tara (en_IN), 160 words per minute, 0.45 s pause
  between lines, then low-passed Gaussian room noise generated in code at 25 dB signal-to-noise
  (measured 25.0 dB on every visit), written as 16 kHz mono FLAC. The audio is not committed
  because of Apple's voice licence; `make visits` rebuilds it (see
  `evals/datasets/visits-v0/LICENSE.md`). Settings and per-visit durations are in
  `evals/datasets/visits-v0/manifest.json`; rendered on macOS 26.7.1.
- Candidates, both in-process on MLX: Whisper large-v3-turbo through `mlx-whisper` 0.4.3
  (`mlx-community/whisper-large-v3-turbo`, revision `a4aaeec0`, float16, language forced to
  English, all other settings the library defaults including its temperature fallback) and
  Parakeet TDT 0.6B v2 through `parakeet-mlx` 0.7.0 (`mlx-community/parakeet-tdt-0.6b-v2`,
  revision `8ae15530`, bfloat16, greedy decoding, 120 s chunks with 15 s overlap).
- Scoring (`spikes/transcription/score.py`): WER from jiwer on text that is lower-cased, with
  punctuation removed and whitespace collapsed. Number words are not converted to digits or
  back, so "one tablet" against "1 tablet" counts as a substitution; the section on style below
  counts how often each happens. A medicine is found when its name and dose, as written in the
  script ("Telma 40"), appear as whole tokens in the transcript. For this check only, a dose
  with its unit attached ("500mg") is read as "500 mg". "Names found" counts a medicine when its
  name appears with any dose.
- Timing: the real-time factor (RTF) is transcription seconds divided by audio seconds. The
  model is loaded first (recorded separately as load seconds) and one short clip is transcribed
  and discarded before the five visits. Each candidate runs in its own process, one at a time,
  with Ollama not running.
- Peak memory is the highest resident set size of that Python process, sampled every 0.25 s from
  before the load to the end, in MiB (GiB is MiB divided by 1024). MLX runs in the process, so
  the weights are counted.
- Machine: Apple M5, 16 GB. Each candidate ran three times. Run r1 is commit 66ca825; r2 and r3
  are commit e1f4cc6, which only added the `--label` option to the runner. Raw per-visit
  numbers and the transcripts are in `spikes/transcription/results/`.
- An earlier run scored "500mg" as a miss. That was a scoring flaw, so the matcher was fixed
  (with a test) and everything was run again; the earlier files were discarded and none of
  their numbers are used here.
- Command: `make spikes-setup`, `make visits`, then
  `uv run --group spikes python -m spikes.transcription.run --set evals/datasets/visits-v0`.

## Results

Run r1, per visit. Medicines found counts name and dose together.

| Visit | Candidate | WER | Medicines found | Names found | RTF | Medicines missed |
|---|---|---|---|---|---|---|
| 1 | Parakeet | 3.3% | 3 of 4 | 3 | 0.015 | Atorvastatin 10 |
| 2 | Parakeet | 4.3% | 4 of 5 | 4 | 0.015 | Januvia 50 |
| 3 | Parakeet | 4.7% | 3 of 4 | 3 | 0.015 | Ondansetron 2 |
| 4 | Parakeet | 3.7% | 3 of 4 | 3 | 0.019 | Cefixime 200 |
| 5 | Parakeet | 5.2% | 1 of 4 | 2 | 0.016 | Timolol 0.5, Latanoprost 0.005, Carboxymethylcellulose 0.5 |
| 1 | Whisper | 4.4% | 3 of 4 | 3 | 0.122 | Atorvastatin 10 |
| 2 | Whisper | 4.8% | 3 of 5 | 3 | 0.173 | Glimepiride 1, Becosules |
| 3 | Whisper | 14.9% | 3 of 4 | 3 | 0.068 | Ondansetron 2 |
| 4 | Whisper | 2.0% | 3 of 4 | 3 | 0.029 | Cefixime 200 |
| 5 | Whisper | 3.4% | 1 of 4 | 2 | 0.032 | Latanoprost 0.005, Carboxymethylcellulose 0.5, Moxifloxacin 0.5 |

Summary over the three runs. WER is the mean of the five per-visit values.

| Measure | Parakeet TDT 0.6B v2 | Whisper large-v3-turbo |
|---|---|---|
| Mean WER (r1 / r2 / r3) | 4.3% / 4.3% / 4.3% | 5.9% / 6.2% / 9.3% |
| Visits with every medicine found | 0 of 5 (all runs) | 0 of 5 (all runs) |
| Medicines found, name and dose | 14 of 21 (all runs) | 13 of 21 (all runs) |
| Medicines found, name only | 15 of 21 | 14 of 21 |
| RTF over all visits (r1 / r2 / r3) | 0.016 / 0.017 / 0.017 | 0.087 / 0.041 / 0.044 |
| Slowest single visit RTF (r1 / r2 / r3) | 0.019 / 0.018 / 0.020 | 0.173 / 0.064 / 0.070 |
| Load time | 1.2 to 1.4 s | 2.3 to 2.4 s |
| Peak memory, Python process | 996 to 1,044 MiB (0.97 to 1.02 GiB) | 1,864 to 1,865 MiB (1.82 GiB) |
| Memory right after load | 138 MiB (0.13 GiB) | 1,752 MiB (1.71 GiB) |

Parakeet gave the same transcripts and scores on all three runs. Whisper did not: the same
audio gave 5.9%, 6.2% and 9.3%.

## Reading the numbers

- Neither model keeps medicine names safe. The misses are spelling errors in the name, not the
  dose: for the names Parakeet missed it wrote "atovastatin", "genuvia", "andancitron",
  "sefixine", "timol" and "litanoprost"; Whisper wrote "atovastatin", "glymepiride", "andansetron",
  "lutanoprost" and "amoxifloxacin", and heard "Becosules" as "Bikaujules" and "Beko Sewells". Only
  1 medicine per candidate had the right name with a wrong dose.
- Whisper hallucinated loops of repeated text. In r3 it inserted a phrase over and over in visit
  2 ("do you want to use my studies", about 57 extra words) and repeated "have a great day" at
  the end of visit 3 (101 extra words), and in the same run it dropped a sentence from visit 3.
  In r1 visit 3 (14.9%) has a phrase that repeats eight times ("will not cause death"), none of
  it in the script. Parakeet's word count stays within 8 of the script's in every visit.
- Number style. The scripts have 61 digit tokens and 86 number words. Parakeet wrote 116 digit
  tokens and 29 number words, so it turns "one" and "twice" style words into digits much more
  than the script does. Whisper (r1) wrote 76 and 60, and used "mg" 4 times where the script
  says "milligrams". Because numbers are not normalised, both styles cost WER; the medicine
  check is not affected, since doses are digits in both the script and the output.
- Both models misspell the same words ("atovastatin"). That may partly be how `say` pronounces
  rare drug names rather than the models' fault; see Limits.
- Speed and memory are not the constraint. Both are far under the RTF limit, and both fit in
  16 GB with room to spare.

## Pick

No candidate meets the rule. Both pass the speed test (RTF 0.087 or lower against a limit of
0.5) but fail the medicine test: neither finds every medicine in any visit, against a
requirement of at least 4 of 5. So there is no pick, and the rule has not been bent.

For the next step only: Parakeet is the stronger base. It has the lower WER (4.3% against 5.9
to 9.3%), identical results on every run, 14 medicines found against 13, no runaway extra text,
an RTF about 2 to 5 times lower, and half the memory. What the data does not show is whether
anything fixes the medicine names. Two options that were not tried: checking each transcript
medicine name against a list of known medicine names and correcting near misses, or showing the
owner the medicine names for confirmation before the note is written. Either needs its own
measurement on this set before it is relied on.

## Limits

- The voices are system text-to-speech. They are cleaner and more regular than a real clinic
  with accents, interruptions, overlapping speech and a phone microphone, so real-world error
  rates are likely higher. They may also mispronounce rare drug names, which would inflate the
  misses for both models.
- Five visits and 21 medicines, so one missed medicine moves the "found" figure by 5 points.
  The set was written once, with no held-out part.
- One machine (Apple M5, 16 GB) and one noise level (25 dB, low-passed noise). Real rooms have
  other noise.
- Whisper was run with the library defaults, not tuned. Settings that reduce repeats (for
  example, turning off conditioning on the previous text) were not tried.
- The medicine check is a text match on the script's spelling; a correct brand-to-generic
  swap would count as a miss.
