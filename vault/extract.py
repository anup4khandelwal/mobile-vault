"""Text extraction: pdftotext first, OCR fallback for scanned pages.

One page at a time: each rasterised page image is deleted immediately after
OCR, so a multi-page scan never holds more than one page image on disk.
All subprocess calls go through the small wrapper functions below so tests
can monkeypatch them without needing poppler/tesseract installed.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_WHITESPACE_RE = re.compile(r"\s+")


class LockedPdfError(Exception):
    """pdftotext reported a missing/incorrect password."""


class ExtractionError(Exception):
    pass


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def pdf_to_text(pdf_path: Path, password: str | None = None) -> str:
    cmd = ["pdftotext", "-layout"]
    if password is not None:
        cmd += ["-upw", password]
    cmd += [str(pdf_path), "-"]
    proc = run(cmd)
    stderr = (proc.stderr or "").lower()
    if "password" in stderr or "incorrect" in stderr:
        raise LockedPdfError()
    if proc.returncode != 0:
        raise ExtractionError(f"pdftotext exit {proc.returncode}")
    return proc.stdout


def count_pdf_pages(pdf_path: Path, pdftotext_output: str | None = None) -> int:
    proc = run(["pdfinfo", str(pdf_path)])
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    if pdftotext_output is not None:
        return pdftotext_output.count("\f") + 1
    return 1


def rasterize_page(pdf_path: Path, page_num: int, out_dir: Path, dpi: int = 200) -> Path | None:
    prefix = Path(out_dir) / "page"
    run(
        [
            "pdftoppm",
            "-r", str(dpi),
            "-gray",
            "-f", str(page_num),
            "-l", str(page_num),
            str(pdf_path),
            str(prefix),
        ]
    )
    matches = sorted(Path(out_dir).glob("page*"))
    return matches[0] if matches else None


def ocr_image(image_path: Path, langs: str = "eng") -> str:
    proc = run(["tesseract", str(image_path), "stdout", "-l", langs])
    if proc.returncode != 0:
        raise ExtractionError(f"tesseract exit {proc.returncode}")
    return proc.stdout


def _non_whitespace_len(text: str) -> int:
    return len(_WHITESPACE_RE.sub("", text))


def extract_pdf(
    pdf_path: Path,
    *,
    min_chars_per_page: int = 100,
    langs: str = "eng",
    dpi: int = 200,
    password: str | None = None,
) -> tuple[str, int]:
    text = pdf_to_text(pdf_path, password=password)  # raises LockedPdfError
    pages = count_pdf_pages(pdf_path, pdftotext_output=text)
    density = _non_whitespace_len(text) / max(pages, 1)

    if density >= min_chars_per_page:
        return text, pages

    ocr_parts = []
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for page_num in range(1, pages + 1):
            image = rasterize_page(pdf_path, page_num, tmp, dpi=dpi)
            if image is None:
                continue
            try:
                ocr_parts.append(ocr_image(image, langs=langs))
            finally:
                image.unlink(missing_ok=True)
    return "\f".join(ocr_parts), pages


def extract_image(image_path: Path, *, langs: str = "eng") -> tuple[str, int]:
    return ocr_image(image_path, langs=langs), 1


def extract_txt(txt_path: Path) -> tuple[str, int]:
    return Path(txt_path).read_text(errors="replace"), 1


def extract_document(
    path: Path,
    ext: str,
    *,
    min_chars_per_page: int = 100,
    langs: str = "eng",
    dpi: int = 200,
    password: str | None = None,
) -> tuple[str, int]:
    ext = ext.lower()
    if ext == ".pdf":
        return extract_pdf(
            path, min_chars_per_page=min_chars_per_page, langs=langs, dpi=dpi, password=password
        )
    if ext in (".jpg", ".jpeg", ".png"):
        return extract_image(path, langs=langs)
    if ext == ".txt":
        return extract_txt(path)
    raise ValueError(f"unsupported extension: {ext}")
