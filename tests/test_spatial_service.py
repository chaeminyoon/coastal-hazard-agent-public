import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))

from coastal_web.services import SpatialService  # noqa: E402


def test_spatial_service_filters_region_and_grade_and_returns_wgs84(tmp_path):
    path = tmp_path / "risk.gpkg"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2", "G3"],
            "SD_NM": ["부산광역시", "부산광역시", "전라남도"],
            "SGG_NM": ["수영구", "수영구", "여수시"],
            "ADM_NM": ["광안동", "남천동", "돌산읍"],
            "강풍_등급": ["5", "4", "1"],
            "강우_등급": ["3", "2", "1"],
            "위해성지수_등급": ["4", "3", "2"],
            "노출성지수_등급": ["5", "2", "1"],
            "취약성지수(가중)_등급": ["3", "2", "1"],
            "위험성지수_등급": ["5", "2", "1"],
        },
        geometry=[
            box(1120000, 1680000, 1120100, 1680100),
            box(1120200, 1680000, 1120300, 1680100),
            box(1000000, 1600000, 1000100, 1600100),
        ],
        crs="EPSG:5179",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk")

    metadata = service.metadata("부산광역시 수영구")
    features = service.features("부산광역시 수영구", grades=["5"])
    focused = service.features("부산광역시 수영구", focus_names=["남천동"])

    assert metadata["feature_count"] == 2
    assert metadata["grade_counts"] == {"2": 1, "5": 1}
    assert len(features["features"]) == 1
    assert features["features"][0]["properties"]["FTR_IDN"] == "G1"
    assert len(focused["features"]) == 1
    assert focused["features"][0]["properties"]["FTR_IDN"] == "G2"
    x, y = features["features"][0]["geometry"]["coordinates"][0][0]
    assert 120 < x < 140
    assert 30 < y < 40


def test_spatial_service_uses_selected_factor_grade_for_counts_and_filter(tmp_path):
    path = tmp_path / "risk.gpkg"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2"],
            "SD_NM": ["부산광역시", "부산광역시"],
            "SGG_NM": ["수영구", "수영구"],
            "ADM_NM": ["광안동", "남천동"],
            "강풍_등급": ["5", "4"],
            "위험성지수_등급": ["5", "2"],
        },
        geometry=[
            box(1120000, 1680000, 1120100, 1680100),
            box(1120200, 1680000, 1120300, 1680100),
        ],
        crs="EPSG:5179",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk")

    metadata = service.metadata("부산광역시 수영구")
    features = service.features(
        "부산광역시 수영구",
        grades=["4"],
        metric="강풍",
    )

    wind = next(metric for metric in metadata["metrics"] if metric["id"] == "강풍")
    assert wind["grade_column"] == "강풍_등급"
    assert wind["grade_counts"] == {"4": 1, "5": 1}
    assert [feature["properties"]["FTR_IDN"] for feature in features["features"]] == ["G2"]
    assert features["features"][0]["properties"]["강풍_등급"] == "4"
    assert features["metadata"]["metric"] == {
        "id": "강풍",
        "label": "강풍",
        "group": "위해성",
        "grade_column": "강풍_등급",
    }


def test_spatial_service_exports_the_selected_factor_map_as_png(tmp_path):
    path = tmp_path / "risk.gpkg"
    export_root = tmp_path / "exports"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2"],
            "SD_NM": ["부산광역시", "부산광역시"],
            "SGG_NM": ["수영구", "수영구"],
            "ADM_NM": ["광안동", "남천동"],
            "파랑_등급": ["4", "2"],
            "위험성지수_등급": ["2", "5"],
        },
        geometry=[
            box(1120000, 1680000, 1120100, 1680100),
            box(1120200, 1680000, 1120300, 1680100),
        ],
        crs="EPSG:5179",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk", export_root=export_root)

    exported = service.export_map(
        "부산광역시 수영구",
        metric="파랑",
        grades=["4"],
    )

    image = service.export_asset(exported["image_id"])
    assert image is not None
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert exported["metric"] == "파랑"
    assert exported["grades"] == ["4"]
    assert exported["feature_count"] == 1
    assert exported["caption"] == "부산광역시 수영구 파랑 4등급 공간분석"


