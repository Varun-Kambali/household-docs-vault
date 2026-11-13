# 0008. Pages are read with Apple's built-in text recognition
Date: 2026-11-13 · Status: accepted

## Context
Every page that reaches the vault has to become text with a position for each line, so the app can fill fields and outline the lines a search answer came from. Pages arrive as clean PDFs and as phone photos. The app runs only on my Mac (0001). I measured three engines on the synthetic spike set `evals/datasets/spike-v0` (18 documents, each as a clean PDF and a phone photo), scoring line recall against ground-truth line boxes. The rule, set before the run, was the highest line recall on photo pages among engines at or under 5 s a page. Method and numbers: `docs/spikes/reading.md`; results: `spikes/reading/results/2026-11-12_*_1f94178.json`.

## Decision
I read pages with Apple Vision text recognition through `ocrmac`, in accurate mode. On the photo pages it found a median of 1.00 and a mean of 0.961 of the true lines, at 0.22 s a page and a 308 MB peak.

## Alternatives considered
- **PaddleOCR** (PP-OCRv6 medium, on the CPU). As accurate on photos (mean 0.962), but 10.8 s a page and a 6,221 MB peak, so it fails the 5 s rule and takes 38% of the Mac's memory.
- **Tesseract 5.5.4.** Fast (0.31 s a page) but a mean photo line recall of 0.564: on form-style pages it joins a label and its value into one line. Other segmentation modes were not tried.
- **A cloud OCR service.** Ruled out: real documents never leave my Mac (0001).

## Consequences
- The reader is macOS only, which fits the design but not CI, which runs on Linux. The Mac-only packages stay in a separate dependency group (`make spikes-setup`), and CI and the Docker image will need a stand-in reader.
- Four photo pages scored under 0.9: two tax invoices (0.74 and 0.80) and both card fronts (0.88). Dense tables and small print are what M2 checks first.
- The photos are generated, not taken with a phone, and only English lines were scored (the spike set has 8 Kannada lines and no Hindi). A check on real phone photos of non-sensitive pages is still needed before this is final.
