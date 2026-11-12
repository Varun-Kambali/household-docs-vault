# Reading spike: which OCR engine reads lines and their positions

## Question

The app has to outline the exact lines an answer came from, so the reader needs both text
and a box per line. This spike measures three local engines on the synthetic set
`evals/datasets/spike-v0` (18 documents, each as a clean PDF and a phone-photo JPG).

## Method

- Clean pages: the PDF rendered at 200 dpi with pypdfium2. Photo pages: the JPG as is.
- Boxes are normalised to 0..1 with the origin at the top left, like the ground truth. Apple
  Vision returns a bottom-left origin and is converted.
- A truth line is matched when an unused OCR line overlaps it with IoU of at least 0.5 and
  its text similarity (1 - CER) is at least 0.8. Line recall is matched lines over truth lines.
- Page CER is the summed edit distance over all truth lines divided by their total length. A
  truth line with no overlapping OCR line costs its full length. Extra OCR lines are ignored.
- Kannada lines are not scored: the generator draws them without shaping (see
  `evals/datasets/spike-v0/LICENSE.md`). The remaining lines are scored. Tesseract and PaddleOCR run
  with English models only, which would handicap them on Hindi lines. The set has no Hindi lines,
  so every line scored is English; the results files also carry English-only figures
  (`*_en` fields), and they equal the all-line figures.
- Each engine runs in its own subprocess. Seconds per page is the wall time of one read,
  after one untimed warm-up page. Peak memory is the subprocess's maximum resident set size.
- Machine: Apple M5, 16 GB. Commit 1f94178. Raw per-document numbers are in
  `spikes/reading/results/`.
- Matching is greedy: truth lines are taken in file order, and each takes the unused OCR line
  with the best IoU of at least 0.5, so one OCR line can match only one truth line.
- Command: `make spikes-setup`, then `uv run --group spikes python -m spikes.reading.run --set evals/datasets/spike-v0`.

## Results

Medians are over the 18 documents of each variant. "Mean recall" is the mean over the same
documents.

| Engine | Version | CER clean | CER photo | Recall clean (median / mean) | Recall photo (median / mean) | Seconds per page (clean / photo) | Peak memory |
|---|---|---|---|---|---|---|---|
| Apple Vision (ocrmac, accurate) | ocrmac 1.0.1 | 0.002 | 0.000 | 1.00 / 0.969 | 1.00 / 0.961 | 0.21 / 0.22 | 308 MB |
| Tesseract | 5.5.4, English data | 0.299 | 0.380 | 0.43 / 0.480 | 0.52 / 0.564 | 0.28 / 0.31 | 170 MB |
| PaddleOCR | 3.7.0, PP-OCRv6 medium detection and recognition, CPU | 0.000 | 0.002 | 1.00 / 0.985 | 1.00 / 0.962 | 11.2 / 10.8 | 6,221 MB |

Documents under 0.9 line recall on the photo variant:

- Apple Vision: both card fronts (0.88), tax invoices (0.74 and 0.80).
- PaddleOCR: lab reports (0.86 and 0.89), tax invoices (0.83 and 0.83).
- Tesseract: 17 of 18.

## Reading the numbers

- Tesseract reads the characters but its line grouping merges a label and its value into one
  line on form-style pages ("Policy Number P/79/5309/6290115 Product"), so those lines fail
  the IoU test against the ground truth. It was run with its default page segmentation.
  Another segmentation mode or word-level boxes might change this; it was not tried.
- PaddleOCR matches Apple Vision on accuracy but takes about 10.8 s per page on CPU and
  6.2 GB of memory, which is 38% of the machine's RAM.
- Apple Vision has the lowest cost: 0.22 s per page and 308 MB.

## Pick

The rule is the highest line recall on photo pages among engines at or under 5 s per page.
PaddleOCR is over 5 s and is out. Of the two that remain, Apple Vision has 0.961 mean photo
line recall against Tesseract's 0.564, so **Apple Vision (through ocrmac, accurate mode)** is
the pick.

It meets the 0.9 bar on the median photo document (1.00) and on the mean (0.961), but not on
every document: four photo pages fall under 0.9, the worst being a tax invoice at 0.74. Those
are the cases to inspect before the reader is built on this engine, and the next step is to
look at which lines were lost there (small print, dense tables or a box that was split).

Apple Vision is macOS only. That fits the design, since the app runs only on the owner's Mac.
The synthetic photos are generated, so a real-phone check on non-sensitive pages is still
needed before this result is treated as final.
