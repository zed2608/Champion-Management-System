"""One PDF writer for every printed table in the system (Reports, Tracking audit report).

``render_pdf`` draws the company header, any note lines, then one or more titled tables onto a single tall page image and saves it as a
PDF with Pillow (no extra libraries). Pure drawing: it knows nothing about the database or Tk.
"""
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

CANVAS_W = 900
LINE_H = 28


def _fonts():
    try:
        return (ImageFont.truetype("arialbd.ttf", 26), ImageFont.truetype("arialbd.ttf", 16), ImageFont.truetype("arial.ttf", 14))
    except IOError:
        d = ImageFont.load_default()
        return d, d, d


def _wrap(text, font, max_w):
    words, lines, cur = str(text).split(), [], ""
    for word in words:
        test = (cur + " " + word).strip()
        try:
            w = font.getlength(test)
        except AttributeError:
            w = len(test) * 8
        if w <= max_w - 4:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def render_pdf(title, criteria, sections, path, notes=(), generated=None):
    """sections: [(heading or None, [column labels], [[cell, ...], ...], optional [relative column widths])]. notes: extra lines under the header. Returns ``path``."""
    f_title, f_head, f_body = _fonts()
    generated = generated or datetime.now().strftime("%B %d, %Y %I:%M %p")
    laid_out = []
    for section in sections:
        heading, labels, rows = section[:3]
        weights = list(section[3]) if len(section) > 3 else [1] * len(labels)       # optional relative column widths
        unit = (CANVAS_W - 60) / sum(weights)
        widths = [int(unit * w) for w in weights]
        col_x = [30 + sum(widths[:i]) for i in range(len(labels))]
        wrapped_rows = []
        for row in rows:
            wrapped = [_wrap(cell, f_body, widths[j]) for j, cell in enumerate(row)]
            wrapped_rows.append((wrapped, max(len(lines) for lines in wrapped) * LINE_H))
        laid_out.append((heading, labels, col_x, wrapped_rows))
    note_lines = [line for n in notes for line in _wrap(n, f_body, CANVAS_W - 60)]
    height = 185 + len(note_lines) * 22 + sum((50 if h else 10) + 40 + sum(rh for _, rh in wr) + 60 for h, _, _, wr in laid_out) + 40
    canvas = Image.new("RGB", (CANVAS_W, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), "CHAMPION FINE TOOLING CORPORATION", fill="#1E4528", font=f_title)
    draw.text((30, 60), title, fill="black", font=f_head)
    draw.text((30, 90), f"Generated: {generated}", fill="gray", font=f_body)
    draw.text((30, 115), criteria, fill="#444444", font=f_body)
    draw.line((30, 145, CANVAS_W - 30, 145), fill="#1E4528", width=2)
    y = 155
    for line in note_lines:
        draw.text((30, y), line, fill="#1E4528", font=f_body)
        y += 22
    y += 5
    total = 0
    for heading, labels, col_x, wrapped_rows in laid_out:
        if heading:
            draw.text((30, y), heading, fill="#1E4528", font=f_head)
            y += 32
        for j, label in enumerate(labels):
            draw.text((col_x[j], y), label, fill="#1E4528", font=f_head)
        draw.line((30, y + 20, CANVAS_W - 30, y + 20), fill="#CCCCCC", width=1)
        y += 28
        for r_idx, (wrapped, row_h) in enumerate(wrapped_rows):
            draw.rectangle([30, y - 2, CANVAS_W - 30, y + row_h - 4], fill="#F9FAFB" if r_idx % 2 == 0 else "white")
            for j, lines in enumerate(wrapped):
                for li, line in enumerate(lines):
                    draw.text((col_x[j], y + li * LINE_H), line, fill="black", font=f_body)
            y += row_h
        draw.line((30, y + 8, CANVAS_W - 30, y + 8), fill="#CCCCCC", width=1)
        draw.text((30, y + 16), f"Records: {len(wrapped_rows)}", fill="gray", font=f_body)
        total += len(wrapped_rows)
        y += 50
    canvas.save(path, "PDF", resolution=100.0)
    return path