def test_spatial_service_exports_a_transparent_selected_area(tmp_path):
    path = tmp_path / "risk.gpkg"
    export_root = tmp_path / "exports"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2"],
            "SD_NM": ["부산광역시", "부산광역시"],
            "SGG_NM": ["수영구", "수영구"],
            "ADM_NM": ["광안동", "남천동"],
            "위험성지수_등급": ["5", "2"],
        },
        geometry=[
            box(129.10, 35.10, 129.11, 35.11),
            box(129.20, 35.20, 129.21, 35.21),
        ],
        crs="EPSG:4326",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk", export_root=export_root)
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [129.09, 35.09], [129.12, 35.09], [129.12, 35.12],
            [129.09, 35.12], [129.09, 35.09],
        ]],
    }

    exported = service.export_map(
        "부산광역시 수영구",
        background="transparent",
        extent="selection",
        geometry=geometry,
    )

    assert exported["feature_count"] == 1
    assert exported["background"] == "transparent"
    assert exported["extent"] == "selection"
    assert exported["caption"].endswith("선택격자 · 투명 배경")


def test_spatial_export_is_namespaced_by_owner(tmp_path):
    path = tmp_path / "risk.gpkg"
    export_root = tmp_path / "exports"
    frame = gpd.GeoDataFrame(
        {
            "SD_NM": ["부산광역시"],
            "SGG_NM": ["수영구"],
            "ADM_NM": ["광안동"],
            "위험성지수_등급": ["5"],
        },
        geometry=[box(1120000, 1680000, 1120100, 1680100)],
        crs="EPSG:5179",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk", export_root=export_root)

    exported = service.export_map("부산광역시 수영구", owner_id="user-first")

    assert service.export_asset(exported["image_id"], owner_id="user-first") is not None
    assert service.export_asset(exported["image_id"], owner_id="user-second") is None


def test_spatial_service_imports_a_shapefile_bundle_as_wgs84_annotation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    frame = gpd.GeoDataFrame(
        {"지역명": ["광안동"], "코드": ["261401"]},
        geometry=[box(1120000, 1680000, 1120100, 1680100)],
        crs="EPSG:5179",
    )
    path = source / "district.shp"
    frame.to_file(path, encoding="utf-8")
    files = [(item.name, item.read_bytes()) for item in source.glob("district.*")]
    annotation_root = tmp_path / "annotations"
    service = SpatialService(
        gpkg_path=path,
        layer="district",
        annotation_root=annotation_root,
    )

    imported = service.import_annotation(files, owner_id="user-first")

    assert imported["name"] == "district"
    assert imported["feature_count"] == 1
    assert imported["columns"] == ["지역명", "코드"]
    assert imported["suggested_label_field"] == "지역명"
    assert imported["geojson"]["features"][0]["properties"]["지역명"] == "광안동"
    x, y = imported["geojson"]["features"][0]["geometry"]["coordinates"][0][0]
    assert 120 < x < 140
    assert 30 < y < 40
    assert any((annotation_root / "user-first").rglob("district.shp"))


def test_spatial_service_imports_a_zipped_shapefile_annotation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    frame = gpd.GeoDataFrame(
        {"NAME": ["수영구"]},
        geometry=[box(1120000, 1680000, 1120100, 1680100)],
        crs="EPSG:5179",
    )
    path = source / "boundary.shp"
    frame.to_file(path, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for item in source.glob("boundary.*"):
            archive.writestr(item.name, item.read_bytes())
    service = SpatialService(
        gpkg_path=path,
        layer="boundary",
        annotation_root=tmp_path / "annotations",
    )

    imported = service.import_annotation([("boundary.zip", buffer.getvalue())])

    assert imported["feature_count"] == 1
    assert imported["suggested_label_field"] == "NAME"


def test_spatial_service_analyzes_custom_area_and_composite_overlap(tmp_path):
    path = tmp_path / "risk.gpkg"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2", "G3"],
            "SD_NM": ["부산광역시"] * 3,
            "SGG_NM": ["수영구"] * 3,
            "ADM_NM": ["광안동", "남천동", "민락동"],
            "강풍_원자료": [30.0, 20.0, 5.0],
            "강풍_등급": ["5", "4", "1"],
            "인구_원자료": [100.0, 50.0, 10.0],
            "인구_등급": ["5", "3", "1"],
            "위해성지수_등급": ["4", "5", "1"],
            "노출성지수_등급": ["2", "4", "1"],
            "취약성지수(가중)_등급": ["5", "2", "1"],
            "위험성지수_등급": ["5", "3", "1"],
        },
        geometry=[
            box(129.10, 35.10, 129.11, 35.11),
            box(129.12, 35.10, 129.13, 35.11),
            box(129.20, 35.20, 129.21, 35.21),
        ],
        crs="EPSG:4326",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk")
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [129.09, 35.09], [129.14, 35.09], [129.14, 35.12],
            [129.09, 35.12], [129.09, 35.09],
        ]],
    }

    result = service.analyze_selection(
        "부산광역시 수영구",
        geometry,
        metric="overall",
    )

    assert result["stats"] == {
        "selected_count": 2,
        "average_grade": 4.0,
        "high_risk_count": 1,
        "high_risk_pct": 50.0,
        "grade_counts": {"3": 1, "5": 1},
    }
    assert [item["metric_id"] for item in result["overlaps"]] == [
        "overall", "hazard", "exposure", "sensitivity",
    ]
    assert result["overlaps"][1]["high_risk_count"] == 2
    assert [
        feature["properties"]["FTR_IDN"]
        for feature in result["feature_collection"]["features"]
    ] == ["G1", "G2"]
    assert result["selected_ftr_ids"] == ["G1", "G2"]
    assert result["grades"] == []
    assert result["feature_collection"]["metadata"]["truncated"] is False
    assert result["analysis"]["drivers"][0] == {
        "factor": "강풍",
        "group": "위해성",
        "unit": "m/s",
        "selected_mean": 25.0,
        "region_mean": 18.33,
        "selected_high_risk_pct": 100.0,
        "region_high_risk_pct": 66.7,
        "difference_pct_point": 33.3,
        "high_risk_range": [20.0, 30.0],
    }
    assert "강풍 원자료 평균 25.00m/s" in result["analysis"]["narrative"]
    assert "지역 전체 평균 18.33m/s" in result["analysis"]["narrative"]
    assert result["report_material"]["results"][0]["columns"] == ["지표", "값", "단위"]


