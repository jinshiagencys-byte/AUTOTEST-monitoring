"""
AutoTest Package - Automated Web Testing Framework
"""

from importlib import import_module

# Keep Phase B independent of the optional LLM and database dependencies.
_EXPORTS = {
    "WebTestGenerator": ".core.web_test_generator",
    "LLMWrapper": ".core.llm_wrapper",
    "PromptManager": ".core.prompt_manager",
    "URLExtractor": ".core.url_extractor",
    "ContextFilter": ".utils.logging_utils",
    "init_db": ".db.database",
    "SessionLocal": ".db.database",
    "Page": ".tables.page",
    "Redirect": ".tables.redirect",
    "TestCase": ".tables.test_case_data",
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value

__version__ = "1.0.0"
__author__ = "Ankit Saha"
__email__ = "ankit.s@mindfiresolutions.com"

__all__ = [
    'WebTestGenerator',
    'LLMWrapper', 
    'PromptManager',
    'URLExtractor',
    'ContextFilter',
    'init_db',
    'SessionLocal',
    'Page', 
    'Redirect',
    'TestCase',
]
