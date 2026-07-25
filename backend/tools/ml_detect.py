"""
Track B — ml_detect.py

Tool name  : ml_detect  (Contract 2 fixed list)
Input      : ctx.df                      — canonical transactions DataFrame
             ctx.artifacts["features"]  — DataFrame indexed by customer_id
                                          (from feature_engineer; required)
             pattern_types              — list[str] | None; passed through to
                                          select the right feature columns

Output     : ToolResult.artifacts["ml_scores"]
               list[{entity_id, score, percentile, top_features: list[str]}]

Design decisions (WORKPLAN.md H22-H28):

  Primary model  : IsolationForest (contamination=0.05)
    - Unsupervised; no labels needed for production use
    - Naturally suited to high-dimensional, mixed-scale AML feature spaces
    - sklearn default n_estimators=100, random_state=42 for reproducibility

  Secondary model: LocalOutlierFactor (n_neighbors=20)
    - Complements IF: catches local density anomalies IF misses
    - Fused score = 0.6 * IF_score + 0.4 * LOF_score (both percentile-ranked)
    - LOF is only run if n_samples >= LOF_MIN_SAMPLES (avoid degenerate KNN)

  Feature selection for ML:
    - Use the columns from ctx.artifacts["feature_list"] that are present in
      the features DataFrame (exclude metadata like zscore_n_samples)
    - Drop columns with zero variance (constant features add noise)
    - StandardScaler applied before both models

  Explainability (cheap, no SHAP):
    - For each flagged entity, top-3 contributing features by
      |value - column_median| / column_std (deviation from peer median)
    - This is what Contract 2 specifies: top_features: list[str]

  Sample size guard:
    - IF needs >= IF_MIN_SAMPLES. LOF needs >= LOF_MIN_SAMPLES.
    - Below thresholds: return ok=True with empty ml_scores and a note.
    - Never crash; comply with the "never raise for expected condition" rule.

No tool may import from backend.agent.* or from another tool.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

from backend.tools.base import ToolContext, ToolResult, tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IF_CONTAMINATION   = 0.05    # expected fraction of anomalies
IF_N_ESTIMATORS    = 100
IF_RANDOM_STATE    = 42
LOF_N_NEIGHBORS    = 20
LOF_MIN_SAMPLES    = 30      # LOF is unstable below this
IF_MIN_SAMPLES     = 10      # absolute floor for IF
IF_WEIGHT          = 0.60    # fused score weights
LOF_WEIGHT         = 0.40
TOP_N_FEATURES     = 3       # features reported per entity

# Metadata columns that are NOT ML features
_META_COLS = {"zscore_n_samples"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_feature_cols(
    feat_df: pd.DataFrame,
    feature_list: list[str],
) -> list[str]:
    """Return usable ML columns: in feature_list, present in df, non-zero variance.

    Excludes metadata columns (zscore_n_samples) and constant columns.
    """
    candidates = [
        c for c in feature_list
        if c in feat_df.columns and c not in _META_COLS
    ]
    # Drop zero-variance columns
    keep = [c for c in candidates if feat_df[c].std() > 0]
    return keep


def _top_features(
    entity_values: pd.Series,
    col_medians: pd.Series,
    col_stds: pd.Series,
    feature_cols: list[str],
    n: int = TOP_N_FEATURES,
) -> list[str]:
    """Return the top-n features by |value - median| / std for a single entity."""
    scores: dict[str, float] = {}
    for col in feature_cols:
        if col_stds[col] > 0:
            scores[col] = abs(entity_values[col] - col_medians[col]) / col_stds[col]
        else:
            scores[col] = 0.0
    return sorted(scores, key=lambda c: scores[c], reverse=True)[:n]


def _percentile_rank(scores: np.ndarray) -> np.ndarray:
    """Convert raw anomaly scores to percentile ranks in [0, 1].

    Higher percentile = more anomalous.
    """
    n = len(scores)
    if n == 0:
        return scores
    # argsort twice gives rank; divide by (n-1) to get [0,1]
    ranks = scores.argsort().argsort()
    return ranks / max(n - 1, 1)


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="ml_detect",
    params={
        "pattern_types": (
            "list[str] | None — passed from the planner to scope feature selection. "
            "If None, all features are used."
        ),
        "min_samples": (
            "int | None — override the minimum sample threshold for ML models. "
            "Defaults to IF_MIN_SAMPLES (10)."
        ),
    },
    description=(
        "Unsupervised anomaly detection via IsolationForest + LocalOutlierFactor. "
        "Reads ctx.artifacts['features'] (must run feature_engineer first). "
        "Emits artifacts['ml_scores']: list[{entity_id, score, percentile, top_features}]."
    ),
)
def ml_detect(
    ctx: ToolContext,
    pattern_types: Optional[list[str]] = None,
    min_samples: Optional[int] = None,
    **kw,
) -> ToolResult:
    """Run unsupervised ML anomaly detection on per-customer features.

    Parameters
    ----------
    ctx          : ToolContext — features in ctx.artifacts["features"]
    pattern_types: list of AML patterns (passed through for logging; does not
                   change which features are used — that was decided by feature_engineer)
    min_samples  : override minimum sample count for models
    """
    try:
        feat_df: pd.DataFrame = ctx.artifacts.get("features", pd.DataFrame())
        feature_list: list[str] = ctx.artifacts.get("feature_list", [])

        if feat_df is None or len(feat_df) == 0:
            return ToolResult(
                ok=True,
                artifacts={"ml_scores": []},
                metrics={"ml_entities_scored": 0},
                notes=["ml_detect: no features available — run feature_engineer first"],
            )

        floor = min_samples if min_samples is not None else IF_MIN_SAMPLES
        n = len(feat_df)

        if n < floor:
            return ToolResult(
                ok=True,
                artifacts={"ml_scores": []},
                metrics={"ml_entities_scored": 0},
                notes=[
                    f"ml_detect: only {n} entities — below minimum {floor} for "
                    f"reliable anomaly detection; ml_scores is empty"
                ],
            )

        # ------------------------------------------------------------------
        # Feature matrix
        # ------------------------------------------------------------------
        feature_cols = _select_feature_cols(feat_df, feature_list)

        if not feature_cols:
            # Fallback: use all numeric non-meta columns
            feature_cols = [
                c for c in feat_df.select_dtypes(include=[np.number]).columns
                if c not in _META_COLS and feat_df[c].std() > 0
            ]

        if not feature_cols:
            return ToolResult(
                ok=True,
                artifacts={"ml_scores": []},
                metrics={"ml_entities_scored": 0},
                notes=["ml_detect: no usable numeric features found after variance filter"],
            )

        X_raw = feat_df[feature_cols].fillna(0.0).values.astype(float)

        scaler = StandardScaler()
        X = scaler.fit_transform(X_raw)

        # ------------------------------------------------------------------
        # IsolationForest (primary)
        # ------------------------------------------------------------------
        iso = IsolationForest(
            n_estimators=IF_N_ESTIMATORS,
            contamination=IF_CONTAMINATION,
            random_state=IF_RANDOM_STATE,
        )
        iso.fit(X)
        # decision_function: lower = more anomalous; negate so higher = more anomalous
        if_raw = -iso.decision_function(X)
        if_pct = _percentile_rank(if_raw)

        # ------------------------------------------------------------------
        # LocalOutlierFactor (secondary) — only if enough samples
        # ------------------------------------------------------------------
        use_lof = n >= LOF_MIN_SAMPLES
        if use_lof:
            lof = LocalOutlierFactor(
                n_neighbors=min(LOF_N_NEIGHBORS, n - 1),
                novelty=False,
            )
            lof.fit(X)
            # negative_outlier_factor_: more negative = more anomalous; negate
            lof_raw = -lof.negative_outlier_factor_
            lof_pct = _percentile_rank(lof_raw)
            fused_pct = IF_WEIGHT * if_pct + LOF_WEIGHT * lof_pct
        else:
            lof_pct = np.zeros(n)
            fused_pct = if_pct  # 100% IF when LOF skipped

        # ------------------------------------------------------------------
        # Top-3 features per entity (deviation from peer median)
        # ------------------------------------------------------------------
        feat_sub = feat_df[feature_cols].fillna(0.0)
        col_medians = feat_sub.median()
        col_stds    = feat_sub.std().replace(0, 1.0)   # avoid divide-by-zero

        ml_scores: list[dict[str, Any]] = []
        entity_ids = feat_df.index.tolist()

        for i, eid in enumerate(entity_ids):
            entity_row = feat_sub.iloc[i]
            top3 = _top_features(entity_row, col_medians, col_stds, feature_cols)
            ml_scores.append({
                "entity_id":    str(eid),
                "score":        round(float(fused_pct[i]), 4),
                "percentile":   round(float(fused_pct[i]), 4),
                "top_features": top3,
            })

        # Sort descending by score for easier downstream consumption
        ml_scores.sort(key=lambda r: r["score"], reverse=True)

        patterns_label = ", ".join(pattern_types) if pattern_types else "all"
        note = (
            f"ml_detect: scored {n} entities on {len(feature_cols)} features "
            f"(IF{'+ LOF' if use_lof else ' only'}), "
            f"pattern_types=[{patterns_label}]"
        )

        return ToolResult(
            ok=True,
            artifacts={"ml_scores": ml_scores},
            metrics={
                "ml_entities_scored": n,
                "feature_cols_used": len(feature_cols),
                "lof_used": use_lof,
            },
            notes=[note],
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"ml_detect failed: {exc}")
