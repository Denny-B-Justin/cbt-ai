# The overall score (Compare Budget)

Each compared budget gets a 0–100 score and a one-sentence reason. The score is **produced by the model and bounded by a
fixed rubric**, so it is explainable and cannot swing away from the numbers.

## Fixed rubric (`tagging/metrics.py::rubric_score`)

| Part | Points | Rule |
|---|---|---|
| Size | 0–60 | `60 · min(1, climate_share / 0.25)`: a level-weighted climate share of 25 % or more earns the full 60 |
| Directness | 0–20 | `20 · high_level_share`: the share of the climate spend in lines at levels 100 and 70 |
| Balance | 0–10 | 10 if both mitigation and adaptation shares ≥ 1 %, 5 if one, else 0 |
| Breadth | 0–10 | `10 · min(1, climate_sectors / 5)`: sectors with at least 1 % of the climate spend; five or more earn the full 10 |

Sum, clamped to 0–100, rounded. Returned with its parts (`Comparison.rubric`).

## Model score and guard (`pipeline.compare_budgets`)

1. The model receives, for each budget, only numbers (climate, mitigation and adaptation shares, the share at levels 100
   and 70, CM / CA / CB counts, sectors) and the names of the largest climate lines (`pipeline.brief`), never the
   document. The prompt explains codes and levels, contains the calibration table, and says that a budget with a clearly
   higher climate share must not score lower.
2. The model's integer score is clamped to `rubric ± SCORE_GUARD` (15).
3. If the call fails with `AIResponseError`, `AIServerError` or `AIRateLimitError`, the rubric score is used with a
   generated reason and summary. Config, quota and cancellation errors are **not** swallowed.
4. The comparison table's last row shows these scores as `N / 100`; the same row ends the Excel "Comparison" sheet.

## Changing it

- Weights and thresholds are literals in `rubric_score`; the matching plain-language description is in
  `utils/methodology.py` ("The overall score"). Keep them in sync.
- Widen or narrow `SCORE_GUARD` to trade model judgement against reproducibility.
- Tests: `tests/test_metrics.py` (bounds; more climate share, more spending at high levels, wider breadth and balance raise
  the score; missing shares) and `tests/test_pipeline.py` (guard, fallback, error propagation).
