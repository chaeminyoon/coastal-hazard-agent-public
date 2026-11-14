import os

from matplotlib import rc

from data_analysis import prompts, theming, tools  # noqa: F401
from data_analysis.server import mcp

try:
    from .mcp_policy import GRADE_COLORS
except ImportError:
    from mcp_policy import GRADE_COLORS


def main() -> None:
    active_theme = theming.current()
    existing = theming.THEMES[active_theme]["palette"]
    theming.THEMES[active_theme]["palette"] = [
        *GRADE_COLORS,
        *existing[len(GRADE_COLORS):],
    ]
    theming.apply(active_theme)
    rc(
        "font",
        family=os.environ.get("MCP_FONT_FAMILY", "Pretendard GOV"),
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
