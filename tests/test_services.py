import subprocess
import sys
from pathlib import Path

import pytest

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))

from coastal_web.services import (  # noqa: E402
    MAP_FONT_CANDIDATES,
    QueryService,
    ReportManager,
    SpatialService,
    _SelectionScopedEngine,
)


class FakeEngine:
    def run(self, sql, limit=200):
        if "DISTINCT SD_NM" in sql:
            return ["SD_NM", "SGG_NM"], [
                ("부산광역시", "수영구"),
                ("부산광역시", "해운대구"),
                ("전라남도", "여수시"),
            ]
        return ["지역", "고위험비율"], [("남천2동", 21.4)]


def test_map_font_candidates_include_the_distribution_packaged_container_font():
    assert Path(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    ) in MAP_FONT_CANDIDATES


def test_query_service_returns_regions_and_raw_query_results():
    captured = {}

    def fake_ask(question, engine):
        captured["question"] = question
        return {
            "answer": "남천2동이 21.4%로 가장 높다.",
            "queries": ["SELECT region, high_pct FROM grid"],
            "grounded": True,
        }

    service = QueryService(engine_factory=FakeEngine, ask_fn=fake_ask)

    assert service.regions()[0] == {
        "name": "부산광역시",
        "districts": ["수영구", "해운대구"],
    }
    response = service.ask(
        "고위험 비율이 가장 높은 읍면동은?",
        region="부산광역시 수영구",
        analysis_context={
            "region": "부산광역시 수영구",
            "grades": ["5"],
            "comparison_regions": ["부산광역시 해운대구"],
        },
        history=[
            {"role": "user", "content": "4·5등급 현황을 알려줘"},
            {"role": "assistant", "content": "고위험 격자를 조회했습니다."},
        ],
    )

    assert "부산광역시 수영구" in captured["question"]
    assert "최근 대화 맥락" in captured["question"]
    assert "4·5등급 현황을 알려줘" in captured["question"]
    assert "이전 답변의 수치를 재사용하지" in captured["question"]
    assert "구조화된 분석 상태" in captured["question"]
    assert "위험성지수 5등급" in captured["question"]
    assert "부산광역시 해운대구" in captured["question"]
    assert "원자료 값을 주 설명" in captured["question"]
    assert "강풍은 m/s" in captured["question"]
    assert "해수면 상승은 mm/yr" in captured["question"]
    assert "대피소는 인구 1명당 수용인원(명)" in captured["question"]
    assert "위험시설물·급경사지·침식지역은 등급(범주형)" in captured["question"]
    assert "비교 기준값" in captured["question"]
    assert "표준화 값은 보조 근거" in captured["question"]
    assert response["question"] == "고위험 비율이 가장 높은 읍면동은?"
    assert response["results"] == [
        {"columns": ["지역", "고위험비율"], "rows": [["남천2동", 21.4]]}
    ]


def test_query_service_replaces_non_finite_result_values_with_null():
    class NonFiniteEngine:
        def run(self, _sql, limit=200):
            return ["nan_value", "positive_inf", "negative_inf", "valid"], [
                (float("nan"), float("inf"), float("-inf"), 1.5),
            ]

    service = QueryService(
        engine_factory=NonFiniteEngine,
        ask_fn=lambda *_args, **_kwargs: {
            "answer": "결측 수치를 제외하고 조회했습니다.",
            "queries": ["SELECT metric FROM grid"],
            "grounded": True,
        },
    )

    result = service.ask("결측 수치를 조회해줘")

    assert result["results"] == [{
        "columns": ["nan_value", "positive_inf", "negative_inf", "valid"],
        "rows": [[None, None, None, 1.5]],
    }]


def test_query_service_closes_duckdb_engines_for_each_public_operation():
    engines = []

    class ClosableEngine:
        def __init__(self):
            self.con = self
            self.closed = False
            engines.append(self)

        def close(self):
            self.closed = True

        def run(self, sql, limit=200):
            if "_mcp_row_count" in sql:
                return ["_mcp_row_count"], [(1,)]
            if "DISTINCT SD_NM" in sql:
                return ["SD_NM", "SGG_NM"], [("부산광역시", "수영구")]
            if "duckdb_columns()" in sql:
                return ["column_name"], [
                    ("ADM_NM",),
                    ("FTR_IDN",),
                    ("위험성지수_등급",),
                ]
            if "GROUP BY region_label, grade" in sql:
                return ["region", "grade", "count", "pct"], [
                    ("부산광역시 수영구", 5, 1, 100.0),
                ]
            if "high_risk_count" in sql:
                return [
                    "region", "grid_count", "avg_grade", "high_risk_count", "high_risk_pct",
                ], [("부산광역시 수영구", 1, 5.0, 1, 100.0)]
            return ["지역", "값"], [["민락동", 1]]

    service = QueryService(
        engine_factory=ClosableEngine,
        ask_fn=lambda *_args, **_kwargs: {
            "answer": "조회했습니다.",
            "queries": ["SELECT ADM_NM AS 지역, 1 AS 값 FROM grid"],
            "grounded": True,
        },
    )

    service.regions()
    service.mcp_dataset("부산광역시 수영구")
    service.compare(["부산광역시 수영구"])
    service.ask("조회해줘", region="부산광역시 수영구")

    assert len(engines) == 4
    assert all(engine.closed for engine in engines)


