import unittest
from pathlib import Path
from unittest.mock import patch

from vault import extract

FIXTURES = Path(__file__).parent / "fixtures"


class TestExtractTxt(unittest.TestCase):
    def test_extract_txt_reads_file(self):
        text, pages = extract.extract_txt(FIXTURES / "sample.txt")
        self.assertIn("HAEMOGLOBIN", text)
        self.assertEqual(pages, 1)


class TestExtractDigitalPdf(unittest.TestCase):
    """digital.pdf is a real, hand-built PDF with real extractable text -
    pdftotext/pdfinfo aren't installed in this sandbox, so the subprocess
    boundary is mocked, but the density math and branch selection run for
    real against the real fixture text."""

    def test_digital_pdf_skips_ocr(self):
        from tests.fixtures.generate_fixtures import DIGITAL_PDF_TEXT

        with patch.object(extract, "run") as mock_run:
            mock_run.return_value = type(
                "P", (), {"stdout": DIGITAL_PDF_TEXT, "stderr": "", "returncode": 0}
            )()
            with patch.object(extract, "count_pdf_pages", return_value=1):
                with patch.object(extract, "rasterize_page") as mock_raster:
                    text, pages = extract.extract_pdf(FIXTURES / "digital.pdf")
        mock_raster.assert_not_called()
        self.assertEqual(text, DIGITAL_PDF_TEXT)
        self.assertEqual(pages, 1)


class TestExtractScannedPdf(unittest.TestCase):
    def test_low_density_triggers_ocr_and_cleans_up_each_page(self):
        def fake_rasterize(pdf_path, page_num, out_dir, dpi=200):
            img = Path(out_dir) / f"page-{page_num}.png"
            img.write_bytes(b"fake-image-bytes")
            return img

        def fake_ocr(image_path, langs="eng"):
            return f"ocr-text-page-{image_path.stem}"

        with patch.object(extract, "run") as mock_run:
            mock_run.return_value = type(
                "P", (), {"stdout": "Pg 1", "stderr": "", "returncode": 0}
            )()
            with patch.object(extract, "count_pdf_pages", return_value=2):
                with patch.object(extract, "rasterize_page", side_effect=fake_rasterize) as mock_raster:
                    with patch.object(extract, "ocr_image", side_effect=fake_ocr) as mock_ocr:
                        text, pages = extract.extract_pdf(
                            FIXTURES / "scanned_trigger.pdf", min_chars_per_page=100
                        )

        self.assertEqual(mock_raster.call_count, 2)
        self.assertEqual(mock_ocr.call_count, 2)
        self.assertEqual(pages, 2)
        self.assertIn("ocr-text-page-page-1", text)
        self.assertIn("ocr-text-page-page-2", text)

    def test_page_image_deleted_immediately_after_ocr(self):
        created_images = []

        def fake_rasterize(pdf_path, page_num, out_dir, dpi=200):
            img = Path(out_dir) / f"page-{page_num}.png"
            img.write_bytes(b"x")
            created_images.append(img)
            return img

        def fake_ocr(image_path, langs="eng"):
            # at OCR time, only the current page's image should exist on disk
            self.assertTrue(image_path.exists())
            return "text"

        with patch.object(extract, "run") as mock_run:
            mock_run.return_value = type(
                "P", (), {"stdout": "x", "stderr": "", "returncode": 0}
            )()
            with patch.object(extract, "count_pdf_pages", return_value=3):
                with patch.object(extract, "rasterize_page", side_effect=fake_rasterize):
                    with patch.object(extract, "ocr_image", side_effect=fake_ocr):
                        extract.extract_pdf(FIXTURES / "scanned_trigger.pdf", min_chars_per_page=100)

        for img in created_images:
            self.assertFalse(img.exists(), "page image must be deleted right after OCR")


class TestLockedPdf(unittest.TestCase):
    def test_password_error_raises_locked(self):
        with patch.object(extract, "run") as mock_run:
            mock_run.return_value = type(
                "P",
                (),
                {"stdout": "", "stderr": "Incorrect password", "returncode": 1},
            )()
            with self.assertRaises(extract.LockedPdfError):
                extract.pdf_to_text(FIXTURES / "digital.pdf")

    def test_generic_failure_raises_extraction_error_not_locked(self):
        with patch.object(extract, "run") as mock_run:
            mock_run.return_value = type(
                "P", (), {"stdout": "", "stderr": "some other poppler error", "returncode": 1}
            )()
            with self.assertRaises(extract.ExtractionError):
                extract.pdf_to_text(FIXTURES / "digital.pdf")


class TestExtractDocumentDispatch(unittest.TestCase):
    def test_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            extract.extract_document(FIXTURES / "unsupported.xyz", ".xyz")

    def test_png_dispatches_to_image_ocr(self):
        with patch.object(extract, "ocr_image", return_value="ocr text") as mock_ocr:
            text, pages = extract.extract_document(FIXTURES / "sample.png", ".png")
        mock_ocr.assert_called_once()
        self.assertEqual(text, "ocr text")
        self.assertEqual(pages, 1)


if __name__ == "__main__":
    unittest.main()
