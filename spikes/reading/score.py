"""Score OCR output against the synthetic ground truth.

A truth line is matched when an unused OCR line overlaps it with IoU >= 0.5 and its text
similarity (1 - CER) is >= 0.8. Kannada lines are skipped: the generator draws them without
shaping (see evals/datasets/spike-v0/LICENSE.md). Hindi lines are scored.
"""

from dataclasses import dataclass

from vault_synth.model import LineBox

from spikes.reading.engines import OcrLine

IOU_MIN = 0.5
SIMILARITY_MIN = 0.8


@dataclass(frozen=True)
class PageScore:
    cer: float
    line_recall: float
    matched: int
    truth_lines: int
    truth_chars: int = 0
    edit_distance: int = 0


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(truth: str, got: str) -> float:
    """Character error rate of one line; capped at 1."""
    if not truth:
        return 0.0 if not got else 1.0
    return min(1.0, edit_distance(truth, got) / len(truth))


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def score_page(truth: list[LineBox], got: list[OcrLine]) -> PageScore:
    """Pair each English truth line with its best-overlapping unused OCR line, then score.

    Page CER is the summed edit distance over all truth lines divided by their total length. A
    truth line with no OCR line at IoU >= 0.5 costs its full length. Extra OCR lines are ignored.
    """
    lines = [t for t in truth if t.lang != "kn"]
    used: set[int] = set()
    matched = total_chars = total_dist = 0
    for t in lines:
        best, best_iou = None, IOU_MIN
        for i, g in enumerate(got):
            if i in used:
                continue
            v = iou(t.bbox, g.bbox)
            if v >= best_iou:
                best, best_iou = i, v
        total_chars += len(t.text)
        if best is None:
            total_dist += len(t.text)
            continue
        used.add(best)
        dist = min(len(t.text), edit_distance(t.text, got[best].text))
        total_dist += dist
        if 1 - cer(t.text, got[best].text) >= SIMILARITY_MIN:
            matched += 1
    return PageScore(
        cer=total_dist / total_chars if total_chars else 0.0,
        line_recall=matched / len(lines) if lines else 0.0,
        matched=matched,
        truth_lines=len(lines),
        truth_chars=total_chars,
        edit_distance=total_dist,
    )