def test_spatial_service_joins_selected_gpkg_ids_to_duckdb_raw_values(tmp_path):
    path = tmp_path / "risk.gpkg"
    parquet_path = tmp_path / "main_eval.parquet"
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": ["G1", "G2", "G3"],
            "SD_NM": ["부산광역시"] * 3,
            "SGG_NM": ["수영구"] * 3,
            "ADM_NM": ["광안동", "남천동", "민락동"],
            "강풍_등급": ["5", "4", "1"],
            "위험성지수_등급": ["5", "3", "1"],
        },
        geometry=[
            box(129.10, 35.10, 129.11, 35.11),
            box(129.12, 35.10, 129.13, 35.11),
            box(129.20, 35.20, 129.21, 35.21),
        ],
        crs="EPSG:4326",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    pd.DataFrame({
        "FTR_IDN": ["G1", "G2", "G3"],
        "SD_NM": ["부산광역시"] * 3,
        "SGG_NM": ["수영구"] * 3,
        "강풍_원자료": [30.0, 20.0, 5.0],
        "강풍_등급": ["5", "4", "1"],
    }).to_parquet(parquet_path)
    service = SpatialService(
        gpkg_path=path,
        layer="risk",
        parquet_path=parquet_path,
    )
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [129.09, 35.09], [129.14, 35.09], [129.14, 35.12],
            [129.09, 35.12], [129.09, 35.09],
        ]],
    }

    result = service.analyze_selection("부산광역시 수영구", geometry)

    assert result["analysis"]["drivers"][0]["factor"] == "강풍"
    assert result["analysis"]["drivers"][0]["selected_mean"] == 25.0
    assert result["analysis"]["drivers"][0]["region_mean"] == 18.33
    assert len(result["report_material"]["queries"]) == 2


def test_spatial_service_samples_evenly_when_over_display_limit(tmp_path):
    path = tmp_path / "risk.gpkg"
    count = 12
    frame = gpd.GeoDataFrame(
        {
            "FTR_IDN": [f"G{i:02d}" for i in range(count)],
            "SD_NM": ["강원특별자치도"] * count,
            "SGG_NM": ["강릉시"] * count,
            # 파일 순서 뒤쪽 절반이 초당동 — 앞에서 자르면 통째로 사라지는 배치
            "ADM_NM": ["경포동"] * (count // 2) + ["초당동"] * (count // 2),
            "위험성지수_등급": ["3"] * count,
        },
        geometry=[
            box(1120000 + i * 200, 1680000, 1120100 + i * 200, 1680100)
            for i in range(count)
        ],
        crs="EPSG:5179",
    )
    frame.to_file(path, layer="risk", driver="GPKG")
    service = SpatialService(gpkg_path=path, layer="risk")

    result = service.features("강원특별자치도 강릉시", limit=4)

    assert result["metadata"]["truncated"] is True
    assert len(result["features"]) <= 4
    shown_adm = {f["properties"]["ADM_NM"] for f in result["features"]}
    # 앞쪽 절단이었다면 경포동만 남는다 — 균등 표본은 두 동 모두 포함해야 한다
    assert shown_adm == {"경포동", "초당동"}
