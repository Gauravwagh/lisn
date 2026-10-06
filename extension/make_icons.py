"""Generate the toolbar icons with PyMuPDF: python extension/make_icons.py"""

from pathlib import Path

import pymupdf

SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'>
<rect width='128' height='128' rx='28' fill='#3b5bdb'/>
<path d='M34 50v28h18l22 18V32L52 50z' fill='#fff'/>
<path d='M84 46a26 26 0 0 1 0 36M94 36a40 40 0 0 1 0 56' stroke='#fff' stroke-width='8' fill='none' stroke-linecap='round'/>
</svg>"""

here = Path(__file__).parent / "icons"
here.mkdir(exist_ok=True)
for size in (16, 48, 128):
    doc = pymupdf.open("svg", SVG.encode())
    page = doc[0]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(size / page.rect.width, size / page.rect.height), alpha=True)
    pix.save(str(here / f"icon{size}.png"))
print("icons written")