def test_query_service_scopes_mcp_dataset_to_selected_grid():
    class SelectionEngine:
        def __init__(self):
            self.executed = []
            self.registered = None

        def register_selection(self, ftr_ids):
            self.registered = list(ftr_ids)
            return len(self.registered)

        def run(self, sql, limit=200):
            self.executed.append(sql)
            if "duckdb_columns()" in sql:
                return ["column_name"], [
                    ("ADM_NM",), ("FTR_IDN",), ("위험성지수_등급",), ("고령인구_원자료",),
                ]
            if "_mcp_row_count" in sql:
                return ["_mcp_row_count"], [(2,)]
            return ["지역", "고령인구 (명)"], [("민락동", 1200), ("민락동", 950)]

    engine = SelectionEngine()
    service = QueryService(
        engine_factory=lambda: engine,
        ask_fn=lambda *_args, **_kwargs: {},
    )

    result = service.mcp_dataset(
        "부산광역시 수영구",
        selection_ftr_ids=["G1", "G2"],
    )

    # 서버가 재계산한 격자 ID가 selected_grid 로 등록되고,
    # 확장 SQL은 grid 가 아니라 selected_grid 를 읽는다.
    assert engine.registered == ["G1", "G2"]
    data_sql = [sql for sql in engine.executed if "duckdb_columns()" not in sql]
    assert all("FROM selected_grid" in sql for sql in data_sql), data_sql
    assert all("FROM grid" not in sql for sql in data_sql), data_sql
    assert result["source"] == "duckdb_selected_grid"
    assert result["rows"] == [["민락동", 1200], ["민락동", 950]]


def test_query_service_builds_mcp_dataset_from_region_grid_raw_values():
    class McpDatasetEngine:
        def __init__(self):
            self.executed = []

        def run(self, sql, limit=200):
            self.executed.append((sql, limit))
            if "duckdb_columns()" in sql:
                return ["column_name"], [
                    ("ADM_NM",),
                    ("FTR_IDN",),
                    ("위험성지수_등급",),
                    ("강우_원자료",),
                    ("고령인구_원자료",),
                ]
            if "_mcp_row_count" in sql:
                return ["_mcp_row_count"], [(4321,)]
            return [
                "지역",
                "종합 위험 (등급)",
                "강우 (mm/h)",
                "고령인구 (명)",
            ], [
                ("민락동", 5, 20.5, 1200),
                ("광안동", 4, 12.1, 950),
            ]

    engine = McpDatasetEngine()
    service = QueryService(
        engine_factory=lambda: engine,
        ask_fn=lambda *_args, **_kwargs: {},
    )

    result = service.mcp_dataset(
        "부산광역시 수영구",
        focus_names=["민락동", "광안동"],
    )

    assert result["columns"] == [
        "지역",
        "종합 위험 (등급)",
        "강우 (mm/h)",
        "고령인구 (명)",
    ]
    assert result["rows"] == [
        ["민락동", 5, 20.5, 1200],
        ["광안동", 4, 12.1, 950],
    ]
    assert result["source"] == "duckdb_grid_raw"
    assert result["query"] == engine.executed[2][0]
    assert '"강우_원자료" AS "강우 (mm/h)"' in result["query"]
    assert "SD_NM = '부산광역시'" in result["query"]
    assert "SGG_NM = '수영구'" in result["query"]
    assert "ADM_NM IN ('민락동', '광안동')" in result["query"]
    assert "ORDER BY ADM_NM, FTR_IDN" in result["query"]
    assert engine.executed[1][1] == 1
    assert engine.executed[2][1] == 4321


def test_query_service_exposes_selected_and_region_scopes_without_leaking_selection_id():
    class ScopedEngine:
        def __init__(self):
            self.executed = []
            self.selected_ids = []

        def validate(self, sql):
            return sql.strip()

        def register_selection(self, ftr_ids):
            self.selected_ids = list(ftr_ids)

        def run(self, sql, limit=200):
            self.executed.append(sql)
            return ["selected_count", "region_count"], [(2, 443)]

        def schema_doc(self):
            return "table grid"

    engine = ScopedEngine()
    captured = {}

    def fake_ask(question, engine):
        captured["question"] = question
        captured["schema"] = engine.schema_doc()
        sql = (
            "SELECT (SELECT COUNT(*) FROM selected_grid) AS selected_count, "
            "(SELECT COUNT(*) FROM grid WHERE \"SGG_NM\" = '수영구') AS region_count"
        )
        engine.run(sql)
        return {
            "answer": "선택 격자는 2개이고 지역 전체는 443개입니다.",
            "queries": [engine.validate(sql)],
            "grounded": True,
        }

    service = QueryService(engine_factory=lambda: engine, ask_fn=fake_ask)
    result = service.ask(
        "선택한 영역을 지역 전체와 비교해줘",
        region="부산광역시 수영구",
        analysis_context={
            "region": "부산광역시 수영구",
            "grades": ["4", "5"],
            "comparison_regions": [],
            "selection": {"id": "selection-1", "metric": "overall", "grades": []},
            "selected_ftr_ids": ["G1", "G2"],
        },
    )

    assert result["scope"] == {
        "type": "spatial_selection",
        "selection_id": "selection-1",
        "selected_count": 2,
    }
    assert result["scope_valid"] is True
    assert result["grounded"] is True
    assert len(result["queries"]) == 1
    assert "FROM selected_grid" in result["queries"][0]
    assert "FROM grid" in result["queries"][0]
    assert "selection-1" not in captured["question"]
    assert "selection-1" not in captured["schema"]
    assert engine.selected_ids == ["G1", "G2"]


