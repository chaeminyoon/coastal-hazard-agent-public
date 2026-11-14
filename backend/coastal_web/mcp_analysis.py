import csv
import json
import os
import re
import subprocess
import sys
import time
import uuid
from math import sqrt
from pathlib import Path
from typing import Any, Callable

CHART_TYPES = {
    "bar",
    "stacked_bar",
    "line",
    "area",
    "scatter",
    "histogram",
    "boxplot",
    "violin",
    "correlation_heatmap",
    "pivot_heatmap",
}

CHART_REQUIRED_COLUMNS = {
    "bar": ("x_column",),
    "stacked_bar": ("x_column", "stack_column"),
    "line": ("x_column", "y_column"),
    "area": ("x_column", "y_column"),
    "scatter": ("x_column", "y_column"),
    "histogram": ("x_column",),
    "boxplot": ("y_column",),
    "violin": ("y_column",),
    "correlation_heatmap": (),
    "pivot_heatmap": ("x_column", "group_column", "y_column"),
}

SAFE_ENVIRONMENT_KEYS = {
    "HOME",
    "LANG",
    "LC_ALL",
    "MPLCONFIGDIR",
    "PATH",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
}
SAFE_OWNER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
READINESS_FAILURE_TTL_SECONDS = 30


def _number(value: float) -> int | float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def _format_number(value: int | float) -> str:
    return f"{value:,}"


def _apply_chart_title(path: Path, title: str) -> Path:
    """Replace a static MCP chart's fixed English title with a Korean title."""
    from PIL import Image, ImageDraw, ImageFont

    font_candidates = [
        os.environ.get("MCP_FONT_PATH", ""),
        "/usr/local/share/fonts/truetype/pretendard-gov/PretendardGOV-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "malgunbd.ttf"),
        "DejaVuSans-Bold.ttf",
    ]
    font = None
    for candidate in font_candidates:
        if not candidate:
            continue
        try:
            font = ImageFont.truetype(candidate, 21)
            break
        except OSError:
            continue
    if font is None:
        return path

    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 42), fill="white")
    draw.text((36, 10), title, fill="#111827", font=font)
    image.save(path)
    return path


def _chart_image_title(chart: str | None, columns: list[str]) -> str:
    if chart == "correlation_heatmap" and len(columns) == 2:
        return f"{columns[0]}과 {columns[1]}의 상관관계"
    return "주요 원자료 간 상관관계"


