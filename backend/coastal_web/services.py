import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .metric_catalog import metric_definition

WEB_ROOT = Path(__file__).resolve().parents[2]
SPATIAL_EXPORT_ROOT = WEB_ROOT / "outputs" / "spatial_maps"
MCP_OUTPUT_ROOT = WEB_ROOT / "outputs" / "mcp"
SPATIAL_ANNOTATION_ROOT = WEB_ROOT / "outputs" / "annotations"
DEFAULT_AGENT_ROOT = WEB_ROOT.parent / "analysis-engine"
STAGES = ["ingest", "analyze", "visualize", "narrate", "verify", "compose", "convert"]
MAP_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/PretendardGOV-Regular.otf"),
    Path("/usr/local/share/fonts/truetype/pretendard-gov/PretendardGOV-Regular.otf"),
    Path("/usr/local/share/fonts/PretendardGOV-Regular.otf"),
    Path("/usr/share/fonts/truetype/pretendard/PretendardGOV-Regular.otf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
)
PUBLIC_KEYS = {
    "region_label",
    "stats",
    "analysis_trace",
    "figures",
    "narratives",
    "narrative_source",
    "narrate_attempts",
    "verify_passed",
    "verify_trace",
    "report_md_path",
    "report_hwpx_path",
    "errors",
}


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


SPATIAL_FACTOR_GROUPS = {
    "위해성": ["강풍", "강우", "해일", "파랑", "해수면 상승"],
    "노출성": [
        "인구", "건물", "농경지", "시설재배", "산업단지·발전시설·공항",
        "도로", "양식장", "어항·항만",
    ],
    "취약성(민감도)": [
        "고령인구", "위험시설물", "침수면적", "지하·반지하", "침식지역",
        "급경사지", "문화재",
    ],
    "취약성(저감능력)": [
        "대피소", "재난재해관리기금", "공무원수", "지역자율방재단", "시민안전보험",
    ],
}

SPATIAL_FACTOR_UNITS = {
    "강우": "mm/h", "강풍": "m/s", "파랑": "m", "해일": "m",
    "해수면 상승": "mm/yr", "인구": "명", "건물": "m²", "도로": "m²",
    "양식장": "m²", "농경지": "m²", "산업단지·발전시설·공항": "m²",
    "어항·항만": "m²", "시설재배": "m²", "고령인구": "명",
    "침수면적": "m²", "지하·반지하": "m²", "문화재": "m²",
    "위험시설물": "등급(범주형)", "급경사지": "등급(범주형)",
    "침식지역": "등급(범주형)", "대피소": "인구 1명당 수용인원(명)",
    "재난재해관리기금": "인구 1명당 관리기금액(원)",
    "공무원수": "인구 1만 명당 공무원 수(명)",
    "지역자율방재단": "인구 1만 명당 방재단 수(명)", "시민안전보험": "원",
}

SPATIAL_GRADE_METRICS = [
    {
        "id": "overall",
        "label": "종합 위험",
        "group": "종합",
        "grade_column": "위험성지수_등급",
    },
    {
        "id": "hazard",
        "label": "위해성",
        "group": "복합지수",
        "grade_column": "위해성지수_등급",
    },
    {
        "id": "exposure",
        "label": "노출성",
        "group": "복합지수",
        "grade_column": "노출성지수_등급",
    },
    {
        "id": "sensitivity",
        "label": "취약성(민감도)",
        "group": "복합지수",
        "grade_column": "취약성지수(가중)_등급",
    },
    {
        "id": "reduction",
        "label": "취약성(저감능력)",
        "group": "복합지수",
        "grade_column": "취약성지수(저감)_등급",
    },
]
for _group, _factors in SPATIAL_FACTOR_GROUPS.items():
    SPATIAL_GRADE_METRICS.extend({
        "id": factor,
        "label": factor,
        "group": _group,
        "grade_column": f"{factor}_등급",
    } for factor in _factors)


def agent_root() -> Path:
    return Path(os.environ.get("COASTAL_AGENT_ROOT", DEFAULT_AGENT_ROOT)).resolve()


def _load_agent_modules():
    root = agent_root()
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    source = root / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from coastal_agent.db import QueryEngine
    from coastal_agent.graph import build_graph
    from coastal_agent.query_agent import ask

    return QueryEngine, build_graph, ask


