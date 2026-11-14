import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))

from coastal_web.metric_catalog import metric_definitions, resolve_metric_question  # noqa: E402


def test_metric_catalog_defines_denominator_unit_and_sql_for_core_metrics():
    definitions = {item["id"]: item for item in metric_definitions()}

    assert set(definitions) == {
        "high_risk_ratio",
        "high_risk_share",
        "average_risk_grade",
        "high_risk_concentration",
    }
    assert definitions["high_risk_ratio"]["denominator"] == "해당 집단의 전체 유효 격자 수"
    assert definitions["high_risk_ratio"]["unit"] == "%"
    assert "COUNT(*)" in definitions["high_risk_ratio"]["sql"]
    assert definitions["high_risk_concentration"]["unit"] == "배"


def test_metric_resolver_asks_for_meaning_when_high_risk_ratio_is_ambiguous():
    result = resolve_metric_question("고위험 비율이 가장 높은 읍면동 5곳을 알려줘")

    assert result["ambiguous"] is True
    assert [choice["id"] for choice in result["choices"]] == [
        "high_risk_ratio",
        "high_risk_share",
    ]


def test_metric_resolver_accepts_explicit_within_group_ratio():
    result = resolve_metric_question("각 읍면동 전체 격자 대비 고위험 비율을 알려줘")

    assert result["ambiguous"] is False
    assert result["selected_metric_id"] == "high_risk_ratio"


def test_metric_resolver_accepts_explicit_share_of_region_high_risk_cells():
    result = resolve_metric_question("수영구 전체 고위험 격자 중 읍면동별 구성비를 알려줘")

    assert result["ambiguous"] is False
    assert result["selected_metric_id"] == "high_risk_share"