def test_selection_engine_rejects_selection_id_as_a_data_value():
    class Engine:
        def validate(self, sql):
            return sql.strip()

        def register_selection(self, _ftr_ids):
            return None

        def schema_doc(self):
            return "table grid"

    engine = _SelectionScopedEngine(Engine(), "6acd17209339", ["G1"])

    with pytest.raises(ValueError, match="선택 영역 ID"):
        engine.validate(
            "SELECT COUNT(*) FROM selected_grid "
            "WHERE \"FTR_IDN_C\" = '6acd17209339'"
        )


def test_query_service_rejects_empty_selected_feature_ids():
    service = QueryService(engine_factory=FakeEngine, ask_fn=lambda *_args, **_kwargs: {})

    with pytest.raises(ValueError, match="교차하는 격자"):
        service.ask(
            "선택한 영역을 분석해줘",
            region="부산광역시 수영구",
            analysis_context={
                "region": "부산광역시 수영구",
                "grades": [],
                "comparison_regions": [],
                "selection": {"id": "selection-1", "metric": "overall", "grades": []},
                "selected_ftr_ids": [],
            },
        )


def test_query_service_withholds_selection_comparison_when_full_scope_is_missing():
    class Engine:
        def validate(self, sql):
            return sql.strip()

        def register_selection(self, _ftr_ids):
            return None

        def run(self, _sql, limit=200):
            return ["selected_avg"], [(50.5,)]

        def schema_doc(self):
            return "table grid"

    service = QueryService(
        engine_factory=Engine,
        ask_fn=lambda *_args, **_kwargs: {
            "answer": "선택 영역 평균은 50.5명입니다.",
            "queries": ["SELECT AVG(elderly) AS selected_avg FROM selected_grid"],
            "grounded": True,
        },
    )

    result = service.ask(
        "이 영역의 고령인구 평균과 지역 전체 평균을 비교해줘",
        region="부산광역시 수영구",
        analysis_context={
            "region": "부산광역시 수영구",
            "grades": [],
            "comparison_regions": [],
            "selection": {"id": "selection-1", "metric": "overall", "grades": []},
            "selected_ftr_ids": ["G1", "G2"],
        },
    )

    assert result["scope_valid"] is False
    assert result["grounded"] is False
    assert "비교 범위를 함께 조회하지 못해" in result["answer"]


def test_query_service_withholds_unbounded_region_baseline_for_selection_comparison():
    class Engine:
        def validate(self, sql):
            return sql.strip()

        def register_selection(self, _ftr_ids):
            return None

        def run(self, _sql, limit=200):
            return ["selected_avg", "region_avg"], [(50.5, 49.9)]

        def schema_doc(self):
            return "table grid"

    service = QueryService(
        engine_factory=Engine,
        ask_fn=lambda *_args, **_kwargs: {
            "answer": "선택 영역 평균은 50.5명이고 전체 평균은 49.9명입니다.",
            "queries": [
                "SELECT "
                "(SELECT AVG(elderly) FROM selected_grid) AS selected_avg, "
                "(SELECT AVG(elderly) FROM grid) AS region_avg"
            ],
            "grounded": True,
        },
    )

    result = service.ask(
        "이 영역의 고령인구 평균과 지역 전체 평균을 비교해줘",
        region="부산광역시 수영구",
        analysis_context={
            "region": "부산광역시 수영구",
            "grades": [],
            "comparison_regions": [],
            "selection": {"id": "selection-1", "metric": "overall", "grades": []},
            "selected_ftr_ids": ["G1", "G2"],
        },
    )

    assert result["scope_valid"] is False
    assert result["grounded"] is False


def test_query_service_compares_regions_with_the_same_duckdb_metrics():
    class CompareEngine:
        def run(self, sql, limit=200):
            if "GROUP BY region_label, grade" in sql:
                return ["region", "grade", "count", "pct"], [
                    ("부산광역시 수영구", 4, 43, 9.7),
                    ("부산광역시 해운대구", 4, 50, 8.2),
                ]
            return [
                "region", "grid_count", "avg_grade", "high_risk_count", "high_risk_pct"
            ], [
                ("부산광역시 수영구", 443, 3.12, 56, 12.6),
                ("부산광역시 해운대구", 610, 3.03, 61, 10.0),
            ]

    service = QueryService(engine_factory=CompareEngine, ask_fn=lambda *_args, **_kwargs: {})

    result = service.compare(["부산광역시 수영구", "부산광역시 해운대구"])

    assert result["grounded"] is True
    assert result["summary"][0] == {
        "region": "부산광역시 수영구",
        "grid_count": 443,
        "avg_grade": 3.12,
        "high_risk_count": 56,
        "high_risk_pct": 12.6,
    }
    assert result["distribution"]["부산광역시 수영구"] == [
        {"grade": "4", "count": 43, "pct": 9.7}
    ]
    assert len(result["queries"]) == 2
    assert "수영구" in result["queries"][0]
    assert "해운대구" in result["queries"][0]


