"""Exercise AUTOTEST's real generation methods with stubbed model responses."""

from unittest.mock import Mock

import pytest

pytest.importorskip("langchain_openai", reason="Phase A dependencies required")

from autotest.core.web_test_generator import WebTestGenerator
from autotest.core.prompt_manager import PromptManager


URL = "https://example.test/"
SOURCE = 'def run(ctx):\n    ctx.open("https://example.test/")\n    ctx.assert_title("Example")'


@pytest.fixture
def generator():
    # Do not construct a provider, browser or database for these unit tests.
    obj = WebTestGenerator.__new__(WebTestGenerator)
    obj.driver = Mock(title="Example", current_url=URL, page_source="<h1>Example</h1>")
    obj.driver.find_elements.return_value = []
    obj.llm = Mock()
    obj.logger = Mock()
    obj.prompt_manager = PromptManager()
    return obj


def test_generation_reuses_analysis_cases_and_script(generator, monkeypatch):
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("Interactive generation")))
    generator.llm_page_analysis = Mock(return_value={"summary": "Example page"})
    generator.llm.generate.side_effect = [
        '{"test_cases": [{"name": "Check title"}]}', "```python\n" + SOURCE + "\n```"]
    source, analysis = generator.generate_monitoring_page(URL)
    assert source.strip() == SOURCE
    assert analysis["metadata"]["url"] == URL
    assert analysis["test_cases"][0]["test_case_type"] == "auto-generated"
    assert [c.kwargs["model_type"] for c in generator.llm.generate.call_args_list] == ["analysis", "selenium"]


def test_generation_refuses_empty_analysis(generator):
    generator.llm_page_analysis = Mock(return_value={})
    with pytest.raises(ValueError, match="analysis failed"):
        generator.generate_monitoring_page(URL)
    generator.llm.generate.assert_not_called()


def test_script_generation_refuses_raw_driver(generator):
    generator.llm.generate.return_value = 'import selenium\n' + SOURCE
    with pytest.raises(ValueError):
        generator.generate_script_for_test_case({}, {}, "<html/>", False, None, None, monitoring=True)


def test_database_relationships_registered():
    from sqlalchemy.orm import configure_mappers
    configure_mappers()