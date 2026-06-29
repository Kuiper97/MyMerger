import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "PDFMerger1.0.2.py"

spec = importlib.util.spec_from_file_location("pdfmerger", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_page_ranges_input():
    assert module.parse_page_ranges_input("1-3,5") == [(1, 3), (5, 5)]
    assert module.parse_page_ranges_input("2-2") == [(2, 2)]
    assert module.parse_page_ranges_input("") == []
