import os
import io
import uuid
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'certificates')
os.makedirs(CERT_DIR, exist_ok=True)


def _get_font(size, bold=False):
    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf' if bold else '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_certificate(
    sponsor_name: str,
    amount_gd: float,
    date_str: str = None,
    cert_id: str = None,
    certificate_type: str = 'sponsorship'
) -> str:
    """Generate a PNG certificate (sponsorship/collaboration) and return filename."""
    if not cert_id:
        cert_id = uuid.uuid4().hex[:12]
    if not date_str:
        date_str = datetime.utcnow().strftime('%B %d, %Y')

    width, height = 900, 620
    img = Image.new('RGB', (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / height
        r = int(15 + (49 - 15) * ratio)
        g = int(23 + (46 - 23) * ratio)
        b = int(42 + (129 - 42) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    border_color = (99, 102, 241)
    border_width = 8
    draw.rectangle([border_width // 2, border_width // 2, width - border_width // 2, height - border_width // 2],
                   outline=border_color, width=border_width)
    draw.rectangle([border_width + 6, border_width + 6, width - border_width - 6, height - border_width - 6],
                   outline=(139, 92, 246), width=2)

    font_title = _get_font(44, bold=True)
    font_subtitle = _get_font(22, bold=False)
    font_name = _get_font(48, bold=True)
    font_body = _get_font(20, bold=False)
    font_amount = _get_font(36, bold=True)
    font_small = _get_font(16, bold=False)

    def center_text(draw, text, y, font, color):
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, font=font, fill=color)

    is_collaboration = (certificate_type or '').strip().lower() == 'collaboration'
    title_text = 'CERTIFICATE OF COLLABORATION' if is_collaboration else 'CERTIFICATE OF SPONSORSHIP'
    action_text = 'has entered a collaboration partnership with' if is_collaboration else 'has generously sponsored the'
    subject_text = 'Learn & Earn Community Module Program' if is_collaboration else 'Learn & Earn Treasury Contract'
    footer_text = (
        'Thank you for supporting learners through platform collaboration!'
        if is_collaboration
        else 'Thank you for supporting financial inclusion worldwide!'
    )

    star = '\u2605'
    center_text(draw, f'{star}  {title_text}  {star}', 40, font_title, (255, 255, 255))

    draw.line([(60, 105), (width - 60, 105)], fill=(99, 102, 241), width=2)

    center_text(draw, 'GoodDollar Learn & Earn Program', 120, font_subtitle, (167, 139, 250))

    center_text(draw, 'This certifies that', 170, font_body, (200, 200, 220))

    center_text(draw, sponsor_name, 210, font_name, (250, 204, 21))

    center_text(draw, action_text, 278, font_body, (200, 200, 220))
    center_text(draw, subject_text, 308, font_subtitle, (255, 255, 255))

    center_text(draw, 'with a contribution of', 358, font_body, (200, 200, 220))

    amount_display = f'{amount_gd:,.2f} G$' if amount_gd != int(amount_gd) else f'{int(amount_gd):,} G$'
    center_text(draw, amount_display, 388, font_amount, (52, 211, 153))

    draw.line([(60, 455), (width - 60, 455)], fill=(99, 102, 241), width=2)

    center_text(draw, f'Date: {date_str}', 470, font_body, (167, 139, 250))
    center_text(draw, f'Certificate ID: {cert_id}', 500, font_small, (120, 130, 160))

    center_text(draw, 'GoodMarket  \u2022  GoodDollar Ecosystem  \u2022  Powered by Celo', 540, font_small, (120, 130, 160))
    center_text(draw, footer_text, 570, font_body, (200, 200, 220))

    corners = [(20, 20), (width - 40, 20), (20, height - 40), (width - 40, height - 40)]
    corner_size = 20
    corner_color = (250, 204, 21)
    for cx, cy in corners:
        draw.rectangle([cx, cy, cx + corner_size, cy + corner_size], outline=corner_color, width=3)

    prefix = 'collaboration' if is_collaboration else 'sponsorship'
    cert_filename = f'{prefix}_{cert_id}.png'
    cert_path = os.path.join(CERT_DIR, cert_filename)
    img.save(cert_path, 'PNG', optimize=True)
    logger.info(f'Certificate generated: {cert_path}')
    return cert_filename
