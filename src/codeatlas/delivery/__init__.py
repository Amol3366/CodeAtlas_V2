"""Renderings of a persisted analysis.

Every renderer reads the same stored report and adds nothing. JSON is the
contract model itself; Markdown is a view for a human reviewer; SARIF is an
export for tools that already consume it. None of the three is the internal
model, and none may state a fact the report does not already carry.
"""

from codeatlas.delivery.markdown_report import render_markdown
from codeatlas.delivery.pr_report import render_pr_markdown
from codeatlas.delivery.sarif_report import render_sarif
from codeatlas.delivery.text_report import render_text

__all__ = [
    "render_markdown",
    "render_pr_markdown",
    "render_sarif",
    "render_text",
]