class SpatialService:
    PROPERTY_COLUMNS = [
        "FTR_IDN",
        "SD_NM",
        "SGG_NM",
        "ADM_NM",
        "위해성지수_등급",
        "노출성지수_등급",
        "취약성지수(가중)_등급",
        "취약성지수(저감)_등급",
        "위험성지수_등급",
    ]
    RISK_GRADE = "위험성지수_등급"
    GRADE_METRICS = SPATIAL_GRADE_METRICS

    def __init__(
        self,
        gpkg_path: Path | str | None = None,
        layer: str | None = None,
        parquet_path: Path | str | None = None,
        export_root: Path | str | None = None,
        annotation_root: Path | str | None = None,
    ):
        use_default_source = gpkg_path is None
        if gpkg_path is None or layer is None:
            source = agent_root() / "src"
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            from coastal_agent import config

            gpkg_path = gpkg_path or config.GPKG_PATH
            layer = layer or config.GPKG_LAYER
            if parquet_path is None and use_default_source:
                parquet_path = config.PARQUET_CACHE
        self.gpkg_path = Path(gpkg_path)
        self.layer = layer
        self.parquet_path = Path(parquet_path) if parquet_path else None
        self.export_root = Path(export_root or SPATIAL_EXPORT_ROOT)
        self.annotation_root = Path(annotation_root or SPATIAL_ANNOTATION_ROOT)

    def _attach_raw_factor_data(self, frame):
        """GPKG의 격자 ID에 DuckDB 원자료를 결합한다."""
        raw_columns = [
            f"{factor}_원자료"
            for factors in SPATIAL_FACTOR_GROUPS.values()
            for factor in factors
        ]
        if any(column in frame for column in raw_columns) or not self.parquet_path:
            return frame

        QueryEngine, _, _ = _load_agent_modules()
        engine = QueryEngine(self.parquet_path)
        try:
            available = {row[0] for row in engine.con.execute("DESCRIBE grid").fetchall()}
            selected_columns = [column for column in raw_columns if column in available]
            if "FTR_IDN" not in available or not selected_columns:
                return frame
            quoted = ", ".join(f'"{column}"' for column in selected_columns)
            parts = self._where_region_values(frame)
            sql = f'SELECT "FTR_IDN", {quoted} FROM grid WHERE "SD_NM" = ?'
            params = [parts[0]]
            if len(parts) > 1:
                sql += ' AND "SGG_NM" = ?'
                params.append(parts[1])
            raw = engine.con.execute(sql, params).fetchdf()
        finally:
            engine.con.close()
        if raw.empty:
            return frame
        joined = frame.copy()
        joined["FTR_IDN"] = joined["FTR_IDN"].astype(str)
        raw["FTR_IDN"] = raw["FTR_IDN"].astype(str)
        return joined.merge(raw, on="FTR_IDN", how="left")

    @staticmethod
    def _where_region_values(frame) -> list[str]:
        values = [str(frame["SD_NM"].dropna().iloc[0])]
        if "SGG_NM" in frame and not frame["SGG_NM"].dropna().empty:
            values.append(str(frame["SGG_NM"].dropna().iloc[0]))
        return values

    @staticmethod
    def _quote(value: str) -> str:
        return value.replace("'", "''")

    def _metric(self, metric: str = "overall") -> dict:
        selected = next((item for item in self.GRADE_METRICS if item["id"] == metric), None)
        if selected is None:
            raise ValueError(f"지원하지 않는 평가항목입니다: {metric}")
        return selected

    def _where(
        self,
        region: str,
        grades: list[str] | None = None,
        focus_names: list[str] | None = None,
        metric: str = "overall",
    ) -> str:
        parts = region.split()
        clauses = [f"SD_NM = '{self._quote(parts[0])}'"]
        if len(parts) > 1:
            district = " ".join(parts[1:])
            clauses.append(f"SGG_NM = '{self._quote(district)}'")
        if grades:
            safe_grades = [grade for grade in grades if grade in {"1", "2", "3", "4", "5"}]
            if safe_grades:
                values = ", ".join(f"'{grade}'" for grade in safe_grades)
                grade_column = self._metric(metric)["grade_column"]
                clauses.append(f'"{grade_column}" IN ({values})')
        if focus_names:
            names = [str(name).strip() for name in focus_names if str(name).strip()]
            if names:
                values = ", ".join(f"'{self._quote(name)}'" for name in names)
                clauses.append(f"ADM_NM IN ({values})")
        return " AND ".join(clauses)

    def _columns(self, metric: str = "overall") -> list[str]:
        import pyogrio

        fields = set(pyogrio.read_info(self.gpkg_path, layer=self.layer)["fields"])
        grade_column = self._metric(metric)["grade_column"]
        columns = [column for column in self.PROPERTY_COLUMNS if column in fields]
        if grade_column in fields and grade_column not in columns:
            columns.append(grade_column)
        return columns

    def metadata(self, region: str) -> dict:
        import pyogrio

        info = pyogrio.read_info(self.gpkg_path, layer=self.layer)
        fields = set(info["fields"])
        metrics = [metric for metric in self.GRADE_METRICS if metric["grade_column"] in fields]
        frame = pyogrio.read_dataframe(
            self.gpkg_path,
            layer=self.layer,
            columns=[metric["grade_column"] for metric in metrics],
            where=self._where(region),
            read_geometry=False,
        )
        metric_items = []
        for metric in metrics:
            counts = frame[metric["grade_column"]].dropna().astype(str).value_counts().sort_index()
            metric_items.append({
                **metric,
                "grade_counts": {grade: int(count) for grade, count in counts.items()},
            })
        overall = next(item for item in metric_items if item["id"] == "overall")
        return {
            "id": "risk_grid",
            "name": "연안재해 위험 격자",
            "feature_count": int(len(frame)),
            "geometry_type": info["geometry_type"],
            "source_crs": info["crs"],
            "grade_counts": overall["grade_counts"],
            "metrics": metric_items,
        }

    def features(
        self,
        region: str,
        grades: list[str] | None = None,
        limit: int = 0,
        focus_names: list[str] | None = None,
        metric: str = "overall",
    ) -> dict:
        import json

        import pyogrio

        # limit=0(기본)은 무제한 — 지역의 모든 격자를 표시한다.
        # 양수 limit이 오면, 파일 순서 앞쪽 N개만 자르는 대신 균등 간격으로
        # 표본한다. 앞쪽 절단은 뒤쪽에 저장된 동 일대를 지도에서 통째로
        # 사라지게 했다(강릉 초당동·강문동 사례). 통계·선택 분석은 별도
        # 경로에서 전체 격자로 계산하므로 표시 방식과 무관하다.
        safe_limit = max(0, int(limit or 0))
        selected_metric = self._metric(metric)
        truncated = False
        if safe_limit:
            frame = pyogrio.read_dataframe(
                self.gpkg_path,
                layer=self.layer,
                columns=self._columns(metric),
                where=self._where(region, grades, focus_names, metric),
                max_features=safe_limit + 1,
            )
            truncated = len(frame) > safe_limit
            if truncated:
                frame = pyogrio.read_dataframe(
                    self.gpkg_path,
                    layer=self.layer,
                    columns=self._columns(metric),
                    where=self._where(region, grades, focus_names, metric),
                )
                step = -(-len(frame) // safe_limit)
                frame = frame.iloc[::step]
            frame = frame.iloc[:safe_limit]
        else:
            frame = pyogrio.read_dataframe(
                self.gpkg_path,
                layer=self.layer,
                columns=self._columns(metric),
                where=self._where(region, grades, focus_names, metric),
            )
        frame = frame.to_crs(4326)
        collection = json.loads(frame.to_json(drop_id=True, na="null"))
        collection["metadata"] = {
            "count": len(collection["features"]),
            "truncated": truncated,
            "source_crs": "EPSG:5179",
            "display_crs": "EPSG:4326",
            "metric": selected_metric,
        }
        return collection

    def _spatial_operation_frame(self, region: str, columns: list[str] | None = None):
        import pyogrio

        fields = set(pyogrio.read_info(self.gpkg_path, layer=self.layer)["fields"])
        requested = list(dict.fromkeys([*self.PROPERTY_COLUMNS, *(columns or [])]))
        selected_columns = [column for column in requested if column in fields]
        return pyogrio.read_dataframe(
            self.gpkg_path,
            layer=self.layer,
            columns=selected_columns,
            where=self._where(region),
        )

    @staticmethod
    def _grade_values(text: str) -> list[str]:
        matches = re.findall(r"([1-5](?:\s*[·,와과~\-]\s*[1-5])*)\s*등급", text)
        return sorted({grade for match in matches for grade in re.findall(r"[1-5]", match)})

    def _question_conditions(self, question: str) -> list[dict]:
        candidates = []
        occupied: list[tuple[int, int]] = []
        for metric in sorted(self.GRADE_METRICS, key=lambda item: len(item["label"]), reverse=True):
            for match in re.finditer(re.escape(metric["label"]), question):
                span = match.span()
                if any(span[0] < end and start < span[1] for start, end in occupied):
                    continue
                occupied.append(span)
                candidates.append((span[0], span[1], metric))
                break
        candidates.sort(key=lambda item: item[0])
        global_grades = self._grade_values(question)
        if not global_grades and "고위험" in question:
            global_grades = ["4", "5"]
        conditions = []
        for index, (start, end, metric) in enumerate(candidates):
            segment_end = candidates[index + 1][0] if index + 1 < len(candidates) else len(question)
            grades = self._grade_values(question[end:segment_end]) or global_grades
            if not grades:
                continue
            conditions.append({
                "metric_id": metric["id"],
                "label": metric["label"],
                "grade_column": metric["grade_column"],
                "grades": grades,
            })
        return conditions

    def _operation_result(
        self,
        operation: str,
        name: str,
        region: str,
        frame,
        summary: str,
        *,
        conditions: list[dict] | None = None,
        evidence: dict | None = None,
        extra_stats: dict | None = None,
    ) -> dict:
        import json

        display_limit = 5000
        displayed = frame.iloc[:display_limit]
        collection = json.loads(displayed.to_crs(4326).to_json(drop_id=True, na="null"))
        operation_id = uuid.uuid4().hex[:12]
        collection["metadata"] = {
            "count": int(len(frame)),
            "truncated": len(frame) > display_limit,
            "display_crs": "EPSG:4326",
            "operation_id": operation_id,
            "operation": operation,
        }
        stats = {"feature_count": int(len(frame)), **(extra_stats or {})}
        evidence = evidence or {"source": f"GPKG · {self.layer}", "queries": []}
        return {
            "operation_id": operation_id,
            "operation": operation,
            "name": name,
            "region": region,
            "conditions": conditions or [],
            "stats": stats,
            "summary": summary,
            "feature_collection": collection,
            "evidence": evidence,
            "report_material": {
                "question": name,
                "answer": summary,
                "region": region,
                "grounded": True,
                "queries": evidence.get("queries") or [evidence.get("source", "GPKG 공간조회")],
                "results": [{
                    "columns": ["지표", "값", "단위"],
                    "rows": [["대상 격자", int(len(frame)), "개"]],
                }],
            },
        }

    def filter_from_question(self, region: str, question: str) -> dict:
        conditions = self._question_conditions(question)
        if not conditions:
            raise ValueError("질문에서 평가항목과 등급 조건을 찾지 못했습니다.")
        frame = self._spatial_operation_frame(
            region,
            [condition["grade_column"] for condition in conditions],
        )
        for condition in conditions:
            column = condition["grade_column"]
            if column not in frame:
                raise ValueError(f"공간 레이어에 {condition['label']} 등급이 없습니다.")
            frame = frame.loc[frame[column].astype(str).isin(condition["grades"])].copy()
        condition_text = " · ".join(
            f"{item['label']} {','.join(item['grades'])}등급" for item in conditions
        )
        summary = f"{condition_text} 조건을 모두 만족하는 격자는 {len(frame):,}개입니다."
        return self._operation_result(
            "filter",
            f"복합필터 · {condition_text}",
            region,
            frame,
            summary,
            conditions=conditions,
            evidence={
                "source": f"GPKG · {self.layer}",
                "queries": [
                    f"GPKG 속성필터 · {item['grade_column']} IN ({', '.join(item['grades'])})"
                    for item in conditions
                ],
            },
        )

    def analyze_neighborhood(
        self,
        region: str,
        ftr_id: str,
        distance_m: float = 500,
        metric: str = "overall",
        grades: list[str] | None = None,
    ) -> dict:
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import mapping

        selected_metric = self._metric(metric)
        impact_columns = [
            "인구_원자료", "고령인구_원자료", "건물_원자료", "대피소_원자료",
        ]
        frame = self._spatial_operation_frame(
            region,
            [selected_metric["grade_column"], *impact_columns],
        )
        frame = self._attach_raw_factor_data(frame)
        if frame.crs is None:
            raise ValueError("공간 레이어 좌표계가 없습니다.")
        projected = frame if not frame.crs.is_geographic else frame.to_crs(5179)
        source = projected.loc[projected["FTR_IDN"].astype(str) == str(ftr_id)]
        if source.empty:
            raise ValueError("선택한 격자를 공간 레이어에서 찾지 못했습니다.")
        source_geometry = source.geometry.iloc[0]
        analysis_geometry = (
            source_geometry
            if distance_m <= 0
            else source_geometry.buffer(distance_m)
        )
        selected = projected.loc[projected.geometry.intersects(analysis_geometry)].copy()
        safe_grades = [grade for grade in (grades or []) if grade in {"1", "2", "3", "4", "5"}]
        if safe_grades:
            selected = selected.loc[
                selected[selected_metric["grade_column"]].astype(str).isin(safe_grades)
            ].copy()
        mode = "adjacent" if distance_m <= 0 else "buffer"
        label = "직접 인접" if mode == "adjacent" else f"{distance_m:g}m 이내"
        impact_specs = [
            ("population", "영향권 인구", "인구_원자료", "명", "합계"),
            ("elderly_population", "영향권 고령인구", "고령인구_원자료", "명", "합계"),
            ("building_area", "영향권 건물면적", "건물_원자료", "m²", "합계"),
            (
                "shelter_capacity", "대피소 수용지표", "대피소_원자료",
                SPATIAL_FACTOR_UNITS["대피소"], "평균",
            ),
        ]
        impact = []
        for impact_id, impact_label, column, unit, aggregation in impact_specs:
            if column not in selected:
                continue
            values = pd.to_numeric(selected[column], errors="coerce").dropna()
            if values.empty:
                continue
            value = values.mean() if aggregation == "평균" else values.sum()
            impact.append({
                "id": impact_id,
                "label": impact_label,
                "value": round(float(value), 2),
                "unit": unit,
                "aggregation": aggregation,
            })
        impact_text = next(
            (
                f" 영향권 인구 {item['value']:g}{item['unit']}를 포함합니다."
                for item in impact if item["id"] == "population"
            ),
            "",
        )
        result = self._operation_result(
            mode,
            f"{ftr_id} 격자 {label}",
            region,
            selected,
            f"{ftr_id} 격자의 {label} 대상 격자는 {len(selected):,}개입니다.{impact_text}",
            conditions=[{
                "metric_id": metric,
                "label": selected_metric["label"],
                "grade_column": selected_metric["grade_column"],
                "grades": safe_grades,
            }],
            evidence={
                "source": f"GPKG · {self.layer}",
                "queries": [f"GPKG ST_Intersects · FTR_IDN={ftr_id} · distance={distance_m:g}m"],
            },
            extra_stats={"impact": impact},
        )
        if impact:
            result["report_material"]["results"].append({
                "columns": ["영향 지표", "값", "단위", "집계"],
                "rows": [
                    [item["label"], item["value"], item["unit"], item["aggregation"]]
                    for item in impact
                ],
            })
        boundary = gpd.GeoSeries([analysis_geometry], crs=projected.crs).to_crs(4326).iloc[0]
        result["source_ftr_id"] = str(ftr_id)
        result["distance_m"] = float(distance_m)
        result["analysis_geometry"] = mapping(boundary)
        return result

    def analyze_hotspots(
        self,
        region: str,
        metric: str = "overall",
        grades: list[str] | None = None,
        min_cluster_size: int = 2,
    ) -> dict:
        import geopandas as gpd
        import pandas as pd

        selected_metric = self._metric(metric)
        safe_grades = [
            grade
            for grade in (grades or ["4", "5"])
            if grade in {"1", "2", "3", "4", "5"}
        ]
        frame = self._spatial_operation_frame(region, [selected_metric["grade_column"]])
        selected = frame.loc[
            frame[selected_metric["grade_column"]].astype(str).isin(safe_grades)
        ].copy().reset_index(drop=True)
        visited: set[int] = set()
        clusters: list[list[int]] = []
        spatial_index = selected.sindex
        for start in range(len(selected)):
            if start in visited:
                continue
            stack = [start]
            component = []
            visited.add(start)
            while stack:
                current = stack.pop()
                component.append(current)
                neighbors = spatial_index.query(
                    selected.geometry.iloc[current], predicate="intersects"
                )
                for neighbor in neighbors:
                    index = int(neighbor)
                    if index not in visited:
                        visited.add(index)
                        stack.append(index)
            if len(component) >= max(1, min_cluster_size):
                clusters.append(component)
        parts = []
        for cluster_id, indexes in enumerate(clusters, 1):
            part = selected.iloc[indexes].copy()
            part["cluster_id"] = cluster_id
            part["cluster_size"] = len(part)
            parts.append(part)
        clustered = gpd.GeoDataFrame(
            pd.concat(parts, ignore_index=True) if parts else selected.iloc[0:0].copy(),
            geometry="geometry",
            crs=selected.crs,
        )
        largest = max((len(component) for component in clusters), default=0)
        summary = (
            f"{selected_metric['label']} {','.join(safe_grades)}등급 격자에서 "
            f"{len(clusters):,}개 군집을 확인했습니다. 가장 큰 군집은 {largest:,}개 격자입니다."
        )
        return self._operation_result(
            "hotspot",
            f"{selected_metric['label']} 핫스팟",
            region,
            clustered,
            summary,
            conditions=[{
                "metric_id": metric,
                "label": selected_metric["label"],
                "grade_column": selected_metric["grade_column"],
                "grades": safe_grades,
            }],
            evidence={
                "source": f"GPKG · {self.layer}",
                "queries": ["GPKG 격자 교차 그래프 · 연결요소 군집 분석"],
            },
            extra_stats={"cluster_count": len(clusters), "largest_cluster": largest},
        )

    def analyze_feature(self, region: str, ftr_id: str, metric: str = "overall") -> dict:
        import geopandas as gpd
        from shapely.geometry import mapping

        frame = self._spatial_operation_frame(region, [self._metric(metric)["grade_column"]])
        if frame.crs is None:
            raise ValueError("공간 레이어 좌표계가 없습니다.")
        target = frame.loc[frame["FTR_IDN"].astype(str) == str(ftr_id)]
        if target.empty:
            raise ValueError("선택한 격자를 공간 레이어에서 찾지 못했습니다.")
        projected = target if not target.crs.is_geographic else target.to_crs(5179)
        probe = projected.geometry.iloc[0].representative_point().buffer(0.01)
        geometry = mapping(gpd.GeoSeries([probe], crs=projected.crs).to_crs(4326).iloc[0])
        result = self.analyze_selection(region, geometry, [], metric)
        result["summary"] = f"{ftr_id} 격자 단일 분석입니다. {result['summary']}"
        result["report_material"]["question"] = f"{ftr_id} 격자 위험 원인 분석"
        return result

    def scope_from_queries(self, region: str, queries: list[str]) -> dict:
        import pandas as pd

        parsed_queries = []
        conditions = []
        for sql in queries:
            focus_names: set[str] = set()
            for match in re.finditer(
                r'["`]?ADM_NM["`]?\s*=\s*[\'\"]([^\'\"]+)[\'\"]', sql, re.IGNORECASE,
            ):
                focus_names.add(match.group(1))
            for match in re.finditer(
                r'["`]?ADM_NM["`]?\s+IN\s*\(([^)]+)\)', sql, re.IGNORECASE,
            ):
                focus_names.update(re.findall(r'[\'\"]([^\'\"]+)[\'\"]', match.group(1)))
            query_conditions = []
            for metric in self.GRADE_METRICS:
                column = metric["grade_column"]
                in_match = re.search(
                    rf'["`]?{re.escape(column)}["`]?\s+IN\s*\(([^)]+)\)', sql, re.IGNORECASE,
                )
                equal_match = re.search(
                    rf'["`]?{re.escape(column)}["`]?\s*=\s*[\'\"]?([1-5])[\'\"]?',
                    sql,
                    re.IGNORECASE,
                )
                grade_source = in_match.group(1) if in_match else (
                    equal_match.group(1) if equal_match else ""
                )
                grades = sorted(set(re.findall(r"(?<!\d)[1-5](?!\d)", grade_source)))
                if grades:
                    condition = {
                        "metric_id": metric["id"], "label": metric["label"],
                        "grade_column": column, "grades": grades,
                    }
                    query_conditions.append(condition)
                    if condition not in conditions:
                        conditions.append(condition)
            parsed_queries.append((focus_names, query_conditions))

        columns = list(dict.fromkeys(
            condition["grade_column"]
            for _, query_conditions in parsed_queries
            for condition in query_conditions
        ))
        source_frame = self._spatial_operation_frame(region, columns)
        scoped_frames = []
        for focus_names, query_conditions in parsed_queries or [(set(), [])]:
            scoped = source_frame
            if focus_names:
                scoped = scoped.loc[scoped["ADM_NM"].astype(str).isin(focus_names)]
            for condition in query_conditions:
                scoped = scoped.loc[
                    scoped[condition["grade_column"]].astype(str).isin(condition["grades"])
                ]
            scoped_frames.append(scoped)
        frame = source_frame.iloc[0:0].copy()
        if scoped_frames:
            frame = pd.concat(scoped_frames).drop_duplicates(subset=["FTR_IDN"])
        summary = f"실행 SQL의 지역·등급 조건이 적용된 조회 범위는 {len(frame):,}개 격자입니다."
        return self._operation_result(
            "query_scope",
            "질문에 사용된 데이터 조회 범위",
            region,
            frame,
            summary,
            conditions=conditions,
            evidence={"source": "DuckDB SQL → GPKG 범위 재현", "queries": queries},
        )

    def analyze_selection(
        self,
        region: str,
        geometry: dict,
        grades: list[str] | None = None,
        metric: str = "overall",
    ) -> dict:
        import geopandas as gpd
        import pandas as pd
        import pyogrio
        from shapely.geometry import shape

        selected_metric = self._metric(metric)
        try:
            selected_geometry = shape(geometry)
        except Exception as error:
            raise ValueError("선택 영역 GeoJSON이 올바르지 않습니다.") from error
        if (
            selected_geometry.geom_type not in {"Polygon", "MultiPolygon"}
            or selected_geometry.is_empty
        ):
            raise ValueError("선택 영역은 Polygon 또는 MultiPolygon이어야 합니다.")

        fields = set(pyogrio.read_info(self.gpkg_path, layer=self.layer)["fields"])
        analysis_columns = list(self._columns(metric))
        for factors in SPATIAL_FACTOR_GROUPS.values():
            for factor in factors:
                for column in (f"{factor}_원자료", f"{factor}_등급"):
                    if column in fields and column not in analysis_columns:
                        analysis_columns.append(column)
        frame = pyogrio.read_dataframe(
            self.gpkg_path,
            layer=self.layer,
            columns=analysis_columns,
            where=self._where(region),
        )
        frame = self._attach_raw_factor_data(frame)
        if frame.crs is None:
            raise ValueError("공간 레이어 좌표계가 없습니다.")
        projected_selection = (
            gpd.GeoSeries([selected_geometry], crs="EPSG:4326")
            .to_crs(frame.crs)
            .iloc[0]
        )
        selected = frame.loc[frame.geometry.intersects(projected_selection)].copy()
        safe_grades = [grade for grade in (grades or []) if grade in {"1", "2", "3", "4", "5"}]
        grade_column = selected_metric["grade_column"]
        if safe_grades and grade_column in selected:
            selected = selected.loc[selected[grade_column].astype(str).isin(safe_grades)].copy()
        if selected.empty:
            raise ValueError("선택 영역에 교차하는 격자가 없습니다.")

        grade_values = (
            selected[grade_column].dropna().astype(str)
            if grade_column in selected
            else []
        )
        numeric_grades = [
            int(value) for value in grade_values if value in {"1", "2", "3", "4", "5"}
        ]
        grade_counts = {
            grade: numeric_grades.count(int(grade))
            for grade in ["1", "2", "3", "4", "5"]
            if numeric_grades.count(int(grade))
        }
        high_risk_count = sum(value >= 4 for value in numeric_grades)
        selected_count = len(selected)
        stats = {
            "selected_count": selected_count,
            "average_grade": (
                round(sum(numeric_grades) / len(numeric_grades), 2)
                if numeric_grades
                else None
            ),
            "high_risk_count": high_risk_count,
            "high_risk_pct": (
                round(high_risk_count * 100 / len(numeric_grades), 1)
                if numeric_grades
                else 0.0
            ),
            "grade_counts": grade_counts,
        }

        overlaps = []
        for candidate in self.GRADE_METRICS:
            if candidate["group"] not in {"종합", "복합지수"}:
                continue
            column = candidate["grade_column"]
            if column not in selected:
                continue
            values = selected[column].dropna().astype(str)
            high_count = int(values.isin(["4", "5"]).sum())
            overlaps.append({
                "metric_id": candidate["id"],
                "label": candidate["label"],
                "high_risk_count": high_count,
                "high_risk_pct": round(high_count * 100 / len(values), 1) if len(values) else 0.0,
            })

        drivers = []
        for group, factors in SPATIAL_FACTOR_GROUPS.items():
            for factor in factors:
                raw_column = f"{factor}_원자료"
                factor_grade_column = f"{factor}_등급"
                if raw_column not in frame or factor_grade_column not in frame:
                    continue
                selected_raw = pd.to_numeric(selected[raw_column], errors="coerce").dropna()
                region_raw = pd.to_numeric(frame[raw_column], errors="coerce").dropna()
                if selected_raw.empty or region_raw.empty:
                    continue
                selected_factor_grades = selected[factor_grade_column].dropna().astype(str)
                region_factor_grades = frame[factor_grade_column].dropna().astype(str)
                selected_high_pct = round(
                    selected_factor_grades.isin(["4", "5"]).mean() * 100, 1,
                ) if len(selected_factor_grades) else 0.0
                region_high_pct = round(
                    region_factor_grades.isin(["4", "5"]).mean() * 100, 1,
                ) if len(region_factor_grades) else 0.0
                high_mask = frame[factor_grade_column].astype(str).isin(["4", "5"])
                high_raw = pd.to_numeric(frame.loc[high_mask, raw_column], errors="coerce").dropna()
                drivers.append({
                    "factor": factor,
                    "group": group,
                    "unit": SPATIAL_FACTOR_UNITS.get(factor, "단위 미기재"),
                    "selected_mean": round(float(selected_raw.mean()), 2),
                    "region_mean": round(float(region_raw.mean()), 2),
                    "selected_high_risk_pct": selected_high_pct,
                    "region_high_risk_pct": region_high_pct,
                    "difference_pct_point": round(selected_high_pct - region_high_pct, 1),
                    "high_risk_range": [
                        round(float(high_raw.min()), 2), round(float(high_raw.max()), 2),
                    ] if not high_raw.empty else None,
                })
        drivers.sort(key=lambda item: (-item["difference_pct_point"], item["factor"]))
        drivers = drivers[:5]

        display_limit = 5000
        display_selected = selected.iloc[:display_limit]
        collection = json.loads(display_selected.to_crs(4326).to_json(drop_id=True, na="null"))
        selection_id = uuid.uuid4().hex[:12]
        collection["metadata"] = {
            "count": selected_count,
            "truncated": selected_count > display_limit,
            "source_crs": str(frame.crs),
            "display_crs": "EPSG:4326",
            "selection_id": selection_id,
            "metric": selected_metric,
        }
        average_text = (
            f"평균 등급은 {stats['average_grade']:.2f}등급이며, "
            if stats["average_grade"] is not None
            else ""
        )
        summary = (
            f"선택 영역은 실제 GPKG 격자 {selected_count:,}개와 교차합니다. "
            f"{average_text}4·5등급은 {high_risk_count:,}개({stats['high_risk_pct']:.1f}%)입니다."
        )
        driver_sentences = []
        for driver in drivers[:3]:
            unit = driver["unit"]
            sentence = (
                f"{driver['factor']} 원자료 평균 {driver['selected_mean']:.2f}{unit}"
                f"(지역 전체 평균 {driver['region_mean']:.2f}{unit})이며, "
                f"4·5등급 비율은 지역보다 {driver['difference_pct_point']:.1f}%p 높습니다"
            )
            if driver["high_risk_range"]:
                low, high = driver["high_risk_range"]
                sentence += f". 실제 4·5등급 원자료 범위는 {low:.2f}~{high:.2f}{unit}입니다"
            driver_sentences.append(sentence + ".")
        analysis_narrative = " ".join(driver_sentences) or "비교 가능한 요인 원자료가 없습니다."
        result_rows = [
            ["교차 격자", selected_count, "개"],
            ["평균 등급", stats["average_grade"], "등급"],
            ["4·5등급 격자", high_risk_count, "개"],
            ["4·5등급 비율", stats["high_risk_pct"], "%"],
        ]
        driver_rows = [[
            item["factor"], item["group"], item["selected_mean"], item["region_mean"],
            item["unit"], item["selected_high_risk_pct"], item["region_high_risk_pct"],
            item["difference_pct_point"],
        ] for item in drivers]
        return {
            "selection_id": selection_id,
            "region": region,
            "grades": safe_grades,
            "selected_ftr_ids": (
                selected["FTR_IDN"].dropna().astype(str).drop_duplicates().tolist()
                if "FTR_IDN" in selected
                else []
            ),
            "metric": selected_metric,
            "geometry": geometry,
            "stats": stats,
            "overlaps": overlaps,
            "feature_collection": collection,
            "summary": summary,
            "analysis": {"narrative": analysis_narrative, "drivers": drivers},
            "report_material": {
                "question": f"{region} 사용자 선택 영역 공간 중첩 분석",
                "answer": f"{summary} {analysis_narrative}",
                "region": region,
                "grounded": True,
                "queries": [
                    f"GPKG 공간교차 · {self.layer} · {selected_metric['grade_column']}",
                    "DuckDB 원자료 격자 ID 결합 · 선택 격자와 지역 전체 요인 비교",
                ],
                "results": [
                    {"columns": ["지표", "값", "단위"], "rows": result_rows},
                    {
                        "columns": [
                            "요인", "분류", "선택 평균", "지역 평균", "단위",
                            "선택 4·5등급(%)", "지역 4·5등급(%)", "차이(%p)",
                        ],
                        "rows": driver_rows,
                    },
                ],
            },
        }

    def compare_selections(
        self,
        region: str,
        geometry_a: dict,
        geometry_b: dict,
        grades: list[str] | None = None,
        metric: str = "overall",
    ) -> dict:
        area_a = self.analyze_selection(region, geometry_a, grades, metric)
        area_b = self.analyze_selection(region, geometry_b, grades, metric)
        average_a = area_a["stats"].get("average_grade")
        average_b = area_b["stats"].get("average_grade")
        average_difference = (
            round(float(average_b) - float(average_a), 2)
            if average_a is not None and average_b is not None
            else None
        )
        high_risk_difference = round(
            float(area_b["stats"].get("high_risk_pct", 0))
            - float(area_a["stats"].get("high_risk_pct", 0)),
            1,
        )
        if high_risk_difference > 0:
            summary = (
                f"B 영역의 고위험 비율이 A 영역보다 "
                f"{high_risk_difference:.1f}%p 높습니다."
            )
        elif high_risk_difference < 0:
            summary = (
                f"A 영역의 고위험 비율이 B 영역보다 "
                f"{abs(high_risk_difference):.1f}%p 높습니다."
            )
        else:
            summary = "A 영역과 B 영역의 고위험 비율이 같습니다."
        return {
            "region": region,
            "metric": area_a["metric"],
            "grades": grades or [],
            "area_a": area_a,
            "area_b": area_b,
            "difference": {
                "average_grade": average_difference,
                "high_risk_pct_point": high_risk_difference,
            },
            "summary": summary,
            "report_material": {
                "question": "사용자 선택 영역 A/B 비교",
                "answer": summary,
                "region": region,
                "grounded": True,
                "queries": [
                    "GPKG ST_Intersects: 사용자 선택 영역 A",
                    "GPKG ST_Intersects: 사용자 선택 영역 B",
                ],
                "results": [{
                    "columns": ["구분", "격자 수", "평균 등급", "4·5등급 비율", "단위"],
                    "rows": [
                        [
                            "A",
                            area_a["stats"]["selected_count"],
                            average_a,
                            area_a["stats"]["high_risk_pct"],
                            "개·등급·%",
                        ],
                        [
                            "B",
                            area_b["stats"]["selected_count"],
                            average_b,
                            area_b["stats"]["high_risk_pct"],
                            "개·등급·%",
                        ],
                    ],
                }],
            },
        }

    def export_map(
        self,
        region: str,
        metric: str = "overall",
        grades: list[str] | None = None,
        focus_names: list[str] | None = None,
        background: str = "transparent",
        extent: str = "region",
        geometry: dict | None = None,
        owner_id: str | None = None,
    ) -> dict:
        import geopandas as gpd
        import matplotlib
        import pyogrio
        from shapely.geometry import shape

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        from matplotlib.font_manager import FontProperties
        from matplotlib.patches import Patch

        selected_metric = self._metric(metric)
        if background not in {"satellite", "composite", "transparent"}:
            raise ValueError(f"지원하지 않는 배경지도입니다: {background}")
        if extent not in {"region", "viewport", "selection"}:
            raise ValueError(f"지원하지 않는 내보내기 범위입니다: {extent}")
        grade_column = selected_metric["grade_column"]
        base = pyogrio.read_dataframe(
            self.gpkg_path,
            layer=self.layer,
            columns=[grade_column],
            where=self._where(region),
        )
        selected = pyogrio.read_dataframe(
            self.gpkg_path,
            layer=self.layer,
            columns=[grade_column],
            where=self._where(region, grades, focus_names, metric),
        )
        if extent != "region":
            if not geometry:
                raise ValueError("특정부분 또는 선택격자를 저장하려면 지도 범위가 필요합니다.")
            try:
                area = shape(geometry)
            except Exception as error:
                raise ValueError("내보내기 범위 GeoJSON이 올바르지 않습니다.") from error
            if area.geom_type not in {"Polygon", "MultiPolygon"} or area.is_empty:
                raise ValueError("내보내기 범위는 Polygon 또는 MultiPolygon이어야 합니다.")
            projected = gpd.GeoSeries([area], crs="EPSG:4326").to_crs(base.crs).iloc[0]
            base = base.loc[base.geometry.intersects(projected)].copy()
            selected = selected.loc[selected.geometry.intersects(projected)].copy()

        export_root = self.export_root
        if owner_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", owner_id):
                raise ValueError("올바르지 않은 사용자 ID입니다.")
            export_root = export_root / owner_id
        export_root.mkdir(parents=True, exist_ok=True)
        grade_label = "·".join(grades) + "등급" if grades else "전체 등급"
        caption = f"{region} {selected_metric['label']} {grade_label} 공간분석"
        extent_labels = {"region": "전체", "viewport": "특정부분", "selection": "선택격자"}
        background_labels = {"satellite": "위성", "composite": "종합지도", "transparent": "투명"}
        if extent != "region" or background != "transparent":
            caption += f" · {extent_labels[extent]} · {background_labels[background]} 배경"
        slug = re.sub(r"[^\w가-힣-]+", "_", caption).strip("_")[:90]
        image_id = f"{slug}_{uuid.uuid4().hex[:8]}"
        image_path = export_root / f"{image_id}.png"

        user_fonts = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"
        font_path = next((path for path in (
            MAP_FONT_CANDIDATES[0],
            user_fonts / "PretendardGOV-Regular.otf",
            user_fonts / "Pretendard-Regular.otf",
            *MAP_FONT_CANDIDATES[1:],
        ) if path.is_file()), None)
        font = FontProperties(fname=font_path) if font_path else FontProperties()
        colors = {"1": "#004000", "2": "#00ff00", "3": "#ffff00", "4": "#ff8040", "5": "#ff0000"}
        transparent = background == "transparent"
        figure, axis = plt.subplots(figsize=(10, 7), dpi=180)
        if transparent:
            figure.patch.set_alpha(0)
            axis.patch.set_alpha(0)
        plot_base = base.to_crs(3857) if background != "transparent" and not base.empty else base
        plot_selected = (
            selected.to_crs(3857)
            if background != "transparent" and not selected.empty
            else selected
        )
        if not base.empty:
            plot_base.plot(
                ax=axis,
                color="none" if background != "transparent" else "#e8eef4",
                edgecolor="#ffffff" if background == "satellite" else "#c3d0dc",
                linewidth=0.2,
            )
        if not selected.empty:
            selected_colors = (
                selected[grade_column].fillna("").astype(str).map(colors).fillna("#9aa8b8")
            )
            plot_selected.plot(
                ax=axis,
                color=selected_colors,
                edgecolor="#ffffff",
                linewidth=0.3,
                alpha=0.88,
            )
        if background != "transparent" and not plot_base.empty:
            try:
                import contextily as ctx

                source = (
                    ctx.providers.Esri.WorldImagery
                    if background == "satellite"
                    else ctx.providers.OpenStreetMap.Mapnik
                )
                ctx.add_basemap(axis, source=source, crs="EPSG:3857", attribution=False)
            except Exception as error:
                plt.close(figure)
                raise ValueError(f"배경지도 타일을 불러오지 못했습니다: {error}") from error
        axis.set_title(caption, fontproperties=font, fontsize=17, fontweight="bold", pad=18)
        axis.text(
            0,
            -0.03,
            f"표시 격자 {len(selected):,}개 · 실제 GPKG {grade_column} 기준",
            transform=axis.transAxes,
            fontproperties=font,
            fontsize=9,
            color="#5d7185",
        )
        axis.axis("off")
        legend_grades = grades or ["1", "2", "3", "4", "5"]
        handles = [Patch(facecolor=colors[grade], label=f"{grade}등급") for grade in legend_grades]
        axis.legend(
            handles=handles,
            loc="lower right",
            frameon=True,
            prop=font,
            title=selected_metric["label"],
            title_fontproperties=font,
        )
        figure.tight_layout()
        figure.savefig(
            image_path,
            facecolor="none" if transparent else "white",
            transparent=transparent,
            bbox_inches="tight",
        )
        plt.close(figure)
        return {
            "image_id": image_id,
            "filename": f"{slug}.png",
            "caption": caption,
            "region": region,
            "metric": selected_metric["label"],
            "grades": list(grades or []),
            "feature_count": int(len(selected)),
            "background": background,
            "extent": extent,
        }

    def export_asset(self, image_id: str, owner_id: str | None = None) -> Path | None:
        if not image_id or Path(image_id).name != image_id:
            return None
        root = self.export_root / owner_id if owner_id else self.export_root
        path = (root / f"{image_id}.png").resolve()
        root = root.resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def import_annotation(
        self,
        files: list[tuple[str, bytes]],
        owner_id: str | None = None,
    ) -> dict:
        import pyogrio

        if not files:
            raise ValueError("업로드할 Shapefile을 선택해주세요.")
        allowed = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
        layer_id = uuid.uuid4().hex[:12]
        if owner_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", owner_id):
            raise ValueError("올바르지 않은 사용자 ID입니다.")
        annotation_root = self.annotation_root / owner_id if owner_id else self.annotation_root
        layer_dir = annotation_root / layer_id
        layer_dir.mkdir(parents=True, exist_ok=True)

        if len(files) == 1 and Path(files[0][0]).suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(files[0][1])) as archive:
                    members = [
                        item for item in archive.infolist()
                        if not item.is_dir() and Path(item.filename).suffix.lower() in allowed
                    ]
                    if sum(item.file_size for item in members) > 50 * 1024 * 1024:
                        raise ValueError(
                            "압축 해제된 annotation 파일은 최대 50MB까지 업로드할 수 있습니다."
                        )
                    for item in members:
                        name = Path(item.filename).name
                        if not name or name in {".", ".."}:
                            continue
                        (layer_dir / name).write_bytes(archive.read(item))
            except zipfile.BadZipFile as error:
                raise ValueError("올바른 Shapefile ZIP이 아닙니다.") from error
        else:
            for raw_name, content in files:
                name = Path(raw_name).name
                if Path(name).suffix.lower() not in allowed:
                    raise ValueError(f"지원하지 않는 Shapefile 구성 파일입니다: {name}")
                (layer_dir / name).write_bytes(content)

        shapefiles = [path for path in layer_dir.iterdir() if path.suffix.lower() == ".shp"]
        if len(shapefiles) != 1:
            raise ValueError("하나의 .shp와 같은 이름의 .shx·.dbf·.prj 파일이 필요합니다.")
        shapefile = shapefiles[0]
        info = pyogrio.read_info(shapefile)
        if int(info["features"]) > 5000:
            raise ValueError("annotation 레이어는 최대 5,000개 피처까지 업로드할 수 있습니다.")
        frame = pyogrio.read_dataframe(shapefile)
        if frame.crs is None:
            raise ValueError("좌표계 확인을 위해 .prj 파일을 함께 업로드해주세요.")
        frame = frame[frame.geometry.notna()].to_crs(4326)
        columns = [column for column in frame.columns if column != frame.geometry.name]
        if not columns:
            raise ValueError("annotation으로 사용할 속성 컬럼이 없습니다.")
        priorities = ["ADM_NM", "SGG_NM", "SD_NM", "지역명", "NAME", "name"]
        suggested = next((column for column in priorities if column in columns), columns[0])
        geojson = json.loads(frame.to_json(drop_id=True, na="null"))
        (layer_dir / "layer.geojson").write_text(
            json.dumps(geojson, ensure_ascii=False),
            encoding="utf-8",
        )
        geometry_types = sorted(set(frame.geom_type.dropna().astype(str)))
        return {
            "id": layer_id,
            "name": shapefile.stem,
            "feature_count": int(len(frame)),
            "geometry_type": ", ".join(geometry_types),
            "source_crs": str(info["crs"]),
            "display_crs": "EPSG:4326",
            "columns": columns,
            "suggested_label_field": suggested,
            "geojson": geojson,
        }