def test_query_service_ranks_subregions_by_their_own_high_risk_ratio():
    class RankingEngine:
        def run(self, sql, limit=200):
            assert "COUNT(*) FILTER" in sql
            assert "COUNT(*) AS total_count" in sql
            return ["region", "high_risk_count", "total_count", "high_risk_pct"], [
                ("남천2동", 12, 56, 21.4),
                ("민락동", 28, 172, 16.3),
            ]

    service = QueryService(engine_factory=RankingEngine, ask_fn=lambda *_args, **_kwargs: {})
    result = service.ask(
        "고위험 비율이 가장 높은 읍면동 5곳을 알려줘",
        region="부산광역시 수영구",
        analysis_context={"metric_definition": "high_risk_ratio"},
    )

    assert result["results"][0]["rows"][0] == ["남천2동", 12, 56, 21.4]
    assert result["metric_definition"]["id"] == "high_risk_ratio"
    assert "해당 읍면동 전체 격자" in result["answer"]


def test_query_service_treats_four_five_grade_ratio_as_high_risk_intent():
    class RankingEngine:
        def run(self, sql, limit=200):
            return ["region", "high_risk_count", "total_count", "high_risk_pct"], [
                ("남천2동", 12, 56, 21.4),
            ]

    called = []
    service = QueryService(
        engine_factory=RankingEngine,
        ask_fn=lambda *_args, **_kwargs: called.append(True) or {},
    )
    result = service.ask(
        "수영구에서 4·5등급 격자 비율이 가장 높은 읍면동 5곳을 알려줘",
        region="부산광역시 수영구",
        analysis_context={"metric_definition": "high_risk_ratio"},
    )

    assert called == []
    assert result["results"][0]["rows"] == [["남천2동", 12, 56, 21.4]]
    assert result["metric_definition"]["id"] == "high_risk_ratio"


def test_provenance_does_not_link_same_number_from_an_unrelated_factor():
    stats = {
        "복합지수등급분포": {
            "위해성지수": {"5": {"count": 3, "pct": 0.7}},
            "노출성지수": {"5": {"count": 383, "pct": 86.5}},
        },
        "요인별등급분포": {"급경사지": {"3등급": 0.7}},
    }
    sentence = (
        "수영구의 위해성지수는 5등급이 3개 격자, 0.7%이며, "
        "노출성지수는 5등급이 383개로 86.5%이다."
    )

    matches = ReportManager._matching_stats(sentence, stats, "복합지수 분석")

    assert {item["path"] for item in matches} == {
        "복합지수등급분포.위해성지수.5.count",
        "복합지수등급분포.위해성지수.5.pct",
        "복합지수등급분포.노출성지수.5.count",
        "복합지수등급분포.노출성지수.5.pct",
    }


def test_query_service_reports_data_quality_and_feature_readiness():
    class QualityEngine:
        def run(self, sql, limit=200):
            if "duckdb_columns()" in sql:
                return ["column_name", "data_type"], [
                    ("FTR_IDN", "VARCHAR"),
                    ("SD_NM", "VARCHAR"),
                    ("SGG_NM", "VARCHAR"),
                    ("ADM_NM", "VARCHAR"),
                    ("위험성지수_등급", "BIGINT"),
                    ("인구_원자료", "DOUBLE"),
                    ("고령인구_원자료", "DOUBLE"),
                    ("건물_원자료", "DOUBLE"),
                    ("대피소_원자료", "DOUBLE"),
                ]
            return ["column_name", "total_count", "missing_count", "invalid_count"], [
                ("FTR_IDN", 443, 0, 0),
                ("위험성지수_등급", 443, 0, 0),
                ("인구_원자료", 443, 74, 0),
            ]

    service = QueryService(engine_factory=QualityEngine, ask_fn=lambda *_args, **_kwargs: {})
    result = service.data_quality("부산광역시 수영구")

    assert result["row_count"] == 443
    assert result["columns"][2]["missing_pct"] == 16.7
    assert result["capabilities"]["spatial_impact"]["supported"] is True
    assert result["capabilities"]["time_series"]["supported"] is False
    assert "시간 컬럼" in result["capabilities"]["time_series"]["reason"]


def test_spatial_buffer_reports_population_and_asset_impact_from_raw_values():
    import geopandas as gpd
    from shapely.geometry import box

    frame = gpd.GeoDataFrame({
        "FTR_IDN": ["G1", "G2"],
        "SD_NM": ["부산광역시", "부산광역시"],
        "SGG_NM": ["수영구", "수영구"],
        "ADM_NM": ["민락동", "민락동"],
        "위험성지수_등급": [5, 4],
        "인구_원자료": [120.0, 80.0],
        "고령인구_원자료": [30.0, 20.0],
        "건물_원자료": [1000.0, 500.0],
        "대피소_원자료": [0.2, 0.4],
    }, geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs="EPSG:5179")

    class ImpactSpatialService(SpatialService):
        def _spatial_operation_frame(self, region, columns=None):
            return frame.copy()

        def _attach_raw_factor_data(self, selected):
            return selected

    service = ImpactSpatialService(gpkg_path="unused.gpkg", layer="grid")
    result = service.analyze_neighborhood(
        "부산광역시 수영구", "G1", distance_m=10, metric="overall",
    )

    assert result["stats"]["impact"] == [
        {
            "id": "population", "label": "영향권 인구", "value": 200.0,
            "unit": "명", "aggregation": "합계",
        },
        {
            "id": "elderly_population", "label": "영향권 고령인구", "value": 50.0,
            "unit": "명", "aggregation": "합계",
        },
        {
            "id": "building_area", "label": "영향권 건물면적", "value": 1500.0,
            "unit": "m²", "aggregation": "합계",
        },
        {
            "id": "shelter_capacity", "label": "대피소 수용지표", "value": 0.3,
            "unit": "인구 1명당 수용인원(명)", "aggregation": "평균",
        },
    ]
    assert "영향권 인구 200명" in result["summary"]


