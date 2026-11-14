from __future__ import annotations

import re
from typing import Any


GRADE_COLORS = ["#004000", "#00ff00", "#ffff00", "#ff8040", "#ff0000"]
_NON_ADDITIVE_MEASURE = re.compile(
    r"(mm/h|m/s|mm/yr|%|등급|비율|평균|지수|rate|ratio|pct|score|grade)",
    re.IGNORECASE,
)


def normalize_plot_parameters(
    parameters: dict[str, Any],
    columns: list[str],
) -> dict[str, Any]:
    normalized = dict(parameters)
    selected = [
        str(normalized[field])
        for field in ("y_column", "column", "value_column")
        if normalized.get(field)
    ] or [str(column) for column in columns]
    if (
        normalized.get("agg") in {None, "sum"}
        and any(_NON_ADDITIVE_MEASURE.search(column) for column in selected)
    ):
        normalized["agg"] = "mean"
    return normalized