class _SelectionScopedEngine:
    def __init__(self, engine, selection_id: str, ftr_ids: list[str]):
        self.engine = engine
        self.selection_id = str(selection_id)
        self.table_name = "selected_grid"
        self.ftr_ids = list(dict.fromkeys(str(value) for value in ftr_ids))
        if not self.ftr_ids:
            raise ValueError("선택 영역에 교차하는 격자가 없습니다.")
        register = getattr(self.engine, "register_selection", None)
        if register is None:
            raise ValueError("선택 영역 조회를 지원하지 않는 데이터 엔진입니다.")
        register(self.ftr_ids)

    def validate(self, sql: str) -> str:
        cleaned = self.engine.validate(sql)
        if self.selection_id and self.selection_id in cleaned:
            raise ValueError(
                "선택 영역 ID는 데이터 값이 아닙니다. 선택 격자는 selected_grid를 사용하세요."
            )
        if re.search(r"\bselection_scope_", cleaned, re.IGNORECASE):
            raise ValueError("이전 선택 영역 테이블명 대신 selected_grid를 사용하세요.")
        return cleaned

    def run(self, sql: str, limit: int = 200):
        return self.engine.run(self.validate(sql), limit=limit)

    def schema_doc(self) -> str:
        return (
            self.engine.schema_doc()
            + f"\n\n추가 테이블: selected_grid ({len(self.ftr_ids):,}행)\n"
            "selected_grid는 사용자가 선택한 격자만 포함합니다. "
            "원본 grid는 지역 전체 또는 비교 집단 기준값 조회에 사용합니다.\n"
            "선택 영역 질문에는 selected_grid를 사용하고, 선택 영역과 지역 전체를 "
            "비교할 때는 selected_grid와 grid를 모두 조회하세요."
        )