def test_spatial_service_compares_two_user_areas_with_same_metric():
    class ComparisonSpatialService(SpatialService):
        def analyze_selection(self, region, geometry, grades=None, metric="overall"):
            selected_count = 10 if geometry["id"] == "A" else 20
            high_risk_count = 4 if geometry["id"] == "A" else 12
            return {
                "selection_id": geometry["id"],
                "region": region,
                "metric": {"id": metric, "label": "종합 위험"},
                "grades": grades or [],
                "geometry": geometry,
                "stats": {
                    "selected_count": selected_count,
                    "average_grade": 3.2 if geometry["id"] == "A" else 4.1,
                    "high_risk_count": high_risk_count,
                    "high_risk_pct": high_risk_count * 100 / selected_count,
                },
            }

    service = ComparisonSpatialService(gpkg_path="unused.gpkg", layer="grid")

    result = service.compare_selections(
        "부산광역시 수영구",
        {"id": "A"},
        {"id": "B"},
        ["4", "5"],
        "overall",
    )

    assert result["area_a"]["stats"]["selected_count"] == 10
    assert result["area_b"]["stats"]["selected_count"] == 20
    assert result["difference"]["average_grade"] == 0.9
    assert result["difference"]["high_risk_pct_point"] == 20.0
    assert "B 영역" in result["summary"]


class FakeGraph:
    def __init__(self):
        self.initial_state = None

    def stream(self, state, stream_mode):
        self.initial_state = state
        assert stream_mode == "updates"
        yield {"ingest": {"region_label": state["region"], "errors": []}}
        yield {
            "analyze": {
                "stats": {"데이터개요": {"총 격자 수": 443}},
                "analysis_trace": {
                    "query_count": 2,
                    "queries": [{
                        "sql": (
                            'SELECT COUNT(*) AS total_count FROM grid '
                            'WHERE "SD_NM" = \'부산광역시\''
                        ),
                        "status": "ok",
                        "row_count": 1,
                    }],
                },
            }
        }
        figure_path = Path(state["figure_dir"]) / "risk_map.png"
        figure_path.write_bytes(b"png")
        yield {"visualize": {"figures": {"risk_map": str(figure_path)}}}
        yield {"verify": {"verify_passed": True, "verify_trace": {"result": "passed"}}}
        md_path = Path(state["report_dir"]) / "report.md"
        hwpx_path = Path(state["report_dir"]) / "report.hwpx"
        md_path.write_text("# 검증 보고서", encoding="utf-8")
        hwpx_path.write_bytes(b"hwpx")
        yield {"compose": {"report_md_path": str(md_path)}}
        yield {"convert": {"report_hwpx_path": str(hwpx_path)}}


def test_report_manager_uses_isolated_job_directory_and_records_events(tmp_path):
    graph = FakeGraph()
    manager = ReportManager(
        graph_factory=lambda: graph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create(
        {
            "region": "부산광역시 수영구",
            "use_llm": False,
            "use_judge": False,
            "make_hwpx": False,
        }
    )

    manager.run(created["job_id"])
    job = manager.get(created["job_id"])

    assert job["status"] == "completed"
    assert job["progress"] == 7
    assert Path(graph.initial_state["figure_dir"]).parent == tmp_path / created["job_id"]
    assert Path(graph.initial_state["report_dir"]).parent == tmp_path / created["job_id"]
    assert [event["stage"] for event in manager.events(created["job_id"])] == [
        "ingest", "analyze", "visualize", "verify", "compose", "convert", "completed"
    ]
    assert job["result"]["stats"]["데이터개요"]["총 격자 수"] == 443


def test_report_manager_namespaces_job_files_by_owner(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )

    first = manager.create({"region": None}, owner_id="user-first")
    second = manager.create({"region": None}, owner_id="user-second")

    assert Path(manager.jobs[first["job_id"]]["job_dir"]).parent == tmp_path / "user-first"
    assert Path(manager.jobs[second["job_id"]]["job_dir"]).parent == tmp_path / "user-second"


def test_report_manager_uses_queue_job_id_and_publishes_progress(tmp_path):
    updates = []
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
        on_update=lambda job: updates.append(job.copy()),
    )

    created = manager.create({"region": None}, owner_id="user-first", job_id="queued-job")
    manager.run(created["job_id"])

    assert created["job_id"] == "queued-job"
    assert updates[0]["status"] == "queued"
    assert any(update["stage"] == "analyze" for update in updates)
    assert updates[-1]["status"] == "completed"


def test_report_manager_stops_between_stages_when_cancel_is_requested(tmp_path):
    checks = iter([False, True])
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
        should_cancel=lambda _job_id: next(checks, True),
    )
    created = manager.create({"region": None}, job_id="cancel-job")

    manager.run(created["job_id"])

    assert manager.get(created["job_id"])["status"] == "cancelled"
    assert manager.events(created["job_id"])[-1]["type"] == "job_cancelled"


