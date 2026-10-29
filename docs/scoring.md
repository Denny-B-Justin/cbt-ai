# The overall score (Compare Budget)

Each compared budget gets a 0–100 score and a one-sentence reason. The score is **produced by the model and bounded by a
fixed rubric**, so it is explainable and cannot swing away from the numbers.

## Fixed rubric (`tagging/metrics.py::rubric_score`)

| Part | Points | Rule |
|---|---|---|
| Size | 0–60 | `60 · min(1, weighted_share / 0.25)`: a Rio-weighted share of 25 % or more earns the full 60 |
| Directness | 0–15 | `15 · principal / (principal + significant)` |
| Balance | 0–10 | 10 if both mitigation and adaptation shares ≥ 1 %, 5 if one, else 0 |
| Breadth | 0–15 | `15 · (EU objectives with share ≥ 1 %) / 6` |
| Harm | 0 to −25 | `−min(25, 25 · brown_share / 0.10)`: 10 % brown spending costs the full 25 |

Sum, clamped to 0–100, rounded. Returned with its parts (`Comparison.rubric`).

## Model score and guard (`pipeline.compare_budgets`)

1. The model receives, for each budget, only numbers and the names of the largest climate and harmful lines
   (`pipeline.brief`), never the document. The prompt contains the calibration table and the instruction that a budget with a
   clearly higher weighted share and no more harmful spending must not score lower.
2. The model's integer score is clamped to `rubric ± SCORE_GUARD` (15).
3. If the call fails with `AIResponseError`, `AIServerError` or `AIRateLimitError`, the rubric score is used with a
   generated reason and summary. Config, quota and cancellation errors are **not** swallowed.
4. The comparison table's last row shows these scores as `N / 100`; the same row ends the Excel "Comparison" sheet.

## Changing it

- Weights and thresholds are literals in `rubric_score`; the matching plain-language description is in
  `utils/methodology.py` ("The overall score"). Keep them in sync.
- Widen or narrow `SCORE_GUARD` to trade model judgement against reproducibility.
- Tests: `tests/test_metrics.py` (bounds; more climate share, more directness, wider breadth and balance raise the score, harm lowers it; missing shares) and
  `tests/test_pipeline.py` (guard, fallback, error propagation).
