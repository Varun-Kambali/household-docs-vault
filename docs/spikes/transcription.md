# Transcription spike: which speech-to-text model writes a doctor's visit down

## Question

In v1 the owner records a doctor's visit (always in English) and the app writes the checkup
note from the transcript, so the transcriber has to get medicine names and doses right. This
spike measures two local models on five synthetic visits and applies the pick rule: the lowest
word error rate (WER) among candidates that find every medicine in at least 4 of 5 visits, with
a real-time factor under 0.5.

## Method

- Data: `evals/datasets/visits-v0`, five scripted visits (blood pressure follow-up, diabetes
  review, child with fever, post-surgery check, eye check). They run 219.7 to 247.7 seconds of
  audio and 593 to 645 words, and each names at least four medicines with a dose and one test.
  The set has 22 medicines; 20 have a dose, and the two without one are Becosules (visit 2) and
  ORS (visit 3). People are fictional; medicine names are real generic or common Indian brand
  names on purpose, since recognising them is the point.
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
- WER (`spikes/transcription/score.py`): jiwer on text that is lower-cased, with punctuation
  removed and whitespace collapsed. Number words are not converted to digits or back, so "one
  tablet" against "1 tablet" counts as a substitution; the numbers-style note below counts how
  often each happens.
- Medicine check: a medicine is found when its name and dose, as written in the script
  ("Telma 40", "Latanoprost 0.005"), appear in the transcript as a whole match. The text is
  lower-cased and punctuation is removed, except that a point between two digits is kept, so
  40.5 is not read as 40 and 0.05 is not read as 0.005. The dose must not run on into more digits
  or a decimal ("Telma 40" does not match "telma 400" or "telma 40.5"). A dose with its unit
  attached ("500mg") is read as "500 mg". A dose spoken as words ("forty", "zero point five") is
  not found. A medicine with no dose in the script (Becosules, ORS) is found by its name.
  "Names found" counts a medicine when its name appears with any dose.
- Timing: the real-time factor (RTF) is transcription seconds divided by audio seconds. The
  model is loaded first (recorded separately as load seconds) and one short clip is transcribed
  and discarded before the five visits. Each candidate runs in its own process, one at a time,
  with Ollama not running.
- Peak memory is the highest resident set size of that Python process, sampled every 0.25 s from
  before the load to the end, in MiB (GiB is MiB divided by 1024). MLX runs in the process, so
  the weights are counted.
- Machine: Apple M5, 16 GB. Each candidate ran three times (r1, r2, r3) on commit 4e9ae6b, with
  a clean working tree for code. Raw per-visit numbers and the transcripts are in
  `spikes/transcription/results/`.
- The earlier runs of this spike were replaced after two fixes: the dataset gained a fourth
  dosed medicine in visit 3, and the medicine check stopped counting a wrong decimal dose as
  found. None of their numbers are used here.
- Command: `make spikes-setup`, `make visits`, then
  `uv run --group spikes python -m spikes.transcription.run --set evals/datasets/visits-v0`.

## Results

Run r1, per visit. Medicines found counts name and dose together.

| Visit | Candidate | WER | Medicines found | Names found | RTF | Medicines missed |
|---|---|---|---|---|---|---|
| 1 | Parakeet | 3.0% | 3 of 4 | 3 | 0.016 | Atorvastatin 10 |
| 2 | Parakeet | 4.2% | 4 of 5 | 4 | 0.015 | Januvia 50 |
| 3 | Parakeet | 4.9% | 4 of 5 | 4 | 0.018 | Ondansetron 2 |
| 4 | Parakeet | 3.7% | 3 of 4 | 3 | 0.020 | Cefixime 200 |
| 5 | Parakeet | 5.1% | 2 of 4 | 2 | 0.017 | Latanoprost 0.005, Carboxymethylcellulose 0.5 |
| 1 | Whisper | 4.6% | 3 of 4 | 3 | 0.032 | Atorvastatin 10 |
| 2 | Whisper | 4.3% | 3 of 5 | 3 | 0.031 | Glimepiride 1, Becosules |
| 3 | Whisper | 3.7% | 4 of 5 | 4 | 0.031 | Ondansetron 2 |
| 4 | Whisper | 1.5% | 3 of 4 | 3 | 0.030 | Cefixime 200 |
| 5 | Whisper | 4.5% | 1 of 4 | 2 | 0.034 | Latanoprost 0.005, Carboxymethylcellulose 0.5, Moxifloxacin 0.5 |