def test_report_manager_restores_completed_worker_job_for_download(tmp_path):
    report_dir = tmp_path / "user-first" / "job-1" / "reports"
    report_dir.mkdir(parents=True)
    report = report_dir / "report.md"
    report.write_text("# 작업 보고서", encoding="utf-8")
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )

    manager.restore({
        "job_id": "job-1",
        "user_id": "user-first",
        "status": "completed",
        "stage": "convert",
        "progress": 7,
        "options": {"region": "부산광역시 수영구"},
        "result": {"report_md_path": str(report)},
        "errors": [],
    }, materials=[])

    assert manager.file("job-1", "md").read_text(encoding="utf-8") == "# 작업 보고서"


def test_report_manager_exposes_only_job_output_files(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": None, "make_hwpx": True})
    manager.run(created["job_id"])

    md_path = manager.file(created["job_id"], "md")
    hwpx_path = manager.file(created["job_id"], "hwpx")

    assert md_path.read_text(encoding="utf-8") == "# 검증 보고서"
    assert hwpx_path.read_bytes() == b"hwpx"
    assert manager.file(created["job_id"], "pdf") is None


def test_report_manager_exposes_only_named_job_assets(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": None})
    manager.run(created["job_id"])

    asset = manager.asset(created["job_id"], "risk_map.png")

    assert asset.read_bytes() == b"png"
    assert manager.asset(created["job_id"], "../report.md") is None


def test_report_manager_inserts_selected_query_materials_before_conversion(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({
        "region": "부산광역시 수영구",
        "make_hwpx": False,
        "materials": [{
            "question": "5등급 격자는 몇 개인가?",
            "answer": "5등급 격자는 13개다.",
            "region": "부산광역시 수영구",
            "queries": ["SELECT COUNT(*) FROM grid WHERE grade = 5"],
            "results": [{"columns": ["등급", "격자수"], "rows": [[5, 13]]}],
        }],
    })

    manager.run(created["job_id"])

    markdown = manager.file(created["job_id"], "md").read_text(encoding="utf-8")
    assert "## 대화에서 선택한 추가 분석" in markdown
    assert "5등급 격자는 13개다." in markdown
    assert "SELECT COUNT(*) FROM grid WHERE grade = 5" in markdown
    assert manager.get(created["job_id"])["result"]["material_count"] == 1


def test_report_manager_copies_selected_spatial_image_into_report(tmp_path):
    spatial_root = tmp_path / "spatial"
    spatial_root.mkdir()
    (spatial_root / "map-1.png").write_bytes(b"map-png")
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path / "jobs",
        spatial_export_root=spatial_root,
        auto_start=False,
    )
    created = manager.create({
        "region": "부산광역시 수영구",
        "make_hwpx": False,
        "materials": [{
            "question": "공간분석 지도",
            "answer": "파랑 4등급 격자를 표시한 지도다.",
            "region": "부산광역시 수영구",
            "queries": [],
            "results": [],
            "spatial_image": {
                "image_id": "map-1",
                "filename": "부산광역시_수영구_파랑_4등급.png",
                "caption": "부산광역시 수영구 파랑 4등급 공간분석",
            },
        }],
    })

    manager.run(created["job_id"])

    markdown = manager.file(created["job_id"], "md").read_text(encoding="utf-8")
    copied = manager.asset(created["job_id"], "selected_map_1.png")
    assert copied is not None
    assert copied.read_bytes() == b"map-png"
    assert (
        "![부산광역시 수영구 파랑 4등급 공간분석]"
        "(../figures/selected_map_1.png)"
    ) in markdown
    assert manager.get(created["job_id"])["result"]["material_images"] == {
        "부산광역시 수영구 파랑 4등급 공간분석": str(copied)
    }


def test_report_manager_copies_selected_mcp_chart_into_owned_report(tmp_path):
    mcp_root = tmp_path / "mcp"
    analysis_id = "a" * 32
    chart_dir = mcp_root / "user-1" / analysis_id
    chart_dir.mkdir(parents=True)
    (chart_dir / "correlation_heatmap.png").write_bytes(b"mcp-chart")
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path / "jobs",
        mcp_output_root=mcp_root,
        auto_start=False,
    )
    created = manager.create(
        {
            "region": "부산광역시 수영구",
            "make_hwpx": False,
            "materials": [{
                "question": "고위험 격자의 상관관계를 분석해줘",
                "answer": (
                    "실제 데이터 213행을 분석했다. "
                    "강풍과 침수면적의 상관계수는 0.62이다."
                ),
                "region": "부산광역시 수영구",
                "grounded": True,
                "queries": ["SELECT raw factors FROM grid"],
                "results": [{
                    "columns": ["근거 항목", "값"],
                    "rows": [["분석 행 수", 213], ["상관계수", 0.62]],
                }],
                "mcp_chart": {
                    "analysis_id": analysis_id,
                    "asset_name": "correlation_heatmap.png",
                    "caption": "고위험 격자 원자료 상관관계",
                    "chart": "correlation_heatmap",
                },
            }],
        },
        owner_id="user-1",
    )

    manager.run(created["job_id"])

    markdown = manager.file(created["job_id"], "md").read_text(encoding="utf-8")
    copied = manager.asset(created["job_id"], "selected_mcp_1.png")
    assert copied is not None
    assert copied.read_bytes() == b"mcp-chart"
    assert "강풍과 침수면적의 상관계수는 0.62이다." in markdown
    assert (
        "![고위험 격자 원자료 상관관계]"
        "(../figures/selected_mcp_1.png)"
    ) in markdown
    assert manager.get(created["job_id"])["result"]["material_images"] == {
        "고위험 격자 원자료 상관관계": str(copied)
    }


def test_report_manager_rebuilds_hwpx_with_selected_spatial_images(tmp_path, monkeypatch):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path / "jobs",
        auto_start=False,
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    markdown = report_dir / "report.md"
    hwpx = report_dir / "report.hwpx"
    image = tmp_path / "selected_map_1.png"
    markdown.write_text("![선택 지도](../figures/selected_map_1.png)", encoding="utf-8")
    hwpx.write_bytes(b"existing-hwpx")
    image.write_bytes(b"png")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    hwpx_images = pytest.importorskip(
        "coastal_agent.hwpx_images",
        reason="The external report engine is not bundled with this public source extract",
    )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        hwpx_images,
        "embed_images",
        lambda path, images: captured.update({"path": path, "images": images}) or [],
    )
    record = {
        "result": {
            "report_md_path": str(markdown),
            "report_hwpx_path": str(hwpx),
            "figures": {},
            "material_images": {"선택 지도": str(image)},
        },
        "errors": [],
    }

    manager._rebuild_hwpx_with_material_images(record)

    assert captured["command"][2:] == [str(markdown), str(hwpx), captured["command"][4]]
    assert captured["path"] == hwpx
    assert captured["images"] == {"선택 지도": image}


