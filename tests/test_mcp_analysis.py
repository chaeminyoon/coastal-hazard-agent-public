import json
import subprocess
import sys
from pathlib import Path

import pytest

from coastal_web.mcp_analysis import (
    McpAnalysisService,
    _apply_chart_title,
    _chart_analysis,
    _chart_input,
)
from coastal_web.mcp_policy import normalize_plot_parameters


def test_apply_chart_title_replaces_the_external_default_title(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    chart = tmp_path / "correlation.png"
    image = Image.new("RGB", (420, 180), "white")
    ImageDraw.Draw(image).rectangle((20, 10, 210, 34), fill="black")
    image.save(chart)
    monkeypatch.setenv("MCP_FONT_PATH", "DejaVuSans-Bold.ttf")

    result = _apply_chart_title(chart, "Natural data relationship")

    assert result == chart
    rendered = Image.open(chart).convert("RGB")
    assert rendered.getpixel((25, 20)) == (255, 255, 255)
    assert any(
        rendered.getpixel((x, y)) != (255, 255, 255)
        for x in range(28, 300)
        for y in range(8, 40)
    )


def test_mcp_plot_policy_replaces_sum_for_non_additive_physical_units():
    assert normalize_plot_parameters(
        {"agg": "sum", "y_column": "강풍 (m/s)"},
        ["지역", "강풍 (m/s)"],
    )["agg"] == "mean"
    assert normalize_plot_parameters(
        {"agg": "sum", "y_column": "고위험 격자 수 (개)"},
        ["지역", "고위험 격자 수 (개)"],
    )["agg"] == "sum"
    assert normalize_plot_parameters(
        {"y_column": "강풍 (m/s)"},
        ["지역", "강풍 (m/s)"],
    )["agg"] == "mean"


def test_stacked_grade_analysis_compares_high_risk_share_by_region():
    columns = ["지역", "종합 위험 (등급)"]
    rows = [
        ["민락동", 5], ["민락동", 4], ["민락동", 3],
        ["광안동", 4], ["광안동", 2], ["광안동", 1],
    ]

    result = _chart_analysis(
        {"chart": "stacked_bar", "columns": columns},
        columns,
        rows,
    )

    assert "민락동의 4·5등급 비율이 66.67%로 가장 높" in result["analysis"]
    assert ["민락동 4·5등급 비율(%)", 66.67] in result["evidence"]["rows"]


def test_mcp_chart_input_keeps_all_rows_but_drops_sparse_and_constant_metrics():
    columns = ["지역", "강풍 (m/s)", "희소 지표", "상수 지표"]
    rows = [
        ["민락동", 18.2 + index, 99 if index == 0 else None, 1]
        for index in range(20)
    ]

    chart_columns, chart_rows = _chart_input(columns, rows)

    assert chart_columns == ["지역", "강풍 (m/s)"]
    assert len(chart_rows) == 20
    assert chart_rows[-1] == ["민락동", 37.2]


def test_histogram_analysis_explains_the_selected_distribution():
    result = _chart_analysis(
        {"chart": "histogram", "columns": ["강풍 (m/s)"]},
        ["강풍 (m/s)", "고령인구 (명)"],
        [[15.0, 100], [17.0, 200], [19.0, 300], [25.0, 400]],
    )

    assert "강풍 (m/s)" in result["analysis"]
    assert "중앙값" in result["analysis"]
    assert "고령인구" not in result["analysis"]


def test_bar_analysis_identifies_the_highest_category():
    result = _chart_analysis(
        {"chart": "bar", "columns": ["지역", "고위험 비율 (%)"]},
        ["지역", "고위험 비율 (%)"],
        [["민락동", 27.4], ["광안동", 18.1], ["남천동", 12.3]],
    )

    assert "민락동" in result["analysis"]
    assert "27.4" in result["analysis"]
    assert "가장 높" in result["analysis"]


def test_mcp_analysis_writes_query_result_and_runs_utf8_bridge(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "bar_region_score.png"
        chart_path.write_bytes(b"png")
        payload = {
            "chart": "bar",
            "columns": ["region", "score"],
            "reason": "지역별 점수를 비교하기 적합합니다.",
            "output_path": str(chart_path),
            "tool_calls": ["recommend_visualizations", "plot_auto"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=tmp_path / ".venv-mcp" / "python.exe",
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    result = service.analyze(
        question="지역별 위험 점수를 고급 분석해줘",
        columns=["region", "score"],
        rows=[["수영구", 72.5], ["해운대구", 64.1]],
    )

    command, kwargs = calls[0]
    csv_path = Path(command[command.index("--csv") + 1])
    assert csv_path.read_text(encoding="utf-8-sig").splitlines() == [
        "region,score",
        "수영구,72.5",
        "해운대구,64.1",
    ]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["capture_output"] is True
    assert result["chart"] == "bar"
    assert result["tool_calls"] == ["recommend_visualizations", "plot_auto"]
    assert result["chart_url"].endswith("/assets/bar_region_score.png")
    assert service.asset(result["analysis_id"], "bar_region_score.png").read_bytes() == b"png"


def test_mcp_analysis_pivots_single_row_numeric_summary_for_charting(tmp_path):
    captured_csv = None

    def runner(command, **kwargs):
        nonlocal captured_csv
        captured_csv = Path(command[command.index("--csv") + 1])
        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "bar_metric_value.png"
        chart_path.write_bytes(b"png")
        payload = {
            "chart": "bar",
            "columns": ["metric", "value"],
            "reason": "단일 행 요약값을 지표별로 비교합니다.",
            "output_path": str(chart_path),
            "tool_calls": ["recommend_visualizations", "plot_bar"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=tmp_path / "python.exe",
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    service.analyze(
        "4,5등급만 분석해줘",
        ["cnt_all", "cnt_45", "pct_45"],
        [[812, 411, 50.6]],
    )

    assert captured_csv is not None
    assert captured_csv.name == "chart_input.csv"
    assert captured_csv.read_text(encoding="utf-8-sig").splitlines() == [
        "metric,value",
        "cnt_all,812",
        "cnt_45,411",
        "pct_45,50.6",
    ]
    original_csv = captured_csv.with_name("duckdb_result.csv")
    assert original_csv.read_text(encoding="utf-8-sig").splitlines() == [
        "cnt_all,cnt_45,pct_45",
        "812,411,50.6",
    ]


def test_mcp_analysis_returns_multiple_chart_assets(tmp_path):
    def runner(command, **kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        bar_path = output_dir / "bar_region_score.png"
        line_path = output_dir / "line_region_score.png"
        bar_path.write_bytes(b"bar")
        line_path.write_bytes(b"line")
        payload = {
            "charts": [
                {"chart": "bar", "columns": ["region", "score"], "reason": "비교", "output_path": str(bar_path)},
                {"chart": "line", "columns": ["region", "score"], "reason": "추세", "output_path": str(line_path)},
            ],
            "tool_calls": ["recommend_visualizations", "plot_auto", "plot_auto"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=tmp_path / "python.exe",
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    result = service.analyze("여러 그래프로 보여줘", ["region", "score"], [["수영구", 72.5]])

    assert [chart["chart"] for chart in result["charts"]] == ["bar", "line"]
    assert result["charts"][0]["chart_url"].endswith("/assets/bar_region_score.png")
    assert result["charts"][1]["chart_url"].endswith("/assets/line_region_score.png")
    assert result["chart_url"] == result["charts"][0]["chart_url"]


def test_mcp_analysis_adds_grounded_korean_analysis_and_evidence(tmp_path):
    def runner(command, **kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "bar_region_score.png"
        chart_path.write_bytes(b"png")
        payload = {
            "chart": "bar",
            "columns": ["지역", "위험도"],
            "reason": "지역별 위험도를 비교합니다.",
            "output_path": str(chart_path),
            "tool_calls": ["plot_bar"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    result = service.analyze(
        "지역별 위험도를 비교해줘",
        ["지역", "위험도"],
        [["민락동", 72.5], ["광안동", 64.1], ["남천동", 68.4]],
    )

    chart = result["charts"][0]
    assert chart["asset_name"] == "bar_region_score.png"
    assert chart["grounded"] is True
    assert "실제 데이터 3행" in chart["analysis"]
    assert "지역별 위험도 평균은 민락동에서 72.5로 가장 높고" in chart["analysis"]
    assert "광안동에서 64.1로 가장 낮다" in chart["analysis"]
    assert chart["evidence"] == {
        "columns": ["근거 항목", "값"],
        "rows": [
            ["분석 행 수", 3],
            ["지역 범주 수", 3],
            ["위험도 최고 범주", "민락동"],
            ["위험도 최고 평균", 72.5],
            ["위험도 최저 범주", "광안동"],
            ["위험도 최저 평균", 64.1],
        ],
    }


def test_mcp_correlation_chart_identifies_strongest_data_relationship(tmp_path):
    def runner(command, **kwargs):
        from PIL import Image

        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "correlation_heatmap.png"
        Image.new("RGB", (420, 180), "white").save(chart_path)
        payload = {
            "chart": "correlation_heatmap",
            "columns": ["강풍 (m/s)", "침수면적 (m²)", "고령인구 (명)"],
            "reason": "수치형 변수의 상관관계를 비교합니다.",
            "output_path": str(chart_path),
            "tool_calls": ["plot_correlation_heatmap"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    result = service.analyze(
        "원자료 상관관계를 분석해줘",
        ["강풍 (m/s)", "침수면적 (m²)", "고령인구 (명)"],
        [[1, 10, 4], [2, 20, 3], [3, 30, 2], [4, 40, 1]],
    )

    chart = result["charts"][0]
    assert "강풍 (m/s)과 침수면적 (m²)의 상관계수는 1" in chart["analysis"]
    assert chart["evidence"]["rows"][-1] == [
        "강풍 (m/s)–침수면적 (m²) 상관계수",
        1,
    ]


def test_mcp_analysis_rejects_output_outside_run_directory(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")

    def runner(command, **kwargs):
        payload = {"output_path": str(outside), "tool_calls": []}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=tmp_path / "python.exe",
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    try:
        service.analyze("분석해줘", ["score"], [[72.5]])
    except RuntimeError as error:
        assert "출력 경로" in str(error)
    else:
        raise AssertionError("run directory 밖의 MCP 출력이 허용되었습니다.")


def test_mcp_analysis_uses_current_interpreter_when_dedicated_runtime_is_absent(
    monkeypatch,
):
    monkeypatch.delenv("COASTAL_MCP_PYTHON", raising=False)

    service = McpAnalysisService()

    assert service.python_path == Path(sys.executable)


def test_mcp_analysis_reports_unwritable_output_root_as_runtime_error(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=blocked,
    )

    with pytest.raises(RuntimeError, match="저장 폴더"):
        service.analyze("분석해줘", ["score"], [[72.5]])


def test_mcp_analysis_forwards_validated_custom_chart_spec(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "scatter_rain_risk.png"
        chart_path.write_bytes(b"png")
        payload = {
            "chart": "scatter",
            "columns": ["강우", "위험도", "지역"],
            "reason": "사용자 지정 산점도입니다.",
            "output_path": str(chart_path),
            "tool_calls": ["plot_scatter"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )
    result = service.analyze(
        "강우와 위험도의 관계를 보여줘",
        ["강우", "위험도", "지역"],
        [[20.5, 4.2, "민락동"], [12.1, 3.1, "광안동"]],
        chart_spec={
            "chart": "scatter",
            "x_column": "강우",
            "y_column": "위험도",
            "group_column": "지역",
            "x_label": "강우 (mm/h)",
            "y_label": "위험도",
        },
    )

    command, _ = calls[0]
    assert "--spec-json" in command
    spec = json.loads(command[command.index("--spec-json") + 1])
    assert spec == {
        "chart": "scatter",
        "x_column": "강우",
        "y_column": "위험도",
        "group_column": "지역",
        "x_label": "강우 (mm/h)",
        "y_label": "위험도",
    }
    assert result["chart"] == "scatter"


def test_mcp_analysis_rejects_chart_columns_outside_result(tmp_path):
    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
    )

    with pytest.raises(ValueError, match="조회 결과에 없는 열"):
        service.analyze(
            "산점도로 보여줘",
            ["강우", "위험도"],
            [[20.5, 4.2]],
            chart_spec={
                "chart": "scatter",
                "x_column": "강우",
                "y_column": "존재하지않음",
            },
        )


def test_mcp_analysis_scopes_assets_to_owner(tmp_path):
    def runner(command, **kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        chart_path = output_dir / "bar.png"
        chart_path.write_bytes(b"png")
        payload = {
            "chart": "bar",
            "columns": ["지역", "위험도"],
            "reason": "비교",
            "output_path": str(chart_path),
            "tool_calls": ["plot_bar"],
            "tools_available": 60,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )
    result = service.analyze(
        "비교해줘",
        ["지역", "위험도"],
        [["수영구", 72.5]],
        owner_id="user-1",
    )

    assert service.asset(
        result["analysis_id"],
        "bar.png",
        owner_id="user-1",
    ).read_bytes() == b"png"
    assert service.asset(
        result["analysis_id"],
        "bar.png",
        owner_id="user-2",
    ) is None


def test_mcp_analysis_rejects_unsafe_owner_id(tmp_path):
    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
    )

    with pytest.raises(ValueError, match="사용자 식별자"):
        service.analyze(
            "비교해줘",
            ["지역", "위험도"],
            [["수영구", 72.5]],
            owner_id="../other-user",
        )


def test_mcp_readiness_checks_runtime_once_without_forwarding_secrets(
    tmp_path,
    monkeypatch,
):
    calls = []
    monkeypatch.setenv("COASTAL_DATABASE_URL", "secret-database-url")

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"ready": True, "tools_available": 60}),
            "",
        )

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    assert service.readiness_checks() == {
        "mcp_output_root": True,
        "mcp_runtime": True,
    }
    assert service.readiness_checks()["mcp_runtime"] is True
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "--check" in command
    assert kwargs["env"]["MCP_FONT_FAMILY"] == "Pretendard GOV"
    assert "COASTAL_DATABASE_URL" not in kwargs["env"]


def test_mcp_readiness_rechecks_a_cached_failure_after_ttl(tmp_path):
    calls = 0

    def runner(command, **kwargs):
        nonlocal calls
        calls += 1
        ready = calls > 1
        return subprocess.CompletedProcess(
            command,
            0 if ready else 1,
            json.dumps({"ready": ready, "tools_available": 60 if ready else 0}),
            "",
        )

    service = McpAnalysisService(
        python_path=sys.executable,
        output_root=tmp_path / "analyses",
        runner=runner,
    )

    assert service.readiness_checks()["mcp_runtime"] is False
    service._runtime_checked_at = 0
    assert service.readiness_checks()["mcp_runtime"] is True
    assert calls == 2