class QueryService:
    RISK_GRADE = "위험성지수_등급"
    _relation_reference = re.compile(
        r'\b(?:FROM|JOIN)\s+(?:"(?P<quoted>[^"]+)"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))',
        re.IGNORECASE,
    )

    def __init__(self, engine_factory=None, ask_fn=None):
        if engine_factory is None or ask_fn is None:
            default_engine, _, default_ask = _load_agent_modules()
            engine_factory = engine_factory or default_engine
            ask_fn = ask_fn or default_ask
        self.engine_factory = engine_factory
        self.ask_fn = ask_fn

    def _with_engine(self, operation):
        engine = self.engine_factory()
        try:
            return operation(engine)
        finally:
            connection = getattr(engine, "con", engine)
            close = getattr(connection, "close", None)
            if callable(close):
                close()

    @classmethod
    def _uses_relation(cls, queries: list[str], table_name: str) -> bool:
        expected = table_name.casefold()
        return any(
            (match.group("quoted") or match.group("plain")).casefold() == expected
            for sql in queries
            for match in cls._relation_reference.finditer(sql)
        )

    @classmethod
    def _baseline_is_region_scoped(
        cls,
        queries: list[str],
        region: str | None,
    ) -> bool:
        if not region:
            return True
        region_tokens = {region, region.split()[-1]}
        return any(
            cls._uses_relation([sql], "grid")
            and any(token in sql for token in region_tokens)
            for sql in queries
        )

    @staticmethod
    def _selection_metric_label(selection: dict) -> str:
        metric_id = str(selection.get("metric") or "overall")
        metric = next(
            (item for item in SPATIAL_GRADE_METRICS if item["id"] == metric_id),
            None,
        )
        return str(metric["label"] if metric else metric_id)

    def regions(self) -> list[dict]:
        return self._with_engine(self._regions)

    def data_quality(self, region: str | None = None) -> dict:
        return self._with_engine(lambda engine: self._data_quality(engine, region))

    def _data_quality(self, engine, region: str | None = None) -> dict:
        _, schema_rows = engine.run(
            """
            SELECT column_name, data_type
            FROM duckdb_columns()
            WHERE table_name = 'grid'
            ORDER BY column_index
            """.strip(),
            limit=300,
        )
        available = [str(row[0]) for row in schema_rows]
        inspected = [
            column
            for column in available
            if column in {"FTR_IDN", "SD_NM", "SGG_NM", "ADM_NM", self.RISK_GRADE}
            or column.endswith("_원자료")
            or column.endswith("_등급")
        ]
        where = f" WHERE {self._region_where(region)}" if region else ""
        statements = []
        for column in inspected:
            escaped = column.replace("'", "''")
            invalid = (
                f'SUM(CASE WHEN "{column}" IS NOT NULL AND '
                f'TRY_CAST("{column}" AS DOUBLE) NOT BETWEEN 1 AND 5 THEN 1 ELSE 0 END)'
                if column.endswith("_등급")
                else "0"
            )
            statements.append(
                f"SELECT '{escaped}' AS column_name, COUNT(*) AS total_count, "
                f'SUM(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) AS missing_count, '
                f"{invalid} AS invalid_count FROM grid{where}"
            )
        quality_rows = []
        if statements:
            _, quality_rows = engine.run(" UNION ALL ".join(statements), limit=300)
        columns = []
        for column, total, missing, invalid in quality_rows:
            total_count = int(total or 0)
            missing_count = int(missing or 0)
            columns.append({
                "name": str(column),
                "total_count": total_count,
                "missing_count": missing_count,
                "missing_pct": round(missing_count * 100 / total_count, 1) if total_count else 0.0,
                "invalid_count": int(invalid or 0),
                "unit": (
                    SPATIAL_FACTOR_UNITS.get(str(column)[:-4], "단위 미기재")
                    if str(column).endswith("_원자료")
                    else "등급" if str(column).endswith("_등급") else None
                ),
            })
        row_count = max((item["total_count"] for item in columns), default=0)
        temporal_columns = [
            column for column in available
            if re.search(r"(?:연도|년도|기준일|날짜|date|year|time)", column, re.IGNORECASE)
        ]
        required_impact = {
            "인구_원자료", "고령인구_원자료", "건물_원자료", "대피소_원자료",
        }
        root = agent_root()
        source_paths = [
            root / "로우데이터 및 표준화 및 등급자료(본평가_평가완료).xlsx",
            root / "본평가_평가완료_시각화.gpkg",
        ]
        sources = []
        for path in source_paths:
            if not path.is_file():
                continue
            stat = path.stat()
            sources.append({
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc,
                ).isoformat(),
            })
        signature = "|".join(
            f"{item['name']}:{item['size']}:{item['modified_at']}" for item in sources
        )
        return _json_safe({
            "region": region,
            "row_count": row_count,
            "schema_column_count": len(available),
            "dataset_version": (
                hashlib.sha256(signature.encode()).hexdigest()[:12]
                if signature
                else None
            ),
            "sources": sources,
            "columns": columns,
            "summary": {
                "missing_cells": sum(item["missing_count"] for item in columns),
                "invalid_grade_cells": sum(item["invalid_count"] for item in columns),
                "unit_missing_columns": [
                    item["name"] for item in columns if item["unit"] == "단위 미기재"
                ],
            },
            "capabilities": {
                "time_series": {
                    "supported": bool(temporal_columns),
                    "reason": (
                        f"시간 컬럼 {', '.join(temporal_columns)}을 사용할 수 있습니다."
                        if temporal_columns
                        else "현재 원자료에 연도·기준일 등 시간 컬럼이 없습니다."
                    ),
                    "columns": temporal_columns,
                },
                "spatial_impact": {
                    "supported": required_impact.issubset(set(available)),
                    "reason": "인구·고령인구·건물·대피소 원자료 연결 상태",
                },
                "scheduled_monitoring": {
                    "supported": bool(temporal_columns),
                    "reason": (
                        "버전별 변화 감시를 구성할 수 있습니다."
                        if temporal_columns
                        else "정기 변화 알림에는 최소 2개 시점의 데이터가 필요합니다."
                    ),
                },
            },
        })

    @staticmethod
    def _regions(engine) -> list[dict]:
        _, rows = engine.run(
            """
            SELECT DISTINCT SD_NM, SGG_NM
            FROM grid
            WHERE SD_NM IS NOT NULL AND SGG_NM IS NOT NULL
            ORDER BY SD_NM, SGG_NM
            """
        )
        grouped: dict[str, list[str]] = {}
        for sido, district in rows:
            grouped.setdefault(sido, []).append(district)
        return [
            {"name": sido, "districts": districts}
            for sido, districts in grouped.items()
        ]

    def mcp_dataset(
        self,
        region: str,
        focus_names: list[str] | None = None,
        limit: int | None = None,
        selection_ftr_ids: list[str] | None = None,
    ) -> dict:
        return self._with_engine(
            lambda engine: self._mcp_dataset(
                engine,
                region,
                focus_names=focus_names,
                limit=limit,
                selection_ftr_ids=selection_ftr_ids,
            )
        )

    def mcp_dataset_columns(self, region: str) -> list[str]:
        """직접 설정 차트에서 축으로 고를 수 있는 격자 원자료 열 라벨."""
        return self._with_engine(
            lambda engine: [
                label for _, label in self._mcp_dataset_fields(engine)
            ]
        )

    @staticmethod
    def _mcp_dataset_fields(engine) -> list[tuple[str, str]]:
        _, schema_rows = engine.run(
            """
            SELECT column_name
            FROM duckdb_columns()
            WHERE table_name = 'grid'
            ORDER BY column_index
            """.strip(),
            limit=200,
        )
        available = {str(row[0]) for row in schema_rows}
        grade_fields = [
            ("위험성지수_등급", "종합 위험 (등급)"),
            ("위해성지수_등급", "위해성 (등급)"),
            ("노출성지수_등급", "노출성 (등급)"),
            ("취약성지수(가중)_등급", "취약성·민감도 (등급)"),
            ("취약성지수(저감)_등급", "취약성·저감능력 (등급)"),
        ]
        raw_fields = [
            (
                f"{factor}_원자료",
                f"{factor} ({SPATIAL_FACTOR_UNITS.get(factor, '단위 미기재')})",
            )
            for factors in SPATIAL_FACTOR_GROUPS.values()
            for factor in factors
        ]
        selected_fields = [
            (source, label)
            for source, label in [("ADM_NM", "지역"), *grade_fields, *raw_fields]
            if source in available
        ]
        if not selected_fields or selected_fields[0][0] != "ADM_NM":
            raise ValueError("MCP 원자료 확장에 필요한 지역 열이 없습니다.")
        return selected_fields

    def _mcp_dataset(
        self,
        engine,
        region: str,
        focus_names: list[str] | None = None,
        limit: int | None = None,
        selection_ftr_ids: list[str] | None = None,
    ) -> dict:
        selected_fields = self._mcp_dataset_fields(engine)

        select_sql = ", ".join(
            f'"{source}" AS "{label}"'
            for source, label in selected_fields
        )
        # 선택 영역이 있으면 서버가 재계산한 격자 ID로 selected_grid 뷰를
        # 등록하고 그 안에서만 원자료를 뽑는다 — 지도·질의와 같은 A5 원칙.
        source_table = "grid"
        source_label = "duckdb_grid_raw"
        clauses = [self._region_where(region)]
        if selection_ftr_ids:
            register = getattr(engine, "register_selection", None)
            if register is None:
                raise ValueError("선택 영역 조회를 지원하지 않는 데이터 엔진입니다.")
            register(list(selection_ftr_ids))
            source_table = "selected_grid"
            source_label = "duckdb_selected_grid"
            clauses = ["1=1"]
        names = list(dict.fromkeys(
            str(name).strip()
            for name in (focus_names or [])
            if str(name).strip()
        ))[:50]
        if names and not selection_ftr_ids:
            values = ", ".join(f"'{self._quote(name)}'" for name in names)
            clauses.append(f"ADM_NM IN ({values})")
        sql = (
            f"SELECT {select_sql} FROM {source_table} "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY ADM_NM, FTR_IDN"
        )
        count_sql = (
            f"SELECT COUNT(*) AS _mcp_row_count FROM {source_table} "
            f"WHERE {' AND '.join(clauses)}"
        )
        _, count_rows = engine.run(count_sql, limit=1)
        row_count = int(count_rows[0][0]) if count_rows else 0
        requested_limit = max(1, int(limit)) if limit is not None else row_count
        row_limit = min(row_count, requested_limit) if row_count else 1
        columns, rows = engine.run(sql, limit=row_limit)
        return _json_safe({
            "source": source_label,
            "query": sql,
            "columns": list(columns),
            "rows": [list(row) for row in rows],
        })

    @staticmethod
    def _quote(value: str) -> str:
        return value.replace("'", "''")

    @classmethod
    def _region_where(cls, region: str) -> str:
        parts = region.split()
        clauses = [f"SD_NM = '{cls._quote(parts[0])}'"]
        if len(parts) > 1:
            clauses.append(f"SGG_NM = '{cls._quote(' '.join(parts[1:]))}'")
        return " AND ".join(clauses)

    def compare(self, regions: list[str]) -> dict:
        return self._with_engine(lambda engine: self._compare(engine, regions))

    def _compare(self, engine, regions: list[str]) -> dict:
        scoped = " UNION ALL ".join(
            (
                f"SELECT '{self._quote(region)}' AS region_label, "
                f'TRY_CAST("{self.RISK_GRADE}" AS INTEGER) AS grade '
                f"FROM grid WHERE {self._region_where(region)}"
            )
            for region in regions
        )
        summary_sql = f"""
            WITH scoped AS ({scoped})
            SELECT region_label AS region,
                   COUNT(*) AS grid_count,
                   ROUND(AVG(grade), 2) AS avg_grade,
                   SUM(CASE WHEN grade IN (4, 5) THEN 1 ELSE 0 END) AS high_risk_count,
                   ROUND(SUM(CASE WHEN grade IN (4, 5) THEN 1 ELSE 0 END)
                         * 100.0 / NULLIF(COUNT(*), 0), 1) AS high_risk_pct
            FROM scoped
            GROUP BY region_label
            ORDER BY CASE region_label
                {''.join(
                    f" WHEN '{self._quote(item)}' THEN {index}"
                    for index, item in enumerate(regions)
                )}
                ELSE {len(regions)} END
        """.strip()
        distribution_sql = f"""
            WITH scoped AS ({scoped})
            SELECT region_label AS region, grade,
                   COUNT(*) AS count,
                   ROUND(COUNT(*) * 100.0
                         / SUM(COUNT(*)) OVER (PARTITION BY region_label), 1) AS pct
            FROM scoped
            WHERE grade BETWEEN 1 AND 5
            GROUP BY region_label, grade
            ORDER BY region_label, grade
        """.strip()

        summary_columns, summary_rows = engine.run(summary_sql)
        distribution_columns, distribution_rows = engine.run(distribution_sql)
        summary = [
            {
                "region": row[0],
                "grid_count": int(row[1]),
                "avg_grade": float(row[2]) if row[2] is not None else None,
                "high_risk_count": int(row[3]),
                "high_risk_pct": float(row[4]) if row[4] is not None else 0.0,
            }
            for row in summary_rows
        ]
        distribution = {region: [] for region in regions}
        for region, grade, count, pct in distribution_rows:
            distribution.setdefault(region, []).append({
                "grade": str(grade),
                "count": int(count),
                "pct": float(pct),
            })
        leader = max(summary, key=lambda item: item["high_risk_pct"], default=None)
        answer = (
            f"{leader['region']}의 4·5등급 비율이 {leader['high_risk_pct']:.1f}%로 가장 높습니다."
            if leader
            else "비교할 데이터가 없습니다."
        )
        return _json_safe({
            "regions": regions,
            "summary": summary,
            "distribution": distribution,
            "queries": [summary_sql, distribution_sql],
            "results": [
                {"columns": list(summary_columns), "rows": [list(row) for row in summary_rows]},
                {
                    "columns": list(distribution_columns),
                    "rows": [list(row) for row in distribution_rows],
                },
            ],
            "answer": answer,
            "grounded": bool(summary),
        })

    def ask(
        self,
        question: str,
        region: str | None = None,
        scope: str = "selected_region",
        history: list[dict] | None = None,
        analysis_context: dict | None = None,
    ) -> dict:
        return self._with_engine(
            lambda engine: self._ask(
                engine,
                question,
                region=region,
                scope=scope,
                history=history,
                analysis_context=analysis_context,
            )
        )

    def _ask(
        self,
        engine,
        question: str,
        region: str | None = None,
        scope: str = "selected_region",
        history: list[dict] | None = None,
        analysis_context: dict | None = None,
    ) -> dict:
        selected_metric_definition = str(
            (analysis_context or {}).get("metric_definition") or ""
        )
        high_risk_ratio_intent = "비율" in question and (
            "고위험" in question
            or re.search(r"4\s*[·ㆍ,~～-]\s*5\s*등급", question) is not None
        )
        if (
            selected_metric_definition in {"high_risk_ratio", "high_risk_share"}
            and region
            and high_risk_ratio_intent
        ):
            return self._rank_subregions(
                engine,
                question,
                region,
                selected_metric_definition,
            )
        selection = (analysis_context or {}).get("selection") or None
        selected_ftr_ids = list((analysis_context or {}).get("selected_ftr_ids") or [])
        query_engine = (
            _SelectionScopedEngine(
                engine,
                str(selection.get("id") or "selection"),
                selected_ftr_ids,
            )
            if selection
            else engine
        )
        prompt = question
        if scope == "selected_region" and region:
            prompt = (
                f"선택 지역은 '{region}'입니다. 비교를 명시적으로 요청하지 않은 경우 "
                f"모든 SQL을 이 지역으로 제한하세요.\n질문: {question}"
            )
        if analysis_context:
            context_lines = ["구조화된 분석 상태(현재 질문에도 유지):"]
            context_region = analysis_context.get("region")
            if context_region:
                context_lines.append(f"- 기준 지역: {context_region}")
            grades = analysis_context.get("grades") or []
            if grades:
                context_lines.append(
                    f"- 위험성지수 {', '.join(grades)}등급만 SQL 조건에 적용"
                )
            comparisons = analysis_context.get("comparison_regions") or []
            if comparisons:
                context_lines.append(f"- 비교 지역: {', '.join(comparisons)}")
            if selection:
                selection_grades = selection.get("grades") or []
                context_lines.append(
                    f"- 사용자 선택 영역 활성화 · 평가항목 "
                    f"{self._selection_metric_label(selection)} · "
                    f"교차 격자 {len(selected_ftr_ids):,}개"
                )
                if selection_grades:
                    context_lines.append(
                        f"- 공간 선택 당시 등급: {', '.join(selection_grades)}등급"
                    )
                context_lines.append(
                    "- 이 영역·선택 영역은 selected_grid, 지역 전체·비교 기준은 "
                    "grid를 사용하고 현재 지역 조건을 반드시 적용. "
                    "선택 영역 ID를 SQL 조건으로 사용하지 말 것"
                )
            prompt = "\n".join(context_lines) + "\n\n" + prompt
        recent_history = (history or [])[-6:]
        if recent_history:
            lines = []
            for item in recent_history:
                role = "사용자" if item.get("role") == "user" else "어시스턴트"
                content = str(item.get("content", "")).strip()[:1000]
                if content:
                    lines.append(f"{role}: {content}")
            if lines:
                prompt = (
                    "최근 대화 맥락(지시어 해석에만 사용):\n"
                    + "\n".join(lines)
                    + "\n이전 답변의 수치를 재사용하지 말고, "
                    "현재 질문은 새 SQL 조회로 검증하세요.\n\n"
                    + prompt
                )
        prompt = (
            "데이터 설명 원칙:\n"
            "- 결과 원인을 설명할 때 *_표준화 값을 주 설명으로 쓰지 말고, "
            "같은 요인의 *_원자료 값을 주 설명으로 조회하세요. 표준화 값은 보조 근거로만 쓰세요.\n"
            "- 원자료 값은 평균·중앙값·최댓값 등 집계 방식을 밝히고, 반드시 비교 기준값도 "
            "같은 SQL 또는 추가 SQL로 조회해 함께 제시하세요. 기준은 선택 지역 전체 또는 "
            "비교 집단의 평균·중앙값을 우선 사용하세요.\n"
            "- 등급 경계를 설명하려면 등급별 원자료 MIN/MAX를 조회하고 'DB 관측 경계'라고 "
            "표시하세요. 제공 자료에 없는 공식 임계값이나 법정 기준을 추정하지 마세요.\n"
            "- 확인된 원자료 단위: 강우는 mm/h, 강풍은 m/s, 파랑·해일은 m, "
            "해수면 상승은 mm/yr, 인구·고령인구는 명, 건물·도로·양식장·농경지·"
            "산업단지·발전시설·공항·어항·항만·시설재배·침수면적·지하·반지하·문화재는 m²입니다.\n"
            "- 저감능력 단위: 대피소는 인구 1명당 수용인원(명), 재난재해관리기금은 "
            "인구 1명당 관리기금액(원), 공무원수는 인구 1만 명당 공무원 수(명), "
            "지역자율방재단은 인구 1만 명당 방재단 수(명), 시민안전보험은 원입니다.\n"
            "- 위험시설물·급경사지·침식지역은 등급(범주형)입니다. 기준표에 없는 "
            "원자료만 '단위 미기재'라고 표시하고 임의로 추정하지 마세요. 격자 수는 개, "
            "비율은 %, 표준화 값은 무단위, 등급은 1~5등급으로 표기하세요.\n\n"
            + prompt
        )
        response = self.ask_fn(prompt, engine=query_engine)
        queries = (
            [query_engine.validate(sql) for sql in response.get("queries", [])]
            if selection
            else list(response.get("queries", []))
        )
        scope_valid = True
        if selection:
            uses_selection = self._uses_relation(queries, "selected_grid")
            needs_baseline = bool(
                re.search(r"전체|비교|대비|기준", question)
                or (analysis_context or {}).get("comparison_regions")
            )
            uses_baseline = self._uses_relation(queries, "grid")
            baseline_scoped = self._baseline_is_region_scoped(queries, region)
            scope_valid = uses_selection and (
                not needs_baseline or (uses_baseline and baseline_scoped)
            )
        result_tables = []
        for sql in queries:
            columns, rows = engine.run(sql)
            result_tables.append(
                {"columns": list(columns), "rows": [list(row) for row in rows]}
            )
        answer = response.get("answer", "")
        if selection and not scope_valid:
            answer = (
                "선택 영역과 지역 전체 등 비교 범위를 함께 조회하지 못해 "
                "답변을 확정하지 않았습니다. 질문을 다시 실행해 주세요."
            )
        return _json_safe({
            "question": question,
            "region": region,
            "answer": answer,
            "queries": queries,
            "results": result_tables,
            "grounded": bool(response.get("grounded")) and scope_valid,
            "scope_valid": scope_valid,
            "scope": (
                {
                    "type": "spatial_selection",
                    "selection_id": str(selection.get("id") or "selection"),
                    "selected_count": len(selected_ftr_ids),
                }
                if selection
                else None
            ),
        })

    def _rank_subregions(
        self,
        engine,
        question: str,
        region: str,
        metric_id: str,
    ) -> dict:
        where = self._region_where(region)
        if metric_id == "high_risk_share":
            sql = f"""
                WITH high_risk AS (
                    SELECT ADM_NM AS region,
                           COUNT(*) AS high_risk_count
                    FROM grid
                    WHERE {where}
                      AND TRY_CAST(\"{self.RISK_GRADE}\" AS INTEGER) IN (4, 5)
                    GROUP BY ADM_NM
                )
                SELECT region,
                       high_risk_count,
                       SUM(high_risk_count) OVER () AS total_high_risk_count,
                       ROUND(high_risk_count * 100.0
                             / NULLIF(SUM(high_risk_count) OVER (), 0), 1) AS high_risk_pct
                FROM high_risk
                ORDER BY high_risk_pct DESC, region
                LIMIT 5
            """.strip()
            denominator_text = "상위 지역 전체 고위험 격자"
        else:
            sql = f"""
                SELECT ADM_NM AS region,
                       COUNT(*) FILTER (
                           WHERE TRY_CAST(\"{self.RISK_GRADE}\" AS INTEGER) IN (4, 5)
                       ) AS high_risk_count,
                       COUNT(*) AS total_count,
                       ROUND(COUNT(*) FILTER (
                           WHERE TRY_CAST(\"{self.RISK_GRADE}\" AS INTEGER) IN (4, 5)
                       ) * 100.0 / NULLIF(COUNT(*), 0), 1) AS high_risk_pct
                FROM grid
                WHERE {where}
                GROUP BY ADM_NM
                ORDER BY high_risk_pct DESC, region
                LIMIT 5
            """.strip()
            denominator_text = "해당 읍면동 전체 격자"
        columns, rows = engine.run(sql)
        definition = metric_definition(metric_id) or {"id": metric_id}
        if rows:
            leader = rows[0]
            answer = (
                f"{leader[0]}의 고위험 비율이 {float(leader[3]):.1f}%로 가장 높습니다. "
                f"분모는 {denominator_text}입니다."
            )
        else:
            answer = "조건에 해당하는 격자가 없습니다."
        return _json_safe({
            "question": question,
            "region": region,
            "answer": answer,
            "queries": [sql],
            "results": [{"columns": list(columns), "rows": [list(row) for row in rows]}],
            "grounded": True,
            "scope_valid": True,
            "scope": None,
            "metric_definition": definition,
        })