def test_report_manager_saves_a_grounded_section_revision_as_a_new_version(tmp_path):
    def rewrite(section, current, instruction, evidence):
        assert section == "정책 제언"
        assert "정책 제언" in current
        assert "간결하게" in instruction
        assert evidence["stats"]["데이터개요"]["총 격자 수"] == 443
        return "수정된 정책 제언이다."

    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
        revision_fn=rewrite,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    original = manager.file(created["job_id"], "md")
    original.write_text(
        "# 보고서\n\n## 6. 결론 및 제언\n\n### 6.2 정책 제언\n\n기존 정책 제언이다.\n",
        encoding="utf-8",
    )

    revision = manager.revise(created["job_id"], "정책 제언", "간결하게 수정해줘")

    latest = manager.file(created["job_id"], "md")
    assert latest != original
    assert original.read_text(encoding="utf-8").endswith("기존 정책 제언이다.\n")
    assert "수정된 정책 제언이다." in latest.read_text(encoding="utf-8")
    assert revision["revision"] == 1
    assert manager.get(created["job_id"])["result"]["revision_count"] == 1


def test_report_manager_saves_direct_markdown_edit_as_a_new_version(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    original = manager.file(created["job_id"], "md")
    original.write_text("# 보고서\n\n기존 설명이다.\n", encoding="utf-8")

    revision = manager.save_content(
        created["job_id"],
        "# 보고서\n\n웹에서 직접 다듬은 설명이다.\n",
    )

    latest = manager.file(created["job_id"], "md")
    assert latest != original
    assert latest.name.endswith("_v2.md")
    assert original.read_text(encoding="utf-8") == "# 보고서\n\n기존 설명이다.\n"
    assert latest.read_text(encoding="utf-8") == "# 보고서\n\n웹에서 직접 다듬은 설명이다.\n"
    assert revision["mode"] == "direct_edit"
    assert manager.get(created["job_id"])["result"]["revision_count"] == 1


def test_report_manager_runs_direct_edit_with_progress_updates(tmp_path):
    updates = []
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
        on_update=lambda update: updates.append(update),
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    updates.clear()

    result = manager.run_edit(
        created["job_id"],
        "content",
        {"markdown": "# 보고서\n\n비동기로 직접 다듬은 설명이다.\n"},
    )

    assert result["mode"] == "direct_edit"
    assert updates[0]["status"] == "running"
    assert updates[0]["stage"] == "revision"
    assert updates[-1]["status"] == "completed"
    assert updates[-1]["result"]["revision_count"] == 1


def test_report_manager_rejects_new_unsupported_number_in_direct_edit(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    current = manager.file(created["job_id"], "md").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="근거 없는 수치: 999999"):
        manager.save_content(created["job_id"], current + "\n근거 없는 값은 999999이다.\n")


def test_report_manager_traces_a_sentence_to_stats_sql_rows_and_gpkg_fields(tmp_path):
    class EvidenceEngine:
        def run(self, sql, limit=200):
            assert "COUNT(*)" in sql
            assert limit == 20
            return ["total_count"], [(443,)]

    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
        query_engine_factory=EvidenceEngine,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"]["주요요인원자료"] = {
        "강풍": {"유효격자수": 443}
    }
    report = manager.file(created["job_id"], "md")
    report.write_text(
        "# 보고서\n\n평가 대상 격자는 총 443개이다. 기후변화 대응이 필요하다.\n",
        encoding="utf-8",
    )

    entries = manager.provenance(created["job_id"])
    grounded = next(item for item in entries if "443개" in item["sentence"])
    general = next(item for item in entries if "기후변화" in item["sentence"])
    detail = manager.provenance(created["job_id"], grounded["id"])

    assert grounded["grounded"] is True
    assert grounded["stats"] == [{"path": "데이터개요.총 격자 수", "value": 443}]
    assert grounded["gpkg_fields"] == ["FTR_IDN", "SD_NM"]
    assert general["grounded"] is False
    assert detail["queries"][0]["columns"] == ["total_count"]
    assert detail["queries"][0]["rows"] == [[443]]