def _topic_particle(label: str) -> str:
    base = label.split("(", 1)[0]
    last = next((char for char in reversed(base) if "가" <= char <= "힣"), "")
    return "은" if last and (ord(last) - ord("가")) % 28 else "는"


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_scale = sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def _quantile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _chart_analysis(
    chart: dict[str, Any],
    columns: list[str],
    rows: list[list[Any]],
) -> dict[str, Any]:
    selected_columns = [
        column for column in chart.get("columns") or columns if column in columns
    ]
    numeric = []
    categories = []
    for column in selected_columns:
        index = columns.index(column)
        values = [
            row[index]
            for row in rows
            if isinstance(row[index], (int, float))
            and not isinstance(row[index], bool)
        ]
        if values:
            numeric.append((column, [float(value) for value in values]))
            continue
        distinct = {
            str(row[index]).strip()
            for row in rows
            if row[index] is not None and str(row[index]).strip()
        }
        if distinct:
            categories.append((column, len(distinct)))

    evidence_rows: list[list[Any]] = [["분석 행 수", len(rows)]]
    sentences = [f"실제 데이터 {_format_number(len(rows))}행 전체를 분석했다."]
    chart_type = chart.get("chart")

    def add_distribution(column: str, values: list[float], quartiles: bool = False):
        minimum = _number(min(values))
        average = _number(sum(values) / len(values))
        median = _number(_quantile(values, 0.5))
        maximum = _number(max(values))
        evidence_rows.extend([
            [f"{column} 유효 행 수", len(values)],
            [f"{column} 최솟값", minimum],
            [f"{column} 평균", average],
            [f"{column} 중앙값", median],
            [f"{column} 최댓값", maximum],
        ])
        sentence = (
            f"{column}{_topic_particle(column)} {_format_number(minimum)}~"
            f"{_format_number(maximum)} 범위이며, 평균 {_format_number(average)}, "
            f"중앙값 {_format_number(median)}이다."
        )
        if quartiles:
            lower = _number(_quantile(values, 0.25))
            upper = _number(_quantile(values, 0.75))
            evidence_rows.extend([
                [f"{column} 25백분위", lower],
                [f"{column} 75백분위", upper],
            ])
            sentence += (
                f" 가운데 50%의 값은 {_format_number(lower)}~"
                f"{_format_number(upper)} 구간에 분포한다."
            )
        sentences.append(sentence)

    if (
        chart_type == "stacked_bar"
        and len(selected_columns) >= 2
        and "등급" in selected_columns[1]
    ):
        region_column, grade_column = selected_columns[:2]
        region_index = columns.index(region_column)
        grade_index = columns.index(grade_column)
        grouped: dict[str, list[float]] = {}
        for row in rows:
            region_value = row[region_index]
            grade_value = row[grade_index]
            if region_value is None or grade_value is None:
                continue
            try:
                grade = float(grade_value)
            except (TypeError, ValueError):
                continue
            grouped.setdefault(str(region_value), []).append(grade)
        shares = [
            (name, sum(grade >= 4 for grade in grades) * 100 / len(grades))
            for name, grades in grouped.items()
            if grades
        ]
        if shares:
            highest = max(shares, key=lambda item: item[1])
            lowest = min(shares, key=lambda item: item[1])
            evidence_rows.append([f"{region_column} 범주 수", len(shares)])
            evidence_rows.extend([
                [f"{name} 4·5등급 비율(%)", _number(share)]
                for name, share in sorted(shares, key=lambda item: item[1], reverse=True)
            ])
            sentences.append(
                f"{region_column}별 {grade_column} 구성을 비교하면 {highest[0]}의 "
                f"4·5등급 비율이 {_format_number(_number(highest[1]))}%로 가장 높고, "
                f"{lowest[0]}이 {_format_number(_number(lowest[1]))}%로 가장 낮다."
            )
    elif chart_type == "histogram" and numeric:
        add_distribution(*numeric[0], quartiles=True)
    elif chart_type in {"boxplot", "violin"} and numeric:
        add_distribution(*numeric[0], quartiles=True)
    elif chart_type in {"bar", "stacked_bar"} and categories and numeric:
        category_column = categories[0][0]
        value_column = numeric[0][0]
        category_index = columns.index(category_column)
        value_index = columns.index(value_column)
        grouped: dict[str, list[float]] = {}
        for row in rows:
            category = row[category_index]
            value = row[value_index]
            if category is None or not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            grouped.setdefault(str(category), []).append(float(value))
        means = [
            (name, sum(values) / len(values))
            for name, values in grouped.items()
            if values
        ]
        if means:
            highest = max(means, key=lambda item: item[1])
            lowest = min(means, key=lambda item: item[1])
            evidence_rows.extend([
                [f"{category_column} 범주 수", len(means)],
                [f"{value_column} 최고 범주", highest[0]],
                [f"{value_column} 최고 평균", _number(highest[1])],
                [f"{value_column} 최저 범주", lowest[0]],
                [f"{value_column} 최저 평균", _number(lowest[1])],
            ])
            sentences.append(
                f"{category_column}별 {value_column} 평균은 {highest[0]}에서 "
                f"{_format_number(_number(highest[1]))}로 가장 높고, {lowest[0]}에서 "
                f"{_format_number(_number(lowest[1]))}로 가장 낮다."
            )
    else:
        for column, values in numeric[:4]:
            add_distribution(column, values, quartiles=chart_type == "small_multiples")
        for column, count in categories[:2]:
            evidence_rows.append([f"{column} 범주 수", count])
            sentences.append(
                f"{column}{_topic_particle(column)} {_format_number(count)}개 범주로 구성된다."
            )

    if chart_type in {"correlation_heatmap", "scatter"}:
        strongest = None
        for left_index, (left_column, _) in enumerate(numeric):
            for right_column, _ in numeric[left_index + 1:]:
                left_column_index = columns.index(left_column)
                right_column_index = columns.index(right_column)
                paired = [
                    (
                        float(row[left_column_index]),
                        float(row[right_column_index]),
                    )
                    for row in rows
                    if isinstance(row[left_column_index], (int, float))
                    and not isinstance(row[left_column_index], bool)
                    and isinstance(row[right_column_index], (int, float))
                    and not isinstance(row[right_column_index], bool)
                ]
                coefficient = _correlation(
                    [pair[0] for pair in paired],
                    [pair[1] for pair in paired],
                )
                if coefficient is None:
                    continue
                candidate = (abs(coefficient), left_column, right_column, coefficient)
                if strongest is None or candidate[0] > strongest[0]:
                    strongest = candidate
        if strongest is not None:
            _, left_column, right_column, coefficient = strongest
            coefficient = _number(coefficient)
            evidence_rows.append([
                f"{left_column}–{right_column} 상관계수",
                coefficient,
            ])
            direction = (
                "양의" if coefficient > 0
                else "음의" if coefficient < 0
                else "뚜렷하지 않은"
            )
            sentences.append(
                f"{left_column}과 {right_column}의 상관계수는 "
                f"{_format_number(coefficient)}로 {direction} 관계가 나타났다."
            )

    return {
        "analysis": " ".join(sentences),
        "grounded": True,
        "evidence": {
            "columns": ["근거 항목", "값"],
            "rows": evidence_rows,
        },
    }


