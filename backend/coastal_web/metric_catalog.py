from __future__ import annotations

_DEFINITIONS = (
    {
        "id": "high_risk_ratio",
        "label": "고위험 비율",
        "description": "각 집단 안에서 4·5등급 격자가 차지하는 비율",
        "numerator": "해당 집단의 4·5등급 격자 수",
        "denominator": "해당 집단의 전체 유효 격자 수",
        "unit": "%",
        "sql": (
            'COUNT(*) FILTER (WHERE TRY_CAST("위험성지수_등급" AS INTEGER) IN (4, 5)) '
            '* 100.0 / NULLIF(COUNT(*), 0)'
        ),
    },
    {
        "id": "high_risk_share",
        "label": "전체 고위험 구성비",
        "description": "상위 지역의 모든 고위험 격자 중 각 집단이 차지하는 비중",
        "numerator": "해당 집단의 4·5등급 격자 수",
        "denominator": "상위 지역 전체의 4·5등급 격자 수",
        "unit": "%",
        "sql": (
            "집단별 고위험 격자 수 * 100.0 / "
            "NULLIF(SUM(집단별 고위험 격자 수) OVER (), 0)"
        ),
    },
    {
        "id": "average_risk_grade",
        "label": "평균 위험도",
        "description": "유효한 종합 위험 등급의 산술평균",
        "numerator": "유효한 위험성지수 등급의 합",
        "denominator": "위험성지수 등급이 있는 격자 수",
        "unit": "등급",
        "sql": 'AVG(TRY_CAST("위험성지수_등급" AS DOUBLE))',
    },
    {
        "id": "high_risk_concentration",
        "label": "고위험 집중도",
        "description": "하위 집단의 고위험 비율이 상위 지역 평균의 몇 배인지 나타내는 값",
        "numerator": "해당 집단의 고위험 비율",
        "denominator": "상위 지역 전체의 고위험 비율",
        "unit": "배",
        "sql": "집단 고위험 비율 / NULLIF(상위 지역 고위험 비율, 0)",
    },
)


def metric_definitions() -> list[dict]:
    return [dict(item) for item in _DEFINITIONS]


def metric_definition(metric_id: str) -> dict | None:
    return next((dict(item) for item in _DEFINITIONS if item["id"] == metric_id), None)


def resolve_metric_question(question: str) -> dict:
    compact = "".join(str(question).split())
    definitions = {item["id"]: item for item in metric_definitions()}
    if "고위험" in compact and any(
        token in compact for token in ("구성비", "차지하는비중", "전체고위험중")
    ):
        return {
            "ambiguous": False,
            "selected_metric_id": "high_risk_share",
            "choices": [],
        }
    if "고위험" not in compact or "비율" not in compact:
        return {"ambiguous": False, "selected_metric_id": None, "choices": []}
    if any(token in compact for token in ("전체격자대비", "자체대비", "해당지역전체")):
        return {
            "ambiguous": False,
            "selected_metric_id": "high_risk_ratio",
            "choices": [],
        }
    if any(token in compact for token in ("읍면동", "동별", "지역별", "시군구별")):
        return {
            "ambiguous": True,
            "selected_metric_id": None,
            "question": "어떤 기준의 고위험 비율을 계산할까요?",
            "choices": [
                definitions["high_risk_ratio"],
                definitions["high_risk_share"],
            ],
        }
    return {
        "ambiguous": False,
        "selected_metric_id": "high_risk_ratio",
        "choices": [],
    }