def test_report_manager_does_not_attach_statistics_or_sql_to_metadata_and_general_text(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    record = manager.jobs[created["job_id"]]
    record["result"]["stats"]["요인별등급분포"] = {"고령인구": {"3등급": 14}}
    record["result"]["analysis_trace"]["queries"].append({
        "sql": "SELECT '고령인구' AS factor, 14 AS grade_count FROM grid",
        "status": "ok",
        "row_count": 1,
    })
    manager.file(created["job_id"], "md").write_text(
        (
            "# 보고서\n\n**작성일:** 2026-07-14\n\n1.\n\n"
            "- 1.1 배경 및 목적\n\n평가 체계는 1~5등급이다.\n\n"
            "고령인구 요인은 별도로 검토한다.\n"
        ),
        encoding="utf-8",
    )

    entries = manager.provenance(created["job_id"])

    assert not any("작성일" in item["sentence"] for item in entries)
    assert not any(item["sentence"] == "1." for item in entries)
    assert not any(item["sentence"].startswith("- 1.1") for item in entries)
    scale = next(item for item in entries if "1~5등급" in item["sentence"])
    assert scale["grounded"] is False
    general = next(item for item in entries if "고령인구 요인" in item["sentence"])
    assert general["grounded"] is False
    assert general["queries"] == []


def test_report_manager_uses_the_section_heading_to_disambiguate_equal_values(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "위험성등급분포": {
            "1": {"count": 3, "pct": 0.7},
            "2": {"count": 9, "pct": 2.0},
        },
        "요인별등급분포": {"급경사지": {"3등급": 0.7}},
    }
    manager.file(created["job_id"], "md").write_text(
        (
            "# 보고서\n\n## 3. 위험성지수 등급 분포\n\n"
            "1등급은 3개(0.7%)이다.\n\n2등급은 9개(2.0%)이다.\n"
        ),
        encoding="utf-8",
    )

    entries = manager.provenance(created["job_id"])

    assert entries[0]["stats"] == [
        {"path": "위험성등급분포.1.count", "value": 3},
        {"path": "위험성등급분포.1.pct", "value": 0.7},
    ]
    assert entries[1]["stats"] == [
        {"path": "위험성등급분포.2.count", "value": 9},
        {"path": "위험성등급분포.2.pct", "value": 2.0},
    ]


def test_report_manager_traces_a_derived_high_risk_percentage(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "위험성등급분포": {
            "4": {"pct": 9.7},
            "5": {"pct": 2.9},
        },
    }
    manager.file(created["job_id"], "md").write_text(
        "# 보고서\n\n고위험(4~5등급) 비율은 12.6%이다.\n",
        encoding="utf-8",
    )

    entry = manager.provenance(created["job_id"])[0]

    assert entry["grounded"] is True
    assert entry["stats"] == [{
        "path": "위험성등급분포.4.pct + 위험성등급분포.5.pct",
        "value": 12.6,
    }]


def test_report_manager_exposes_map_filters_for_a_grounded_sentence(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "시군구별순위": {"남천2동": {"고위험비율(%)": 21.4}},
    }
    manager.file(created["job_id"], "md").write_text(
        "# 보고서\n\n남천2동의 5등급 고위험 비율은 21.4%이다.\n",
        encoding="utf-8",
    )

    entry = manager.provenance(created["job_id"])[0]

    assert entry["map_context"] == {
        "region": "부산광역시 수영구",
        "adm_names": ["남천2동"],
        "grades": ["5"],
        "metric_id": "overall",
    }


def test_report_manager_does_not_treat_sentence_endings_as_admin_names(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "위험성등급분포": {"5": {"pct": 21.4}},
    }
    manager.file(created["job_id"], "md").write_text(
        "# 보고서\n\n등급분포에 따르면 해수면 위험의 5등급 비율은 21.4%이다.\n",
        encoding="utf-8",
    )

    entry = manager.provenance(created["job_id"])[0]

    assert entry["map_context"]["adm_names"] == []


def test_report_manager_links_composite_metric_to_map_context(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "노출성등급분포": {"4": {"pct": 18.2}},
    }
    manager.file(created["job_id"], "md").write_text(
        "# 보고서\n\n노출성지수 4등급 비율은 18.2%이다.\n",
        encoding="utf-8",
    )

    entry = manager.provenance(created["job_id"])[0]

    assert entry["map_context"]["metric_id"] == "exposure"


def test_report_manager_exposes_actual_vulnerability_gpkg_field(tmp_path):
    manager = ReportManager(
        graph_factory=FakeGraph,
        output_root=tmp_path,
        auto_start=False,
    )
    created = manager.create({"region": "부산광역시 수영구", "make_hwpx": False})
    manager.run(created["job_id"])
    manager.jobs[created["job_id"]]["result"]["stats"] = {
        "취약성지수(가중)등급분포": {"5": {"pct": 7.1}},
    }
    manager.file(created["job_id"], "md").write_text(
        "# 보고서\n\n취약성지수(가중) 5등급 비율은 7.1%이다.\n",
        encoding="utf-8",
    )

    entry = manager.provenance(created["job_id"])[0]

    assert "취약성지수(가중)_등급" in entry["gpkg_fields"]
