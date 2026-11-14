import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

try:
    from .mcp_policy import normalize_plot_parameters
except ImportError:
    from mcp_policy import normalize_plot_parameters

REQUIRED_TOOLS = {"recommend_visualizations", "plot_auto"}
CUSTOM_CHART_LABELS = {
    "bar": "막대 차트",
    "stacked_bar": "누적 막대 차트",
    "line": "선 차트",
    "area": "영역 차트",
    "scatter": "산점도",
    "histogram": "히스토그램",
    "boxplot": "상자수염 차트",
    "violin": "바이올린 차트",
    "correlation_heatmap": "상관관계 히트맵",
    "pivot_heatmap": "피벗 히트맵",
}
TITLE_CAPABLE_TOOLS = {
    "plot_auto", "plot_bar", "plot_stacked_bar", "plot_line", "plot_area",
    "plot_scatter", "plot_histogram", "plot_boxplot", "plot_violin",
    "plot_pivot_heatmap", "plot_small_multiples", "plot_missingness",
}


def _natural_chart_title(chart: str | None, columns: list[str], fallback: str) -> str:
    clean_columns = [str(column).strip() for column in columns if str(column).strip()]
    if chart == "histogram" and clean_columns:
        return f"{clean_columns[0]} 값의 전체 분포"
    if chart in {"bar", "line", "area"} and len(clean_columns) >= 2:
        return f"{clean_columns[0]}별 {clean_columns[1]} 비교"
    if chart == "stacked_bar" and len(clean_columns) >= 2:
        return f"{clean_columns[0]}별 {clean_columns[1]} 구성"
    if chart == "scatter" and len(clean_columns) >= 2:
        return f"{clean_columns[0]}과 {clean_columns[1]}의 관계"
    if chart in {"correlation_heatmap", "pivot_heatmap"}:
        return "주요 원자료 간 관계와 분포"
    if chart == "small_multiples":
        return "주요 지표별 실제 데이터 분포"
    if chart == "missingness":
        return "주요 지표별 자료 확인 비율"
    if clean_columns:
        return f"{clean_columns[0]} 중심 데이터 분석"
    return fallback


def _result_data(result: Any) -> dict:
    is_error = getattr(result, "isError", getattr(result, "is_error", False))
    text_parts = [
        item.text for item in result.content if isinstance(item, types.TextContent)
    ]
    if is_error:
        raise RuntimeError("\n".join(text_parts) or "MCP 도구 호출 실패")

    structured = getattr(
        result,
        "structuredContent",
        getattr(result, "structured_content", None),
    )
    if isinstance(structured, dict):
        return structured
    for text in text_parts:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("MCP 도구가 구조화된 결과를 반환하지 않았습니다.")


def _result_value(result: Any) -> str:
    is_error = getattr(result, "isError", getattr(result, "is_error", False))
    text_parts = [
        item.text for item in result.content if isinstance(item, types.TextContent)
    ]
    if is_error:
        raise RuntimeError("\n".join(text_parts) or "MCP 도구 호출 실패")
    structured = getattr(
        result,
        "structuredContent",
        getattr(result, "structured_content", None),
    )
    if isinstance(structured, dict) and isinstance(structured.get("result"), str):
        return structured["result"]
    for text in text_parts:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        if isinstance(parsed, str):
            return parsed
    raise RuntimeError("MCP 도구가 파일 경로를 반환하지 않았습니다.")


def _label_numeric_pair(csv_path: Path) -> tuple[str, str] | None:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if len(reader.fieldnames or []) != 2 or not rows:
        return None
    numeric = []
    for column in reader.fieldnames or []:
        values = [row[column] for row in rows if row[column] not in {"", None}]
        try:
            for value in values:
                float(value)
        except ValueError:
            continue
        if values:
            numeric.append(column)
    if len(numeric) != 1:
        return None
    label = next(column for column in reader.fieldnames or [] if column != numeric[0])
    return label, numeric[0]


def _server_parameters(output_dir: Path | None = None) -> StdioServerParameters:
    environment = os.environ.copy()
    if output_dir is not None:
        environment["MCP_OUTPUT_DIR"] = str(output_dir)
    server_path = Path(__file__).with_name("mcp_server.py")
    return StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env=environment,
    )