class ReportManager:
    def __init__(
        self,
        graph_factory=None,
        output_root: Path | str | None = None,
        auto_start: bool = True,
        revision_fn=None,
        query_engine_factory=None,
        spatial_export_root: Path | str | None = None,
        mcp_output_root: Path | str | None = None,
        on_update=None,
        should_cancel=None,
    ):
        if graph_factory is None:
            _, graph_factory, _ = _load_agent_modules()
        self.graph_factory = graph_factory
        self.output_root = Path(output_root or WEB_ROOT / "outputs" / "jobs")
        self.auto_start = auto_start
        self.revision_fn = revision_fn or self._rewrite_section_with_llm
        self.query_engine_factory = query_engine_factory
        self.spatial_export_root = Path(spatial_export_root or SPATIAL_EXPORT_ROOT)
        self.mcp_output_root = Path(mcp_output_root or MCP_OUTPUT_ROOT)
        self.on_update = on_update
        self.should_cancel = should_cancel
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report-job")

    def create(
        self,
        options: dict,
        owner_id: str | None = None,
        job_id: str | None = None,
    ) -> dict:
        job_id = job_id or uuid.uuid4().hex[:12]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", job_id):
            raise ValueError("올바르지 않은 작업 ID입니다.")
        if owner_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", owner_id):
            raise ValueError("올바르지 않은 사용자 ID입니다.")
        job_dir = self.output_root / owner_id / job_id if owner_id else self.output_root / job_id
        figure_dir = job_dir / "figures"
        report_dir = job_dir / "reports"
        for directory in (figure_dir, report_dir, job_dir / "drafts", job_dir / "traces"):
            directory.mkdir(parents=True, exist_ok=True)
        record = {
            "job_id": job_id,
            "status": "queued",
            "stage": None,
            "progress": 0,
            "result": {},
            "errors": [],
            "events": [],
            "options": dict(options),
            "owner_id": owner_id,
            "job_dir": str(job_dir),
            "figure_dir": str(figure_dir),
            "report_dir": str(report_dir),
        }
        with self.lock:
            self.jobs[job_id] = record
        self._notify(record)
        if self.auto_start:
            self.executor.submit(self.run, job_id)
        return {"job_id": job_id, "status": "queued"}

    def restore(self, saved: dict, *, materials: list[dict]) -> None:
        job_id = saved["job_id"]
        owner_id = saved["user_id"]
        job_dir = self.output_root / owner_id / job_id
        record = {
            "job_id": job_id,
            "status": saved["status"],
            "stage": saved["stage"],
            "progress": saved["progress"],
            "result": dict(saved["result"]),
            "errors": list(saved["errors"]),
            "events": [],
            "options": {**saved["options"], "materials": materials},
            "owner_id": owner_id,
            "job_dir": str(job_dir),
            "figure_dir": str(job_dir / "figures"),
            "report_dir": str(job_dir / "reports"),
        }
        with self.lock:
            self.jobs[job_id] = record

    def _notify(self, record: dict) -> None:
        if self.on_update is None:
            return
        snapshot = self.get(record["job_id"])
        snapshot["result"] = dict(snapshot["result"])
        snapshot["errors"] = list(snapshot["errors"])
        self.on_update(snapshot)

    def _cancel_requested(self, record: dict) -> bool:
        if self.should_cancel is None or not self.should_cancel(record["job_id"]):
            return False
        record["status"] = "cancelled"
        record["events"].append(
            {
                "index": len(record["events"]),
                "type": "job_cancelled",
                "stage": record["stage"],
                "data": {},
            }
        )
        self._notify(record)
        return True

    def _event(self, record: dict, stage: str, data: dict | None = None):
        record["events"].append(
            {
                "index": len(record["events"]),
                "type": "stage_completed" if stage != "completed" else "job_completed",
                "stage": stage,
                "data": data or {},
            }
        )

    def run(self, job_id: str):
        record = self.jobs[job_id]
        record["status"] = "running"
        self._notify(record)
        if self._cancel_requested(record):
            return
        options = record["options"]
        initial_state = {
            **options,
            "errors": [],
            "job_dir": record["job_dir"],
            "figure_dir": record["figure_dir"],
            "report_dir": record["report_dir"],
        }
        original_config = None
        try:
            source = agent_root() / "src"
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            try:
                from coastal_agent import config

                original_config = (config.FIGURE_DIR, config.REPORT_DIR)
                config.FIGURE_DIR = Path(record["figure_dir"])
                config.REPORT_DIR = Path(record["report_dir"])
            except ImportError:
                config = None

            graph = self.graph_factory()
            for chunk in graph.stream(initial_state, stream_mode="updates"):
                for stage, update in chunk.items():
                    public_update = {
                        key: value for key, value in update.items() if key in PUBLIC_KEYS
                    }
                    record["result"].update(public_update)
                    if stage == "compose":
                        self._append_materials(record)
                    if stage == "convert":
                        self._rebuild_hwpx_with_material_images(record)
                    record["stage"] = stage
                    record["progress"] = STAGES.index(stage) + 1 if stage in STAGES else 0
                    record["errors"] = list(public_update.get("errors", record["errors"]))
                    self._event(record, stage, public_update)
                    self._notify(record)
                    if self._cancel_requested(record):
                        return
            record["status"] = "completed"
            record["progress"] = len(STAGES)
            self._event(record, "completed", record["result"])
            self._notify(record)
        except Exception as error:
            record["status"] = "failed"
            record["errors"].append(str(error))
            record["events"].append(
                {
                    "index": len(record["events"]),
                    "type": "job_failed",
                    "stage": record["stage"],
                    "data": {"error": str(error)},
                }
            )
            self._notify(record)
        finally:
            if original_config is not None:
                config.FIGURE_DIR, config.REPORT_DIR = original_config

    @staticmethod
    def _markdown_cell(value) -> str:
        return str(value if value is not None else "—").replace("|", "\\|")

    def _append_materials(self, record: dict) -> None:
        materials = record["options"].get("materials") or []
        raw_path = record["result"].get("report_md_path")
        if not materials or not raw_path:
            return
        path = Path(raw_path)
        lines = ["", "## 대화에서 선택한 추가 분석", ""]
        material_images = {}
        for index, material in enumerate(materials, 1):
            question = str(material.get("question", "")).strip()
            answer = str(material.get("answer", "")).strip()
            lines += [f"### 추가 분석 {index}. {question}", ""]
            if material.get("region"):
                lines += [f"**대상 지역:** {material['region']}", ""]
            lines += [answer, ""]
            spatial_image = material.get("spatial_image") or {}
            image_id = str(spatial_image.get("image_id", ""))
            source_root = self.spatial_export_root
            if record.get("owner_id"):
                source_root = source_root / record["owner_id"]
            source = source_root / f"{image_id}.png"
            if image_id and Path(image_id).name == image_id and source.is_file():
                target = Path(record["figure_dir"]) / f"selected_map_{index}.png"
                shutil.copy2(source, target)
                caption = str(spatial_image.get("caption") or question).strip()
                lines += [f"![{caption}](../figures/{target.name})", ""]
                material_images[caption] = str(target)
            mcp_chart = material.get("mcp_chart") or {}
            analysis_id = str(mcp_chart.get("analysis_id", ""))
            asset_name = str(mcp_chart.get("asset_name", ""))
            mcp_source_root = self.mcp_output_root
            if record.get("owner_id"):
                mcp_source_root = mcp_source_root / record["owner_id"]
            mcp_source = mcp_source_root / analysis_id / asset_name
            if (
                re.fullmatch(r"[A-Fa-f0-9]{32}", analysis_id)
                and Path(asset_name).name == asset_name
                and mcp_source.is_file()
            ):
                target = Path(record["figure_dir"]) / f"selected_mcp_{index}.png"
                shutil.copy2(mcp_source, target)
                caption = str(mcp_chart.get("caption") or question).strip()
                lines += [f"![{caption}](../figures/{target.name})", ""]
                material_images[caption] = str(target)
            for table in material.get("results") or []:
                columns = table.get("columns") or []
                rows = table.get("rows") or []
                if not columns:
                    continue
                lines.append("| " + " | ".join(map(self._markdown_cell, columns)) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in rows:
                    lines.append("| " + " | ".join(map(self._markdown_cell, row)) + " |")
                lines.append("")
            for sql in material.get("queries") or []:
                lines += ["```sql", str(sql).strip(), "```", ""]
        with path.open("a", encoding="utf-8") as report:
            report.write("\n".join(lines).rstrip() + "\n")
        record["result"]["material_count"] = len(materials)
        if material_images:
            record["result"]["material_images"] = material_images

    def _rebuild_hwpx_with_material_images(self, record: dict) -> None:
        material_images = record["result"].get("material_images") or {}
        raw_markdown = record["result"].get("report_md_path")
        raw_hwpx = record["result"].get("report_hwpx_path")
        if not material_images or not raw_markdown or not raw_hwpx:
            return

        from coastal_agent import config
        from coastal_agent.hwpx_images import embed_images
        from coastal_agent.nodes.convert import _report_style

        markdown = Path(raw_markdown)
        hwpx = Path(raw_hwpx)
        command = [
            "node",
            str(config.PROJECT_ROOT / "scripts" / "md2hwpx.mjs"),
            str(markdown),
            str(hwpx),
            json.dumps(_report_style(), ensure_ascii=False),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            cwd=config.PROJECT_ROOT,
        )
        if result.returncode != 0 or not hwpx.is_file():
            record["errors"].append(
                f"convert: 선택 지도 포함 HWPX 변환 실패 — {result.stderr.strip()[:500]}"
            )
            return

        figure_labels = {
            "grade_dist": "위험성지수 등급별 격자 분포",
            "risk_map": "연안재해 위험성지수 등급 분포도",
            "grade_stack": "지역별 위험성 등급 구성",
            "region_ranking": "지역별 고위험 격자 비율 상위",
            "factor_lift": "고위험 지역 요인 집중도",
            "factor_grid_map": "주요 요인별 격자 등급 분포",
        }
        figures = record["result"].get("figures") or {}
        images = {
            label: Path(figures[key])
            for key, label in figure_labels.items()
            if key in figures
        }
        images.update({caption: Path(path) for caption, path in material_images.items()})
        notes = embed_images(hwpx, images)
        record["errors"] += [f"convert: {note}" for note in notes if "미발견" in note]

    @staticmethod
    def _section_key(value: str) -> str:
        return re.sub(r"[^가-힣A-Za-z]", "", value).lower()

    @staticmethod
    def _section_title(value: str) -> str:
        return re.sub(r"^\d+(?:\.\d+)*\s*", "", value).strip()

    def _find_section(self, markdown: str, requested: str):
        headings = list(re.finditer(r"(?m)^(#{2,3})\s+(.+?)\s*$", markdown))
        requested_key = self._section_key(requested)
        for index, heading in enumerate(headings):
            heading_key = self._section_key(heading.group(2))
            if requested_key and requested_key not in heading_key:
                continue
            end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
            return heading, end
        raise ValueError(f"보고서에서 '{requested}' 섹션을 찾을 수 없습니다.")

    @staticmethod
    def _rewrite_section_with_llm(
        section: str,
        current: str,
        instruction: str,
        evidence: dict,
    ) -> str:
        from coastal_agent import config
        from coastal_agent.llm import make_llm, provider

        if provider() is None:
            raise RuntimeError("보고서 부분 수정에는 LLM API 키가 필요합니다.")
        prompt = (
            f"수정 대상 섹션: {section}\n\n현재 섹션:\n{current}\n\n"
            f"수정 요청:\n{instruction}\n\n근거 데이터(JSON):\n"
            f"{json.dumps(evidence, ensure_ascii=False, default=str)}\n\n"
            "현재 섹션의 Markdown 본문만 출력하세요. 제목은 출력하지 마세요. "
            "근거 데이터에 없는 수치나 지역명은 만들지 마세요."
        )
        response = make_llm(config.LLM_MAX_TOKENS).invoke(
            [
                (
                    "system",
                    "당신은 검증된 통계 보고서의 한 섹션만 수정하는 편집자입니다.",
                ),
                ("user", prompt),
            ]
        )
        content = response.content
        text = content if isinstance(content, str) else content[0]["text"]
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            text = text[8:] if text.startswith("markdown") else text
        return text.strip()

    def revise(self, job_id: str, section: str, instruction: str) -> dict:
        record = self.jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if record["status"] != "completed":
            raise RuntimeError("완료된 보고서만 수정할 수 있습니다.")
        source = self.file(job_id, "md")
        if source is None:
            raise RuntimeError("수정할 Markdown 보고서가 없습니다.")

        markdown = source.read_text(encoding="utf-8")
        heading, end = self._find_section(markdown, section)
        current = markdown[heading.start():end].strip()
        title = self._section_title(heading.group(2))
        evidence_stats = dict(record["result"].get("stats") or {})
        materials = record["options"].get("materials") or []
        evidence = {"stats": evidence_stats, "materials": materials}
        rewritten = self.revision_fn(title, current, instruction, evidence).strip()
        if not rewritten:
            raise ValueError("수정된 섹션이 비어 있습니다.")

        from coastal_agent.nodes.verify import (
            allowed_numbers,
            check_numbers,
            check_region_names,
            known_names,
        )

        validation_stats = {**evidence_stats, "대화추가분석": materials}
        bad_numbers = check_numbers(rewritten, allowed_numbers(validation_stats))
        bad_regions = check_region_names(
            rewritten,
            known_names(validation_stats, record["options"].get("region") or "전국"),
        )
        if bad_numbers or bad_regions:
            issues = [f"근거 없는 수치: {value}" for value in bad_numbers]
            issues += [f"미확인 지역명: {value}" for value in bad_regions]
            raise ValueError("부분 수정 검증 실패 — " + ", ".join(issues))

        replacement = f"{heading.group(1)} {heading.group(2)}\n\n{rewritten}\n\n"
        revised_markdown = markdown[:heading.start()] + replacement + markdown[end:]
        revision_number = int(record["result"].get("revision_count", 0)) + 1
        base_name = re.sub(r"_v\d+$", "", source.stem)
        target = source.parent / f"{base_name}_v{revision_number + 1}.md"
        target.write_text(revised_markdown.rstrip() + "\n", encoding="utf-8")

        record["result"].setdefault("base_report_md_path", str(source))
        record["result"]["report_md_path"] = str(target)
        record["result"]["revision_count"] = revision_number
        revision = {
            "revision": revision_number,
            "section": heading.group(2),
            "instruction": instruction,
            "report_md_path": str(target),
        }
        record["result"].setdefault("revisions", []).append(revision)
        record["result"].pop("report_hwpx_path", None)

        if record["options"].get("make_hwpx", True):
            from coastal_agent.nodes.convert import convert

            converted = convert({
                "report_md_path": str(target),
                "make_hwpx": True,
                "figures": record["result"].get("figures", {}),
                "errors": record["errors"],
            })
            record["result"]["report_hwpx_path"] = converted.get(
                "report_hwpx_path",
                "",
            )
            record["errors"] = converted.get("errors", record["errors"])
        return revision

    def save_content(self, job_id: str, markdown: str) -> dict:
        record = self.jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if record["status"] != "completed":
            raise RuntimeError("완료된 보고서만 직접 편집할 수 있습니다.")
        source = self.file(job_id, "md")
        if source is None:
            raise RuntimeError("편집할 Markdown 보고서가 없습니다.")

        revised_markdown = markdown.rstrip() + "\n"
        if not revised_markdown.strip():
            raise ValueError("보고서 본문은 비워둘 수 없습니다.")
        current_markdown = source.read_text(encoding="utf-8")
        if revised_markdown == current_markdown:
            raise ValueError("변경된 내용이 없습니다.")

        from coastal_agent.nodes.verify import (
            allowed_numbers,
            check_numbers,
            check_region_names,
            known_names,
        )

        stats = {
            **dict(record["result"].get("stats") or {}),
            "대화추가분석": record["options"].get("materials") or [],
        }
        allowed = allowed_numbers(stats)
        names = known_names(stats, record["options"].get("region") or "전국")
        existing_bad_numbers = set(check_numbers(current_markdown, allowed))
        existing_bad_regions = set(check_region_names(current_markdown, names))
        bad_numbers = [
            value for value in check_numbers(revised_markdown, allowed)
            if value not in existing_bad_numbers
        ]
        bad_regions = [
            value for value in check_region_names(revised_markdown, names)
            if value not in existing_bad_regions
        ]
        if bad_numbers or bad_regions:
            issues = [f"근거 없는 수치: {value}" for value in bad_numbers]
            issues += [f"미확인 지역명: {value}" for value in bad_regions]
            raise ValueError("직접 편집 검증 실패 — " + ", ".join(issues))

        revision_number = int(record["result"].get("revision_count", 0)) + 1
        base_name = re.sub(r"_v\d+$", "", source.stem)
        target = source.parent / f"{base_name}_v{revision_number + 1}.md"
        target.write_text(revised_markdown, encoding="utf-8")

        record["result"].setdefault("base_report_md_path", str(source))
        record["result"]["report_md_path"] = str(target)
        record["result"]["revision_count"] = revision_number
        revision = {
            "revision": revision_number,
            "mode": "direct_edit",
            "section": "전체 보고서",
            "report_md_path": str(target),
        }
        record["result"].setdefault("revisions", []).append(revision)
        record["result"].pop("report_hwpx_path", None)

        if record["options"].get("make_hwpx", True):
            from coastal_agent.nodes.convert import convert

            converted = convert({
                "report_md_path": str(target),
                "make_hwpx": True,
                "figures": record["result"].get("figures", {}),
                "errors": record["errors"],
            })
            record["result"]["report_hwpx_path"] = converted.get(
                "report_hwpx_path",
                "",
            )
            record["errors"] = converted.get("errors", record["errors"])
        return revision

    def run_edit(self, job_id: str, operation: str, payload: dict) -> dict:
        record = self.jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        record["status"] = "running"
        record["stage"] = "revision"
        self._notify(record)
        record["status"] = "completed"
        try:
            if operation == "revision":
                result = self.revise(
                    job_id,
                    str(payload.get("section", "")),
                    str(payload.get("instruction", "")),
                )
            elif operation == "content":
                result = self.save_content(job_id, str(payload.get("markdown", "")))
            else:
                raise ValueError(f"지원하지 않는 보고서 편집 작업입니다: {operation}")
            record["status"] = "completed"
            record["stage"] = "revision"
            self._event(record, "completed", {"revision": result})
            self._notify(record)
            return result
        except Exception as error:
            record["status"] = "failed"
            record["errors"].append(str(error))
            record["events"].append({
                "index": len(record["events"]),
                "type": "job_failed",
                "stage": "revision",
                "data": {"error": str(error)},
            })
            self._notify(record)
            raise

    def get(self, job_id: str) -> dict | None:
        record = self.jobs.get(job_id)
        if record is None:
            return None
        return {
            key: record[key]
            for key in ("job_id", "status", "stage", "progress", "result", "errors")
        }

    @staticmethod
    def _sentences(markdown: str) -> list[dict]:
        sentences = []
        in_code = False
        current_section = ""
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                in_code = not in_code
                continue
            if not in_code and line.startswith("#"):
                current_section = re.sub(r"^#+\s*", "", line).strip()
                continue
            plain = re.sub(r"[*_`>]", "", line).strip()
            if (
                in_code
                or not line
                or line.startswith(("#", "|", "![", "---"))
                or re.match(r"^(작성일|기준일|생성일)\s*:", plain)
                or re.fullmatch(r"\d+\.", plain)
                or re.match(r"^-\s*\d+(?:\.\d+)+\s+", plain)
                or plain.startswith(("<표 ", "<그림 "))
            ):
                continue
            plain = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", plain)
            sentences.extend(
                {"sentence": part.strip(), "section": current_section}
                for part in re.split(r"(?<=[.!?])\s+", plain)
                if part.strip()
            )
        return sentences

    @classmethod
    def _flatten_stats(cls, value, path: str = "") -> list[dict]:
        if isinstance(value, dict):
            items = []
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                items.extend(cls._flatten_stats(child, child_path))
            return items
        if isinstance(value, list):
            items = []
            for index, child in enumerate(value, 1):
                label = index
                if isinstance(child, dict):
                    label = next(
                        (
                            child[key]
                            for key in ("지역", "지역명", "시군구", "요인", "항목")
                            if key in child
                        ),
                        index,
                    )
                child_path = f"{path}.{label}" if path else str(label)
                items.extend(cls._flatten_stats(child, child_path))
            return items
        scalar = value.item() if hasattr(value, "item") else value
        return [{"path": path, "value": scalar}]

    @staticmethod
    def _number(value) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            return float(str(value).replace(",", "").replace("%", ""))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _matching_stats(cls, sentence: str, stats: dict, section: str = "") -> list[dict]:
        sentence_numbers = set()
        number_pattern = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
        for match in re.finditer(number_pattern, sentence):
            trailing = sentence[match.end():]
            if (
                re.match(r"\s*등급", trailing)
                or re.match(r"\s*[~～-]\s*\d+(?:\.\d+)?\s*등급", trailing)
            ):
                continue
            sentence_numbers.add(float(match.group().replace(",", "")))
        if (
            re.search(r"\d+\s*등급.*부터.*\d+\s*등급.*까지", sentence)
            or ("표준화" in sentence and re.search(r"\d+\s*[~～-]\s*\d+", sentence))
        ):
            sentence_numbers.clear()
        if not sentence_numbers:
            return []
        matches = []
        for item in cls._flatten_stats(stats):
            number = cls._number(item["value"])
            if number is not None and any(
                abs(number - target) < 1e-9 for target in sentence_numbers
            ):
                matches.append(item)

        explicit_matches = []
        for item in matches:
            segments = str(item["path"]).split(".")[1:-1]
            subjects = [
                segment
                for segment in segments
                if not re.fullmatch(r"\d+(?:등급)?", segment)
            ]
            if any(subject in sentence for subject in subjects):
                explicit_matches.append(item)
        if explicit_matches:
            matches = explicit_matches

        if "고위험" in sentence and "비율" in sentence:
            distribution = stats.get("위험성등급분포", {})
            grade_4 = distribution.get("4", distribution.get(4, {}))
            grade_5 = distribution.get("5", distribution.get(5, {}))
            pct_4 = cls._number(grade_4.get("pct")) if isinstance(grade_4, dict) else None
            pct_5 = cls._number(grade_5.get("pct")) if isinstance(grade_5, dict) else None
            if pct_4 is not None and pct_5 is not None:
                high_risk_pct = round(pct_4 + pct_5, 1)
                if any(abs(high_risk_pct - target) < 1e-9 for target in sentence_numbers):
                    return [{
                        "path": "위험성등급분포.4.pct + 위험성등급분포.5.pct",
                        "value": high_risk_pct,
                    }]
        if len(matches) <= 1:
            return matches

        root_hints = {
            "데이터개요": ("평가 대상", "총 격자", "데이터", "결측"),
            "위험성등급분포": ("위험성", "위험 등급"),
            "복합지수등급분포": ("복합지수", "복합 지수"),
            "시군구별순위": ("시군구", "순위", "고위험"),
            "지역별등급구성": ("지역별", "읍면동", "등급 구성"),
            "하위지역단위": ("읍면동", "하위지역"),
            "고위험지역프로파일": ("고위험지역", "고위험 지역"),
            "요인기여도": ("기여도", "상승배율", "요인"),
            "주요요인원자료": ("원자료", "실측치", "요인"),
            "요인원자료전체": ("원자료", "실측치", "요인"),
            "요인별등급분포": ("요인별", "요인 등급"),
        }

        def relevance(item: dict) -> int:
            path = item["path"]
            root = path.split(".", 1)[0]
            context = f"{section} {sentence}"
            score = sum(4 for hint in root_hints.get(root, ()) if hint in context)
            score += sum(
                1
                for token in re.findall(r"[가-힣A-Za-z_]{2,}", path)
                if token in context
            )
            return score

        scored = [(relevance(item), item) for item in matches]
        best = max(score for score, _ in scored)
        if best == 0:
            return []
        return [item for score, item in scored if score == best][:8]

    @staticmethod
    def _query_score(path: str, sentence: str, sql: str) -> int:
        root = path.split(".", 1)[0]
        checks = {
            "데이터개요": ("total_count", "missing_risk_grade"),
            "위험성등급분포": ("grade_count", "위험성지수_등급"),
            "복합지수등급분포": ("grade_count", "복합"),
            "시군구별순위": ("region_name", "high_pct", "grid_count"),
            "지역별등급구성": ("partition by region_name", "grade_count"),
            "요인기여도": ("factor_values", "overall_avg", "lift"),
            "주요요인원자료": ("mean_value", "median_value", "max_value"),
            "요인원자료전체": ("mean_value", "median_value", "max_value"),
            "요인별등급분포": ("factor_grades", "grade_1"),
        }
        lowered = sql.lower()
        score = sum(2 for token in checks.get(root, ()) if token.lower() in lowered)
        score += sum(
            1
            for token in re.findall(r"[가-힣A-Za-z_]{3,}", path + " " + sentence)
            if token.lower() in lowered
        )
        return score

    @classmethod
    def _related_queries(
        cls,
        stats_matches: list[dict],
        sentence: str,
        trace: dict,
    ) -> list[dict]:
        if not stats_matches:
            return []
        candidates = []
        path = " ".join(item["path"] for item in stats_matches)
        for query in trace.get("queries", []) if isinstance(trace, dict) else []:
            sql = str(query.get("sql", "")).strip()
            if not sql:
                continue
            score = cls._query_score(path, sentence, sql)
            if score:
                candidates.append((score, query))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "sql": item.get("sql", ""),
                "status": item.get("status", "unknown"),
                "row_count": item.get("row_count", 0),
            }
            for _, item in candidates[:1]
        ]

    @staticmethod
    def _gpkg_fields(sentence: str, queries: list[dict]) -> list[str]:
        sql = " ".join(str(query.get("sql", "")) for query in queries)
        fields = []
        if "격자" in sentence or "FTR_IDN" in sql:
            fields.append("FTR_IDN")
        semantic_fields = [
            "SD_NM",
            "SGG_NM",
            "ADM_NM",
            "위해성지수_등급",
            "노출성지수_등급",
            "취약성지수(가중)_등급",
            "취약성지수(저감)_등급",
            "위험성지수_등급",
        ]
        for field in semantic_fields:
            keyword = field.split("지수", 1)[0]
            if field in sql or keyword in sentence:
                fields.append(field)
        return list(dict.fromkeys(fields))

    @staticmethod
    def _map_context(sentence: str, stats_matches: list[dict], region: str | None) -> dict:
        names = []
        for item in stats_matches:
            names.extend(
                segment
                for segment in str(item.get("path", "")).split(".")
                if re.fullmatch(r"[가-힣0-9·]+(?:동|읍|면)", segment)
            )

        grades = []
        for start, end in re.findall(r"([1-5])\s*[·~～-]\s*([1-5])\s*등급", sentence):
            grades.extend([start, end])
        grades.extend(re.findall(r"([1-5])\s*등급", sentence))
        evidence_text = " ".join([
            sentence,
            *(str(item.get("path", "")) for item in stats_matches),
        ])
        metric_id = "overall"
        metric_aliases = [
            ("reduction", ("취약성(저감능력)", "취약성지수(저감)", "저감능력")),
            ("sensitivity", ("취약성(민감도)", "취약성지수(가중)", "민감도")),
            ("exposure", ("노출성지수", "노출성")),
            ("hazard", ("위해성지수", "위해성")),
        ]
        factor_metrics = sorted(
            (
                (metric["id"], metric["label"])
                for metric in SPATIAL_GRADE_METRICS
                if metric["group"] not in {"종합", "복합지수"}
            ),
            key=lambda item: len(item[1]),
            reverse=True,
        )
        for candidate_id, label in factor_metrics:
            if label in evidence_text:
                metric_id = candidate_id
                break
        else:
            for candidate_id, aliases in metric_aliases:
                if any(alias in evidence_text for alias in aliases):
                    metric_id = candidate_id
                    break
        return {
            "region": region,
            "adm_names": list(dict.fromkeys(names)),
            "grades": sorted(set(grades)),
            "metric_id": metric_id,
        }

    def provenance(self, job_id: str, evidence_id: str | None = None):
        record = self.jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        report = self.file(job_id, "md")
        if report is None:
            raise RuntimeError("근거를 추적할 Markdown 보고서가 없습니다.")

        result = record.get("result", {})
        stats = result.get("stats") or {}
        trace = result.get("analysis_trace") or {}
        materials = record.get("options", {}).get("materials") or []
        entries = []
        sentences = self._sentences(report.read_text(encoding="utf-8"))
        for index, sentence_record in enumerate(sentences, 1):
            sentence = sentence_record["sentence"]
            stats_matches = self._matching_stats(sentence, stats, sentence_record["section"])
            queries = self._related_queries(stats_matches, sentence, trace)
            material_index = None
            for candidate_index, material in enumerate(materials):
                answer = str(material.get("answer", "")).strip()
                if answer and (sentence in answer or answer in sentence):
                    material_index = candidate_index
                    stats_matches = [{
                        "path": f"대화추가분석.{candidate_index + 1}.답변",
                        "value": answer,
                    }]
                    queries = [
                        {"sql": sql, "status": "ok", "row_count": 0}
                        for sql in material.get("queries") or []
                    ]
                    break
            entries.append({
                "id": f"s{index}",
                "sentence": sentence,
                "grounded": bool(stats_matches),
                "stats": stats_matches,
                "gpkg_fields": self._gpkg_fields(sentence, queries),
                "queries": queries,
                "map_context": self._map_context(
                    sentence,
                    stats_matches,
                    record.get("options", {}).get("region"),
                ),
                "material_index": material_index,
            })

        if evidence_id is None:
            return [
                {key: value for key, value in entry.items() if key != "material_index"}
                for entry in entries
            ]
        selected = next((entry for entry in entries if entry["id"] == evidence_id), None)
        if selected is None:
            raise KeyError(evidence_id)

        detailed_queries = []
        material_index = selected.pop("material_index")
        material = materials[material_index] if material_index is not None else None
        for index, query in enumerate(selected["queries"]):
            detail = dict(query)
            if material is not None and index < len(material.get("results") or []):
                table = material["results"][index]
                detail["columns"] = list(table.get("columns") or [])
                detail["rows"] = [list(row) for row in table.get("rows") or []]
            else:
                try:
                    engine_factory = self.query_engine_factory
                    if engine_factory is None:
                        engine_factory, _, _ = _load_agent_modules()
                    columns, rows = engine_factory().run(query["sql"], limit=20)
                    detail["columns"] = list(columns)
                    detail["rows"] = [list(row) for row in rows]
                except Exception as error:
                    detail["error"] = str(error)
            detailed_queries.append(detail)
        selected["queries"] = detailed_queries
        return selected

    def events(self, job_id: str) -> list[dict]:
        record = self.jobs.get(job_id)
        return list(record["events"]) if record else []

    def file(self, job_id: str, kind: str) -> Path | None:
        record = self.jobs.get(job_id)
        result_key = {"md": "report_md_path", "hwpx": "report_hwpx_path"}.get(kind)
        if record is None or result_key is None:
            return None
        raw_path = record["result"].get(result_key)
        if not raw_path:
            return None
        path = Path(raw_path).resolve()
        job_dir = Path(record["job_dir"]).resolve()
        if job_dir not in path.parents or not path.is_file():
            return None
        return path

    def asset(self, job_id: str, name: str) -> Path | None:
        record = self.jobs.get(job_id)
        if record is None or Path(name).name != name:
            return None
        figure_dir = Path(record["figure_dir"]).resolve()
        path = (figure_dir / name).resolve()
        if figure_dir not in path.parents or not path.is_file():
            return None
        return path
