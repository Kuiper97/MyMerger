import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "PDFMerger1.0.2.py"

spec = importlib.util.spec_from_file_location("pdfmerger", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PdfUtilsTests(unittest.TestCase):
    def test_parse_page_ranges_input(self):
        self.assertEqual(module.parse_page_ranges_input("1-3,5"), [(1, 3), (5, 5)])
        self.assertEqual(module.parse_page_ranges_input("2-2"), [(2, 2)])
        self.assertEqual(module.parse_page_ranges_input(""), [])

    def test_parse_size_to_bytes(self):
        self.assertEqual(module.parse_size_to_bytes("20 MB"), 20 * 1024 * 1024)
        self.assertEqual(module.parse_size_to_bytes("512KB"), 512 * 1024)

    def test_estimate_target_dpi_from_size(self):
        self.assertEqual(module.estimate_target_dpi_from_size(1000, 500), 212)
        self.assertEqual(module.estimate_target_dpi_from_size(1000, 1000), 300)
        self.assertEqual(module.estimate_target_dpi_from_size(1000, 250, compression_factor=1.2), 137)

    def test_estimate_compression_factor(self):
        self.assertAlmostEqual(module.estimate_compression_factor(30 * 1024 * 1024, 15 * 1024 * 1024), 0.65)
        self.assertAlmostEqual(module.estimate_compression_factor(60 * 1024 * 1024, 15 * 1024 * 1024), 0.325)

    def test_merge_pdfs_saves_output_and_returns_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            first_pdf = temp_path / "first.pdf"
            second_pdf = temp_path / "second.pdf"
            output_pdf = temp_path / "merged.pdf"

            for pdf_path in (first_pdf, second_pdf):
                writer = module.PyPDF2.PdfWriter()
                writer.add_blank_page(width=72, height=72)
                with pdf_path.open("wb") as handle:
                    writer.write(handle)

            result_path = module.merge_pdfs([str(first_pdf), str(second_pdf)], [(1, 1), (1, 1)], output_path=str(output_pdf))

            self.assertEqual(result_path, str(output_pdf))
            self.assertTrue(output_pdf.exists())

            reader = module.PyPDF2.PdfReader(str(output_pdf))
            self.assertEqual(len(reader.pages), 2)

    def test_merge_pdfs_rotates_pages_from_input_angle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_pdf = temp_path / "landscape.pdf"
            output_pdf = temp_path / "merged.pdf"

            writer = module.PyPDF2.PdfWriter()
            writer.add_blank_page(width=144, height=72)
            with input_pdf.open("wb") as handle:
                writer.write(handle)

            module.merge_pdfs([str(input_pdf)], [(1, 1)], output_path=str(output_pdf), rotate_angles=[90])

            reader = module.PyPDF2.PdfReader(str(output_pdf))
            self.assertEqual(len(reader.pages), 1)
            self.assertEqual(reader.pages[0].rotation, 90)


if __name__ == "__main__":
    unittest.main()
