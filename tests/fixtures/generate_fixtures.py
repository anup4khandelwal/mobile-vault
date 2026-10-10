#!/usr/bin/env python3
"""Builds the synthetic fixtures under tests/fixtures/ - pure stdlib, no
external PDF/image tools needed (this sandbox has none). Every value here is
fabricated: fake names, fake PAN/Aadhaar-shaped numbers, fake phone numbers,
fake lab values. Run with `python3 tests/fixtures/generate_fixtures.py` to
regenerate.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def build_pdf(page_texts: list[str]) -> bytes:
    """A minimal but valid multi-page PDF with real extractable text,
    built by hand (no poppler/reportlab available in this sandbox)."""
    n = len(page_texts)
    font_obj = 3
    page_objs = [4 + 2 * i for i in range(n)]
    content_objs = [5 + 2 * i for i in range(n)]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_objs)}] /Count {n} >>".encode(),
        font_obj: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for i, text in enumerate(page_texts):
        page_num, content_num = page_objs[i], content_objs[i]
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_num} 0 R >>"
        ).encode()

        parts = ["BT", "/F1 11 Tf", "14 TL", "72 740 Td"]
        for j, line in enumerate(text.split("\n")):
            esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            if j > 0:
                parts.append("T*")
            parts.append(f"({esc}) Tj")
        parts.append("ET")
        stream = "\n".join(parts).encode()
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    buf = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(buf)
        buf += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"

    xref_offset = len(buf)
    max_num = max(objects)
    buf += f"xref\n0 {max_num + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        off = offsets.get(num)
        buf += (f"{off:010d} 00000 n \n" if off is not None else "0000000000 65535 f \n").encode()
    buf += f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return bytes(buf)


def build_png(width: int = 4, height: int = 4, rgb=(220, 220, 220)) -> bytes:
    """A minimal valid solid-colour RGB PNG, built from stdlib zlib only."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = bytes(rgb) * width
    raw = (b"\x00" + row) * height
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


DIGITAL_PDF_TEXT = """FICTIONAL BANK OF INDIA
INTEREST CERTIFICATE FOR FY 2024-25
Customer Name: Rohan Mehta
PAN: ABCDE1234F
Account Number: 123456789012
IFSC: FBOI0001234
Mobile: +91 98765 43210
Email: rohan.mehta.fake@example.test
Interest credited this year: Rs. 18,432.00
This is a synthetic fixture for automated testing only. No real person,
account, or financial data is represented here. Padding text follows so
that the extractable character count per page clears the scanned-page
detection threshold used by the extraction pipeline during testing."""

SCANNED_TRIGGER_PDF_TEXT = "Pg 1"

SAMPLE_TXT = """FICTIONAL DIAGNOSTIC LABS
LAB REPORT
Patient Name: Asha Verma
UHID: FAKE-UHID-00219
DOB: 14-03-1988
Aadhaar: 2345 6789 1234
HAEMOGLOBIN: 13.2 g/dL (Normal: 12.0 - 15.5)
Findings: all values within normal range for this synthetic fixture.
This document is entirely fabricated for the mobile-vault test suite.
"""


def main() -> None:
    (FIXTURES_DIR / "digital.pdf").write_bytes(build_pdf([DIGITAL_PDF_TEXT]))
    (FIXTURES_DIR / "scanned_trigger.pdf").write_bytes(build_pdf([SCANNED_TRIGGER_PDF_TEXT]))
    (FIXTURES_DIR / "sample.png").write_bytes(build_png())
    (FIXTURES_DIR / "sample.txt").write_text(SAMPLE_TXT)
    (FIXTURES_DIR / "duplicate_of_sample.txt").write_text(SAMPLE_TXT)
    (FIXTURES_DIR / "unsupported.xyz").write_text("not a supported format\n")
    print(f"wrote fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
