from pathlib import Path

import geopandas as gpd
from coastal_web.services import SpatialService
from shapely.geometry import box


def _service(tmp_path: Path) -> SpatialService:
    path = tmp_path / "spatial-operations.gpkg"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["A", "B", "C", "D"],
            "SD_NM": ["부산광역시"] * 4,
            "SGG_NM": ["수영구"] * 4,
            "ADM_NM": ["민락동", "민락동", "광안동", "광안동"],
            "위험성지수_등급": ["5", "4", "5", "2"],
            "위해성지수_등급": ["5", "4", "5", "2"],
            "노출성지수_등급": ["5", "4", "4", "2"],
            "취약성지수(가중)_등급": ["5", "3", "4", "2"],
            "취약성지수(저감)_등급": ["4", "3", "4", "2"],
            "강풍_등급": ["5", "4", "5", "2"],
            "고령인구_등급": ["5", "3", "4", "2"],
            "강풍_원자료": [30.0, 22.0, 28.0, 10.0],
            "고령인구_원자료": [120.0, 80.0, 150.0, 20.0],
        },
        geometry=[
            box(0, 0, 100, 100),
            box(100, 0, 200, 100),
            box(400, 0, 500, 100),
            box(500, 0, 600, 100),
        ],
        crs="EPSG:3857",
    )
    frame.to_file(path, layer="grid", driver="GPKG")
    return SpatialService(gpkg_path=path, layer="grid")


def test_natural_spatial_filter_combines_metric_grade_conditions(tmp_path):
    result = _service(tmp_path).filter_from_question(
        "부산광역시 수영구",
        "강풍 4·5등급이면서 고령인구 4·5등급인 격자를 찾아줘",
    )

    assert result["operation"] == "filter"
    assert result["stats"]["feature_count"] == 2
    assert {
        feature["properties"]["FTR_IDN"] for feature in result["feature_collection"]["features"]
    } == {"A", "C"}
    assert result["conditions"] == [
        {"metric_id": "강풍", "label": "강풍", "grade_column": "강풍_등급", "grades": ["4", "5"]},
        {
            "metric_id": "고령인구",
            "label": "고령인구",
            "grade_column": "고령인구_등급",
            "grades": ["4", "5"],
        },
    ]


def test_selected_grid_buffer_and_adjacency_return_real_neighbors(tmp_path):
    service = _service(tmp_path)

    buffered = service.analyze_neighborhood(
        "부산광역시 수영구", "A", distance_m=20, metric="overall", grades=[]
    )
    adjacent = service.analyze_neighborhood(
        "부산광역시 수영구", "A", distance_m=0, metric="overall", grades=[]
    )

    assert buffered["operation"] == "buffer"
    assert buffered["stats"]["feature_count"] == 2
    assert adjacent["operation"] == "adjacent"
    assert {
        feature["properties"]["FTR_IDN"] for feature in adjacent["feature_collection"]["features"]
    } == {"A", "B"}
    assert adjacent["source_ftr_id"] == "A"


def test_hotspot_analysis_groups_touching_high_risk_grids(tmp_path):
    result = _service(tmp_path).analyze_hotspots(
        "부산광역시 수영구", metric="overall", grades=["4", "5"], min_cluster_size=2
    )

    assert result["operation"] == "hotspot"
    assert result["stats"]["cluster_count"] == 1
    assert result["stats"]["feature_count"] == 2
    assert {
        feature["properties"]["cluster_id"] for feature in result["feature_collection"]["features"]
    } == {1}
    assert {
        feature["properties"]["FTR_IDN"] for feature in result["feature_collection"]["features"]
    } == {"A", "B"}


def test_feature_explanation_is_scoped_to_the_clicked_grid(tmp_path):
    result = _service(tmp_path).analyze_feature("부산광역시 수영구", "A", "overall")

    assert result["stats"]["selected_count"] == 1
    assert result["selected_ftr_ids"] == ["A"]
    assert result["feature_collection"]["features"][0]["properties"]["FTR_IDN"] == "A"


def test_sql_scope_layer_uses_only_allowed_spatial_predicates(tmp_path):
    result = _service(tmp_path).scope_from_queries(
        "부산광역시 수영구",
        [
            "SELECT ADM_NM, COUNT(*) FROM grid WHERE \"ADM_NM\" = '민락동' "
            'AND "위험성지수_등급" IN (4, 5) GROUP BY ADM_NM'
        ],
    )

    assert result["operation"] == "query_scope"
    assert result["stats"]["feature_count"] == 2
    assert result["evidence"]["queries"][0].startswith("SELECT ADM_NM")
    assert {
        feature["properties"]["FTR_IDN"] for feature in result["feature_collection"]["features"]
    } == {"A", "B"}


def test_sql_scope_layer_supports_multiple_places_and_single_grade(tmp_path):
    result = _service(tmp_path).scope_from_queries(
        "부산광역시 수영구",
        ["SELECT * FROM grid WHERE \"ADM_NM\" IN ('민락동', '광안동') AND \"위험성지수_등급\" = 5"],
    )

    assert result["stats"]["feature_count"] == 2
    assert {
        feature["properties"]["FTR_IDN"] for feature in result["feature_collection"]["features"]
    } == {"A", "C"}


def test_sql_scope_layer_unions_the_ranges_of_separate_queries(tmp_path):
    result = _service(tmp_path).scope_from_queries(
        "부산광역시 수영구",
        [
            'SELECT * FROM grid WHERE "ADM_NM" = \'민락동\' AND "위험성지수_등급" = 5',
            'SELECT * FROM grid WHERE "ADM_NM" = \'광안동\' AND "위험성지수_등급" = 2',
        ],
    )

    assert {
        feature["properties"]["FTR_IDN"] for feature in result["feature_collection"]["features"]
    } == {"A", "D"}