def _custom_tool_call(
    csv_path: Path,
    title: str,
    spec: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str], str]:
    chart = spec["chart"]
    common = {
        "csv_path": str(csv_path),
        "title": _natural_chart_title(chart, [
            value for value in (
                spec.get("x_column"), spec.get("y_column"),
                spec.get("group_column"), spec.get("stack_column"),
            ) if value
        ], title),
    }
    x_column = spec.get("x_column")
    y_column = spec.get("y_column")
    group_column = spec.get("group_column")
    stack_column = spec.get("stack_column")
    aggregation = spec.get("aggregation", "mean")

    if chart == "bar":
        tool_name = "plot_bar"
        arguments = {
            **common,
            "column": x_column,
            "y_column": y_column,
            "agg": aggregation,
            "top_n": spec.get("top_n", 20),
            "interactive": False,
        }
    elif chart == "stacked_bar":
        tool_name = "plot_stacked_bar"
        arguments = {
            **common,
            "category_column": x_column,
            "stack_column": stack_column,
            "y_column": y_column,
            "agg": aggregation,
            "normalize": spec.get("normalize", False),
            "top_n": spec.get("top_n", 20),
        }
    elif chart in {"line", "area"}:
        tool_name = f"plot_{chart}"
        arguments = {
            **common,
            "x_column": x_column,
            "y_column": y_column,
            "group_column": group_column,
            "agg": aggregation,
        }
        if chart == "line":
            arguments["interactive"] = False
    elif chart == "scatter":
        tool_name = "plot_scatter"
        arguments = {
            **common,
            "x_column": x_column,
            "y_column": y_column,
            "hue_column": group_column,
            "xlabel": spec.get("x_label"),
            "ylabel": spec.get("y_label"),
        }
    elif chart == "histogram":
        tool_name = "plot_histogram"
        arguments = {
            **common,
            "column": x_column,
            "bins": spec.get("bins", 10),
            "xlabel": spec.get("x_label"),
            "ylabel": spec.get("y_label") or "격자 수 (개)",
        }
    elif chart == "boxplot":
        tool_name = "plot_boxplot"
        arguments = {
            **common,
            "column": y_column,
            "by_column": x_column,
            "xlabel": spec.get("x_label"),
            "ylabel": spec.get("y_label"),
        }
    elif chart == "violin":
        tool_name = "plot_violin"
        arguments = {
            **common,
            "column": y_column,
            "by_column": x_column,
        }
    elif chart == "correlation_heatmap":
        tool_name = "plot_correlation_heatmap"
        arguments = {
            "csv_path": str(csv_path),
            "columns": spec.get("columns") or None,
        }
    elif chart == "pivot_heatmap":
        tool_name = "plot_pivot_heatmap"
        arguments = {
            **common,
            "index_column": x_column,
            "column_column": group_column,
            "value_column": y_column,
            "agg": aggregation,
        }
    else:
        raise RuntimeError(f"지원하지 않는 사용자 지정 그래프입니다: {chart}")

    arguments = {
        key: value
        for key, value in arguments.items()
        if value is not None
    }
    columns = list(dict.fromkeys([
        column
        for column in (
            x_column,
            y_column,
            group_column,
            stack_column,
            *(spec.get("columns") or []),
        )
        if column
    ]))
    arguments = normalize_plot_parameters(arguments, columns)
    reason = f"선택한 열을 기준으로 생성한 {CUSTOM_CHART_LABELS[chart]}입니다."
    return tool_name, arguments, columns, reason


