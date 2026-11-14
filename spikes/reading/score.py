"""Score OCR output against the synthetic ground truth. The scorer lives in src."""

from household_vault.scoring import (
    IOU_MIN,
    SIMILARITY_MIN,
    PageScore,
    cer,
    edit_distance,
    iou,
    score_page,
)

__all__ = [
    "IOU_MIN",
    "SIMILARITY_MIN",
    "PageScore",
    "cer",
    "edit_distance",
    "iou",
    "score_page",
]
