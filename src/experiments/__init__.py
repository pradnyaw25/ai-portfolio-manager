"""Fund-as-config experiments: baselines, ablations, and their comparison.

A *variant* is any strategy that turns a start capital + a price window into an
end value. The live fund is one variant; buy-and-hold and random-from-watchlist
are others. Keeping them behind one `VariantResult` currency is the seam the
ablation harness and the multi-fund tournament reuse (roadmap V1-1 / V1-12).
"""

from src.experiments.baselines import (
    VariantResult,
    buy_and_hold,
    fund_variant,
    random_from_watchlist,
    with_alpha,
)

__all__ = [
    "VariantResult",
    "buy_and_hold",
    "fund_variant",
    "random_from_watchlist",
    "with_alpha",
]