def _chart_input(
    columns: list[str],
    rows: list[list[Any]],
) -> tuple[list[str], list[list[Any]]]:
    if len(rows) == 1:
        numeric_indexes = [
            index
            for index, value in enumerate(rows[0])
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if len(numeric_indexes) < 2:
            return columns, rows
        return ["metric", "value"], [
            [columns[index], rows[0][index]] for index in numeric_indexes
        ]

    minimum_values = max(3, int(len(rows) * 0.1))
    category_indexes = []
    numeric_candidates = []
    for index, _column in enumerate(columns):
        numeric_values = [
            float(row[index])
            for row in rows
            if isinstance(row[index], (int, float)) and not isinstance(row[index], bool)
        ]
        if numeric_values:
            if (
                len(numeric_values) >= minimum_values
                and len(set(numeric_values)) >= 2
            ):
                numeric_candidates.append((index, len(numeric_values)))
            continue
        if any(row[index] is not None and str(row[index]).strip() for row in rows):
            category_indexes.append(index)

    numeric_indexes = [
        index for index, _count in sorted(
            numeric_candidates,
            key=lambda item: (-item[1], item[0]),
        )[:8]
    ]
    selected_indexes = [*category_indexes[:1], *numeric_indexes]
    if not numeric_indexes or selected_indexes == list(range(len(columns))):
        return columns, rows
    return (
        [columns[index] for index in selected_indexes],
        [[row[index] for index in selected_indexes] for row in rows],
    )


def _write_csv(path: Path, columns: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


def _runtime_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in SAFE_ENVIRONMENT_KEYS
    }
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["MCP_FONT_FAMILY"] = os.environ.get(
        "MCP_FONT_FAMILY",
        "Pretendard GOV",
    )
    return environment


def _validate_chart_spec(
    chart_spec: dict[str, Any],
    columns: list[str],
) -> dict[str, Any]:
    chart = chart_spec.get("chart")
    if chart not in CHART_TYPES:
        raise ValueError(f"지원하지 않는 그래프 유형입니다: {chart}")

    missing_fields = [
        field
        for field in CHART_REQUIRED_COLUMNS[chart]
        if not chart_spec.get(field)
    ]
    if missing_fields:
        raise ValueError(
            f"{chart} 그래프에 필요한 설정이 없습니다: {', '.join(missing_fields)}"
        )

    selected = [
        chart_spec.get(field)
        for field in ("x_column", "y_column", "group_column", "stack_column")
        if chart_spec.get(field)
    ]
    selected.extend(chart_spec.get("columns") or [])
    unknown = sorted({column for column in selected if column not in columns})
    if unknown:
        raise ValueError(f"조회 결과에 없는 열입니다: {', '.join(unknown)}")
    if chart == "correlation_heatmap" and len(chart_spec.get("columns") or []) < 2:
        raise ValueError("상관관계 히트맵에는 숫자 열을 두 개 이상 선택해야 합니다.")
    return chart_spec


def _default_python_path(web_root: Path) -> Path:
    configured = os.environ.get("COASTAL_MCP_PYTHON")
    if configured:
        return Path(configured)
    dedicated = (
        web_root / ".venv-mcp" / "Scripts" / "python.exe"
        if os.name == "nt"
        else web_root / ".venv-mcp" / "bin" / "python"
    )
    return dedicated if dedicated.is_file() else Path(sys.executable)


class McpAnalysisService:
    def __init__(
        self,
        python_path: Path | str | None = None,
        output_root: Path | str | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        web_root = Path(__file__).resolve().parents[2]
        self.python_path = Path(python_path or _default_python_path(web_root))
        self.bridge_path = Path(__file__).with_name("mcp_bridge.py")
        self.output_root = Path(output_root or web_root / "outputs" / "mcp").resolve()
        self.runner = runner
        self._runtime_ready: bool | None = None
        self._runtime_checked_at = 0.0

    def _run(self, command: list[str], timeout: int) -> subprocess.CompletedProcess:
        return self.runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_runtime_environment(),
            timeout=timeout,
            check=False,
        )

    def readiness_checks(self) -> dict[str, bool]:
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
            output_ready = self.output_root.is_dir() and os.access(
                self.output_root,
                os.W_OK,
            )
        except OSError:
            output_ready = False

        should_probe_runtime = self._runtime_ready is None or (
            self._runtime_ready is False
            and time.monotonic() - self._runtime_checked_at >= READINESS_FAILURE_TTL_SECONDS
        )
        if should_probe_runtime:
            try:
                completed = self._run(
                    [
                        str(self.python_path),
                        str(self.bridge_path),
                        "--check",
                    ],
                    timeout=30,
                )
                payload = json.loads(completed.stdout.strip().splitlines()[-1])
                self._runtime_ready = bool(
                    completed.returncode == 0 and payload.get("ready")
                )
            except (
                OSError,
                subprocess.TimeoutExpired,
                IndexError,
                json.JSONDecodeError,
            ):
                self._runtime_ready = False
            self._runtime_checked_at = time.monotonic()
        return {
            "mcp_output_root": output_ready,
            "mcp_runtime": self._runtime_ready,
        }

    def analyze(
        self,
        question: str,
        columns: list[str],
        rows: list[list[Any]],
        chart_spec: dict[str, Any] | None = None,
        owner_id: str | None = None,
    ) -> dict:
        if not columns or not rows:
            raise ValueError("MCP 분석에는 열과 행이 하나 이상 필요합니다.")
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("MCP 분석 데이터의 열과 행 길이가 일치하지 않습니다.")
        if chart_spec is not None:
            chart_spec = _validate_chart_spec(chart_spec, columns)
        if owner_id and not SAFE_OWNER_ID.fullmatch(owner_id):
            raise ValueError("MCP 사용자 식별자가 올바르지 않습니다.")

        analysis_id = uuid.uuid4().hex
        owner_root = self.output_root / owner_id if owner_id else self.output_root
        run_dir = (owner_root / analysis_id).resolve()
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise RuntimeError(
                "MCP 분석 결과 저장 폴더를 만들 수 없습니다."
            ) from error
        csv_path = run_dir / "duckdb_result.csv"
        _write_csv(csv_path, columns, rows)

        chart_columns, chart_rows = (
            (columns, rows)
            if chart_spec is not None
            else _chart_input(columns, rows)
        )
        chart_csv_path = csv_path
        if chart_columns != columns or chart_rows != rows:
            chart_csv_path = run_dir / "chart_input.csv"
            _write_csv(chart_csv_path, chart_columns, chart_rows)

        command = [
            str(self.python_path),
            str(self.bridge_path),
            "--csv",
            str(chart_csv_path),
            "--output-dir",
            str(run_dir),
            "--title",
            question,
        ]
        if chart_spec is not None:
            command.extend([
                "--spec-json",
                json.dumps(chart_spec, ensure_ascii=False),
            ])
        try:
            completed = self._run(command, timeout=180)
        except OSError as error:
            raise RuntimeError(
                "MCP 전용 환경을 실행할 수 없습니다. scripts/setup_mcp.ps1을 먼저 실행하세요."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("MCP 고급 분석이 180초 안에 완료되지 않았습니다.") from error

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "알 수 없는 오류").strip()
            raise RuntimeError(f"MCP 고급 분석 실패: {detail[-1200:]}")

        try:
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as error:
            raise RuntimeError("MCP 응답을 JSON으로 해석할 수 없습니다.") from error

        raw_charts = payload.get("charts")
        if not isinstance(raw_charts, list) or not raw_charts:
            raw_charts = [{
                "chart": payload.get("chart"),
                "columns": payload.get("columns", []),
                "reason": payload.get("reason", ""),
                "output_path": payload.get("output_path", ""),
            }]

        charts = []
        for raw_chart in raw_charts:
            output_path = Path(raw_chart.get("output_path", "")).resolve()
            if run_dir not in output_path.parents or not output_path.is_file():
                raise RuntimeError("MCP 출력 경로가 분석 작업 폴더 밖에 있거나 파일이 없습니다.")
            chart = dict(raw_chart)
            if chart.get("chart") == "correlation_heatmap":
                _apply_chart_title(
                    output_path,
                    _chart_image_title(chart.get("chart"), chart.get("columns") or []),
                )
            chart["chart_url"] = (
                f"/api/mcp/analyses/{analysis_id}/assets/{output_path.name}"
            )
            chart["asset_name"] = output_path.name
            chart.update(_chart_analysis(chart, chart_columns, chart_rows))
            chart.pop("output_path", None)
            charts.append(chart)

        first_chart = charts[0]
        payload["analysis_id"] = analysis_id
        payload["charts"] = charts
        for key in (
            "chart",
            "columns",
            "reason",
            "chart_url",
            "asset_name",
            "analysis",
            "grounded",
            "evidence",
        ):
            payload[key] = first_chart.get(key)
        payload.pop("output_path", None)
        return payload

    def asset(
        self,
        analysis_id: str,
        name: str,
        owner_id: str | None = None,
    ) -> Path | None:
        if not analysis_id.isalnum() or Path(name).name != name:
            return None
        if owner_id and not SAFE_OWNER_ID.fullmatch(owner_id):
            return None
        owner_root = self.output_root / owner_id if owner_id else self.output_root
        run_dir = (owner_root / analysis_id).resolve()
        candidate = (run_dir / name).resolve()
        if run_dir not in candidate.parents or not candidate.is_file():
            return None
        return candidate
