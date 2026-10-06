"""Decision F: PDF remains offered with Odin's unchanged tool description."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.config.schema import Config
from src.discord.tool_catalog import ToolCatalog
from src.tools.affordances import decorate_description
from src.tools.defs.browser_web import TOOLS_SECTION
from src.tools.registry import get_tool_definitions


def test_missing_pdf_dependency_is_offered_with_unchanged_description():
    config = Config()
    catalog = ToolCatalog(
        get_config=lambda: config,
        skill_manager=MagicMock(get_tool_definitions=lambda: []),
    )
    # A configured handler must still be admitted by the owning engine. Absence
    # of the optional wheel alone must not remove it from the backend catalog.
    with (patch.dict("sys.modules", {"fitz": None}),
          patch("src.discord.tool_catalog.get_tool_definitions", lambda **kwargs:
                get_tool_definitions(readiness={"analyze_pdf": True}, **kwargs))):
        assert "analyze_pdf" not in catalog.backend_hidden_names()
        definitions = {tool["name"]: tool for tool in catalog.merged_definitions()}
    original = next(tool for tool in TOOLS_SECTION if tool["name"] == "analyze_pdf")
    assert original["description"] == (
        "Extracts text from a PDF (URL or host:path). Returns markdown text; large results "
        "have retained previews and get_tool_output(cursor=...) continuation. "
        "For image-heavy PDFs, use browser_screenshot."
    )
    assert definitions["analyze_pdf"]["description"] == decorate_description(
        "analyze_pdf", original["description"],
    )
