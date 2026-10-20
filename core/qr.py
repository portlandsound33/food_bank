"""QR code + printable membership card (CR80, 3.375" x 2.125" @ 300 dpi)."""
from __future__ import annotations

import io
import re

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M

from .config import MEMBER_PREFIX, ORG_NAME

CARD_SIZE = (1012, 638)
_CODE_RE = re.compile(rf"^\s*(?:{re.escape(MEMBER_PREFIX)}[-_ ]?)?0*(\d{{1,9}})\s*$", re.IGNORECASE)


def parse_member_code(scanned: str) -> int | None:
    """'RGFP-000123', 'rgfp123', '123' -> 123. Returns None for anything else."""
    m = _CODE_RE.match(scanned or "")
    return int(m.group(1)) if m else None


def make_qr_png(payload: str, box_size: int = 10) -> bytes:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf"])  # Linux / Windows / macOS
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_member_card(full_name: str, member_code: str, qr_png: bytes, since: str = "") -> bytes:
    """A print-ready PNG for a card printer (front side)."""
    w, h = CARD_SIZE
    card = Image.new("RGB", CARD_SIZE, "white")
    d = ImageDraw.Draw(card)
    # brand band
    d.rectangle([0, 0, w, 120], fill=(158, 52, 36))
    d.rectangle([0, 120, w, 132], fill=(32, 138, 140))
    d.text((40, 30), ORG_NAME.upper(), font=_font(46, bold=True), fill="white")
    d.text((42, 84), "MEMBER CARD", font=_font(24), fill=(250, 222, 200))
    # QR
    qr = Image.open(io.BytesIO(qr_png)).convert("RGB").resize((400, 400), Image.NEAREST)
    card.paste(qr, (w - 440, 175))
    # text
    name = full_name if len(full_name) <= 22 else full_name[:21] + "…"
    d.text((40, 200), name, font=_font(52, bold=True), fill=(30, 30, 30))
    d.text((40, 290), "Member #", font=_font(26), fill=(110, 110, 110))
    d.text((40, 325), member_code, font=_font(58, bold=True), fill=(158, 52, 36))
    if since:
        d.text((40, 430), f"Member since {since}", font=_font(26), fill=(110, 110, 110))
    d.text((40, 560), "Please bring this card to every visit.", font=_font(24), fill=(110, 110, 110))
    buf = io.BytesIO()
    card.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()