async def check_runtime() -> dict:
    async with stdio_client(_server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            missing = sorted(REQUIRED_TOOLS - tool_names)
            return {
                "ready": not missing,
                "tools_available": len(tool_names),
                "missing": missing,
            }


async def run(
    csv_path: Path,
    output_dir: Path,
    title: str,
    chart_spec: dict[str, Any] | None = None,
) -> dict:
    parameters = _server_parameters(output_dir)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            missing = sorted(REQUIRED_TOOLS - tool_names)
            if missing:
                raise RuntimeError(f"필수 MCP 도구가 없습니다: {', '.join(missing)}")

            if chart_spec is not None:
                tool_name, arguments, columns, reason = _custom_tool_call(
                    csv_path,
                    title,
                    chart_spec,
                )
                if tool_name not in tool_names:
                    raise RuntimeError(f"선택한 MCP 그래프 도구가 없습니다: {tool_name}")
                plot_result = await session.call_tool(tool_name, arguments=arguments)
                chart = {
                    "chart": chart_spec["chart"],
                    "columns": columns,
                    "reason": reason,
                    "output_path": _result_value(plot_result),
                }
                return {
                    **chart,
                    "charts": [chart],
                    "alternatives": [],
                    "column_roles": {},
                    "tool_calls": [tool_name],
                    "tools_available": len(tool_names),
                }

            recommendation_result = await session.call_tool(
                "recommend_visualizations",
                arguments={"csv_path": str(csv_path), "max_recommendations": 5},
            )
            recommendations = _result_data(recommendation_result)
            charts = []
            tool_calls = ["recommend_visualizations"]
            pair = _label_numeric_pair(csv_path)
            if pair and "plot_bar" in tool_names:
                label, value = pair
                plot_result = await session.call_tool(
                    "plot_bar",
                    arguments={
                        "csv_path": str(csv_path),
                        "column": label,
                        "y_column": value,
                        "agg": "mean",
                        "interactive": False,
                        "title": _natural_chart_title("bar", [label, value], title),
                    },
                )
                charts.append({
                    "chart": "bar",
                    "columns": [label, value],
                    "reason": f"{label}별 {value} 값을 직접 비교하는 막대 차트입니다.",
                    "output_path": _result_value(plot_result),
                })
                tool_calls.append("plot_bar")
                if "plot_histogram" in tool_names:
                    histogram_result = await session.call_tool(
                        "plot_histogram",
                        arguments={
                            "csv_path": str(csv_path),
                            "column": value,
                            "title": _natural_chart_title("histogram", [value], title),
                        },
                    )
                    charts.append({
                        "chart": "histogram",
                        "columns": [value],
                        "reason": f"{value} 값의 분포와 치우침을 확인하는 히스토그램입니다.",
                        "output_path": _result_value(histogram_result),
                    })
                    tool_calls.append("plot_histogram")

            for recommendation in recommendations.get("recommendations", []):
                if len(charts) >= 3:
                    break
                tool_call = recommendation.get("tool_call") or {}
                tool_name = tool_call.get("tool")
                params = tool_call.get("params") or {}
                if not tool_name or tool_name not in tool_names or not tool_name.startswith("plot_"):
                    continue
                columns = recommendation.get("columns", [])
                params = normalize_plot_parameters(params, columns)
                rendered_columns = columns
                if (
                    recommendation.get("chart") == "stacked_bar"
                    and "등급" in str(params.get("stack_column", ""))
                ):
                    params.pop("y_column", None)
                    params.pop("agg", None)
                    rendered_columns = [
                        params.get("category_column"),
                        params.get("stack_column"),
                    ]
                if tool_name in TITLE_CAPABLE_TOOLS:
                    params["title"] = _natural_chart_title(
                        recommendation.get("chart"),
                        rendered_columns,
                        title,
                    )
                if len(set(columns)) != len(columns):
                    continue
                if pair and recommendation.get("chart") == "bar" and set(columns).issubset(set(pair)):
                    continue
                signature = (recommendation.get("chart"), tuple(columns))
                if any((chart.get("chart"), tuple(chart.get("columns", []))) == signature for chart in charts):
                    continue
                try:
                    plot_result = await session.call_tool(tool_name, arguments=params)
                    if tool_name == "plot_auto":
                        plotted = _result_data(plot_result)
                        output_path = plotted.get("output_path")
                    else:
                        output_path = _result_value(plot_result)
                    charts.append({
                        "chart": recommendation.get("chart"),
                        "columns": rendered_columns,
                        "reason": recommendation.get("reason") or "자동 추천 차트입니다.",
                        "output_path": output_path,
                    })
                    tool_calls.append(tool_name)
                except RuntimeError:
                    continue

            if not charts:
                plot_result = await session.call_tool(
                    "plot_auto",
                    arguments={
                        "csv_path": str(csv_path),
                        "interactive": False,
                        "title": _natural_chart_title("auto", [], title),
                    },
                )
                plotted = _result_data(plot_result)
                charts.append({
                    "chart": plotted.get("chart"),
                    "columns": plotted.get("columns", []),
                    "reason": plotted.get("reason") or "자동 추천 차트입니다.",
                    "output_path": plotted.get("output_path"),
                })
                tool_calls.append("plot_auto")

    plotted = charts[0]
    return {
        "chart": plotted.get("chart"),
        "columns": plotted.get("columns", []),
        "reason": plotted.get("reason") or "자동 추천 차트입니다.",
        "output_path": plotted.get("output_path"),
        "charts": charts,
        "alternatives": recommendations.get("recommendations", [])[1:4],
        "column_roles": recommendations.get("column_roles", {}),
        "tool_calls": tool_calls,
        "tools_available": len(tool_names),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--title", default="고급 데이터 분석")
    parser.add_argument("--spec-json")
    args = parser.parse_args()
    if args.check:
        result = asyncio.run(check_runtime())
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.csv is None or args.output_dir is None:
        parser.error("--csv와 --output-dir가 필요합니다.")
    chart_spec = json.loads(args.spec_json) if args.spec_json else None
    result = asyncio.run(
        run(
            args.csv.resolve(),
            args.output_dir.resolve(),
            args.title,
            chart_spec,
        )
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