Summary. WER is the mean of the five per-visit values. Both candidates gave the same
transcripts and scores on all three runs, so the three runs differ only in timing and memory.

| Measure | Parakeet TDT 0.6B v2 | Whisper large-v3-turbo |
|---|---|---|
| Mean WER (all three runs) | 4.18% | 3.71% |
| Visits with every medicine found | 0 of 5 | 0 of 5 |
| Medicines found, name and dose | 16 of 22 | 14 of 22 |
| Medicines found, name only | 16 of 22 | 15 of 22 |
| RTF over all visits (r1 / r2 / r3) | 0.0170 / 0.0166 / 0.0181 | 0.0315 / 0.0317 / 0.0356 |
| Slowest single visit RTF (r1 / r2 / r3) | 0.0196 / 0.0193 / 0.0221 | 0.0338 / 0.0345 / 0.0410 |
| Load time (r1 / r2 / r3) | 1.54 / 1.33 / 1.25 s | 16.68 / 2.40 / 2.40 s |
| Peak memory, Python process (r1 / r2 / r3) | 986 / 961 / 1,025 MiB (0.96 / 0.94 / 1.00 GiB) | 1,818 / 1,857 / 1,856 MiB (1.78 / 1.81 / 1.81 GiB) |
| Memory right after load | 138 MiB (0.13 GiB) | 1,751 to 1,752 MiB (1.71 GiB) |

Per run, Whisper's RTF is 1.86, 1.91 and 1.97 times Parakeet's, and its peak memory is 1.84,
1.93 and 1.81 times Parakeet's. The results files do not say why Whisper's first load took
16.7 s against 2.4 s on the other two runs; it was not investigated.

## Reading the numbers

- Neither model keeps medicine names safe. The misses are spelling errors in the name, not the
  dose. Parakeet wrote "atovastatin", "genuvia", "andancitron", "sefixine", "litanoprost" and
  "carboxymethylcellus". Whisper wrote "atovastatin", "glymepiride", "andansetron", "suffixine",
  "lutanoprost", "carboxymethyl cellless" and "amoxifloxacin", and heard "Becosules" as
  "Bikaujules" and "Beko suels". Every Parakeet miss is a wrong name; Whisper has one medicine
  with the right name and no matching dose (names found 15, found 14).
- Whisper has the lower mean WER (3.71% against 4.18%) but finds fewer medicines (14 against 16
  of 22). The two measures point in different directions, so this set does not say which model
  is the better base.
- Number style. The scripts have 62 digit tokens and 89 number words. Parakeet wrote 117 digit
  tokens and 32 number words, so it turns number words such as "one" and "twice" into digits much
  more than the script does. Whisper wrote 83 digit tokens and 58 number words, and 4 "mg"
  tokens where the script says "milligrams". Because numbers are not normalised, both styles
  cost WER. The medicine check is less affected, since doses are digits in both the script and
  the output.
- Both models misspell the same words ("atovastatin"). That may partly be how `say` pronounces
  rare drug names rather than the models' fault; see Limits.
- Speed and memory are not the constraint. Both are far under the RTF limit of 0.5 (0.0356 or
  lower for all visits together, 0.0410 or lower for the slowest visit), and both fit in 16 GB
  with room to spare.

## Pick

No candidate meets the rule. Both pass the speed test but fail the medicine test: neither finds
every medicine in any visit, against a requirement of at least 4 of 5 visits. So there is no
pick, and the rule has not been bent.

What the data does and does not show: the misses are name spellings, and no measurement here
shows a fix. Two options were not tried: checking each transcript medicine name against a list
of known medicine names and correcting near misses, or showing the owner the medicine names for
confirmation before the note is written. Either needs its own measurement on this set before it
is relied on.

## Limits

- The voices are system text-to-speech. They are cleaner and more regular than a real clinic
  with accents, interruptions, overlapping speech and a phone microphone, so real-world error
  rates are likely higher. They may also mispronounce rare drug names, which would inflate the
  misses for both models.
- Five visits and 22 medicines, so one missed medicine moves the "found" figure by about 4.5
  points. The set was written once, with no held-out part.
- One machine (Apple M5, 16 GB) and one noise level (25 dB, low-passed noise). Real rooms have
  other noise.
- Whisper was run with the library defaults, not tuned, and its decoding has a random fallback.
  Its three runs here were identical, which does not show that every run would be.
- The medicine check is a text match on the script's spelling and digit doses; a correct
  brand-to-generic swap or a dose spoken as words would count as a miss.
