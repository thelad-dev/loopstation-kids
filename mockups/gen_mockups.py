# Generator für die Loopstation-Kids-Mockups.
# Schreibt je Ansicht eine SVG-Datei und, wenn cairosvg installiert ist, eine PNG-Datei (1280 x 916).
# Aufruf aus dem Repo-Wurzelverzeichnis:  pip install cairosvg && python mockups/gen_mockups.py
import os, math
OUT = os.path.dirname(os.path.abspath(__file__))  # schreibt neben dieses Skript (mockups/)
W, H, CAP = 1280, 800, 116
FONT = "Inter, 'Noto Sans', 'DejaVu Sans', Arial, sans-serif"
BG = "#0E0E10"; SURF = "#26262B"; SURF2 = "#1B1B1F"; SURF3 = "#3A3A41"
TEXT = "#F2F2F2"; DIM = "#8E8E93"; DARK = "#111114"
GREEN = "#32D74B"; RED = "#FF3B30"; BLUE = "#40A9FF"; ORANGE = "#FF9F0A"
PURPLE = "#C77DFF"; YELLOW = "#FFD60A"; GRAY = "#AEAEB2"; WHITE = "#F2F2F2"; SKY = "#5AC8FA"
PAD = {"white": WHITE, "yellow": YELLOW, "green": GREEN, "red": RED}

ICONS = {
 "play": ("f", ["M7 4 L20 12 L7 20 Z"]),
 "record": ("f", ["M12 5 a7 7 0 1 0 0.01 0 Z"]),
 "stop": ("f", ["M6 6 h12 v12 h-12 Z"]),
 "loop": ("s", ["M17 1l4 4-4 4", "M3 11V9a4 4 0 0 1 4-4h14", "M7 23l-4-4 4-4", "M21 13v2a4 4 0 0 1-4 4H3"]),
 "undo": ("s", ["M1 4v6h6", "M3.51 15a9 9 0 1 0 2.13-9.36L1 10"]),
 "redo": ("s", ["M23 4v6h-6", "M20.49 15a9 9 0 1 1-2.12-9.36L23 10"]),
 "history": ("s", ["M12 2a10 10 0 1 0 0.01 0", "M12 6v6l4 2"]),
 "delete": ("s", ["M12 2a10 10 0 1 0 0.01 0", "M15 9l-6 6", "M9 9l6 6"]),
 "trash": ("s", ["M3 6h18", "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6", "M10 11v6", "M14 11v6", "M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"]),
 "vol_lo": ("s", ["M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 0 1 0 7.07"]),
 "vol_hi": ("s", ["M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 0 1 0 7.07", "M19.07 4.93a10 10 0 0 1 0 14.14"]),
 "lock": ("s", ["M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M7 11V7a5 5 0 0 1 10 0v4"]),
 "unlock": ("s", ["M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M7 11V7a5 5 0 0 1 9.9-1"]),
 "mic": ("s", ["M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v4", "M8 23h8"]),
 "headphones": ("s", ["M3 18v-6a9 9 0 0 1 18 0v6", "M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3z", "M3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"]),
 "save": ("s", ["M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z", "M17 21v-8H7v8", "M7 3v5h8"]),
 "folder": ("s", ["M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"]),
 "download": ("s", ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "M7 10l5 5 5-5", "M12 15V3"]),
 "wave": ("s", ["M2 12c2.5-6 5-6 7 0s4.5 6 7 0 4.5-6 6 0"]),
 "info": ("s", ["M12 2a10 10 0 1 0 0.01 0", "M12 16v-4", "M12 8h.01"]),
 "alert": ("s", ["M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z", "M12 9v4", "M12 17h.01"]),
 "sliders": ("s", ["M4 21v-7", "M4 10V3", "M12 21v-9", "M12 8V3", "M20 21v-5", "M20 12V3", "M1 14h6", "M9 8h6", "M17 16h6"]),
 "check": ("s", ["M20 6L9 17l-5-5"]),
 "x": ("s", ["M18 6L6 18", "M6 6l12 12"]),
 "chev": ("s", ["M6 9l6 6 6-6"]),
 "back": ("s", ["M19 12H5", "M12 19l-7-7 7-7"]),
 "pulse": ("s", ["M22 12h-4l-3 9L9 3l-3 9H2"]),
 "layers": ("s", ["M12 2L2 7l10 5 10-5-10-5z", "M2 17l10 5 10-5", "M2 12l10 5 10-5"]),
 "speaker": ("s", ["M6 2h12a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z", "M12 10a4 4 0 1 0 0.01 0", "M12 6h.01"]),
}

def tw_est(t, size, bold=True):
    w = 0
    for ch in t:
        if ch.isupper() or ch in "MWm": w += 0.70
        elif ch in " .,:;·'|il!()/": w += 0.32
        elif ch.isdigit(): w += 0.60
        else: w += 0.56
    return w * size * (1.0 if bold else 0.94)

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def icon(name, x, y, size, color, sw=2.2):
    kind, paths = ICONS[name]
    s = size / 24.0
    d = " ".join(paths)
    if kind == "f":
        return f'<path transform="translate({x},{y}) scale({s:.4f})" d="{d}" fill="{color}"/>'
    return (f'<path transform="translate({x},{y}) scale({s:.4f})" d="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{sw/s*s:.2f}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>')

def text(x, y, t, size=16, color=TEXT, weight=400, anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}" {extra}>{esc(t)}</text>')

def rect(x, y, w, h, r=12, fill=SURF, stroke=None, sw=2, extra=""):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{st} {extra}/>'

class Doc:
    def __init__(self, num, title, plan, notes, accent):
        self.num, self.title, self.plan, self.notes, self.accent = num, title, plan, notes, accent
        self.el = []
    def add(self, *e): self.el.extend(e)
    def svg(self):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H+CAP}" viewBox="0 0 {W} {H+CAP}">\n'
                f'<title>Mockup {self.num} – {esc(self.title)}</title>\n'
                '<defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
                '<rect width="10" height="10" fill="#2E2E34"/><line x1="0" y1="0" x2="0" y2="10" stroke="#4A4A52" stroke-width="4"/></pattern>'
                '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="10"/></filter></defs>\n'
                f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
                f'<rect x="6" y="6" width="{W-12}" height="{H-12}" rx="26" fill="none" stroke="{self.accent}" stroke-opacity="0.75" stroke-width="4"/>\n')
        body = "\n".join(self.el)
        cap = (f'\n<rect x="0" y="{H}" width="{W}" height="{CAP}" fill="#F4F4F6"/>'
               f'<rect x="0" y="{H}" width="{W}" height="4" fill="{self.accent}"/>'
               + text(24, H+34, f"Mockup {self.num} · {self.title}", 20, DARK, 700)
               + text(W-24, H+34, self.plan, 15, "#55555C", 600, "end"))
        import textwrap
        lines = []
        for n in self.notes:
            lines += textwrap.wrap(n, 172)
        for i, line in enumerate(lines[:4]):
            cap += text(24, H+58+i*19, line, 13.5, "#3A3A41")
        return head + body + cap + "\n</svg>\n"

# ---------------------------------------------------------------- components
def big_button(x, y, w, h, ic, label, accent, state="normal", stacked=False, size=22):
    # state: normal | checked | disabled
    out = []
    if state == "checked":
        out.append(rect(x, y, w, h, 18, accent))
        fg = DARK; ic_c = DARK
    elif state == "disabled":
        out.append(rect(x, y, w, h, 18, "#1A1A1E", "#2C2C31"))
        fg = "#55555C"; ic_c = "#55555C"
    else:
        out.append(rect(x, y, w, h, 18, SURF))
        fg = TEXT; ic_c = accent
    if stacked:
        isz = 34
        out.append(icon(ic, x + w/2 - isz/2, y + 14, isz, ic_c, 2.6))
        out.append(text(x + w/2, y + h - 16, label, size, fg, 700, "middle"))
    else:
        isz = 32
        tw = len(label) * size * 0.56
        total = isz + 12 + tw
        sx = x + (w - total) / 2
        out.append(icon(ic, sx, y + h/2 - isz/2, isz, ic_c, 2.6))
        out.append(text(sx + isz + 12, y + h/2 + size*0.36, label, size, fg, 700))
    return "\n".join(out)

MODES = [("play", "Spielen", GREEN), ("record", "Aufnehmen", RED), ("loop", "Loop", BLUE),
         ("delete", "Löschen", ORANGE), ("history", "Verlauf", PURPLE)]

def mode_bar(active):
    out = []
    x = 28
    for i, (ic, word, acc) in enumerate(MODES):
        out.append(big_button(x, 24, 152, 104, ic, word, acc, "checked" if i == active else "normal", True, 20))
        x += 152 + 12
    return "\n".join(out)

def volume(x=868, y=24, w=384, h=104, val=0.55, ceil=0.75, kid=True):
    """Lautstärkeregler rechts oben. ceil = Eltern-Grenze (Anteil der Spur)."""
    out = [rect(x, y, w, h, 20, SURF)]
    out.append(icon("vol_lo", x + 18, y + h/2 - 16, 32, TEXT, 2.4))
    out.append(icon("vol_hi", x + w - 52, y + h/2 - 16, 32, TEXT, 2.4))
    tx0, tx1 = x + 66, x + w - 66
    ty = y + h/2 + (8 if not kid else 0)
    tw = tx1 - tx0
    cx = tx0 + tw * ceil
    # Bereich über der Elterngrenze: schraffiert, nicht erreichbar
    out.append(f'<rect x="{cx:.1f}" y="{ty-11}" width="{tx1-cx:.1f}" height="22" rx="11" fill="url(#hatch)"/>')
    out.append(f'<rect x="{tx0}" y="{ty-11}" width="{cx-tx0+6:.1f}" height="22" rx="11" fill="#3A3A41"/>')
    kx = tx0 + tw * val
    out.append(f'<rect x="{tx0}" y="{ty-11}" width="{kx-tx0:.1f}" height="22" rx="11" fill="{SKY}"/>')
    out.append(f'<line x1="{cx:.1f}" y1="{ty-20}" x2="{cx:.1f}" y2="{ty+20}" stroke="{GRAY}" stroke-width="3" stroke-linecap="round"/>')
    out.append(icon("lock", cx - 8, ty - 40 if kid else ty + 18, 16, GRAY, 2))
    out.append(f'<circle cx="{kx:.1f}" cy="{ty}" r="27" fill="#FFFFFF" stroke="{SKY}" stroke-width="5"/>')
    if not kid:
        out.append(text(x + 66, y + 26, "Lautstärke 62 %", 14, TEXT, 700))
        out.append(text(x + w - 66, y + 26, "Grenze −6 dBFS", 14, GRAY, 600, "end"))
    return "\n".join(out)

def pad(x, y, s, idx, color="white", overlay=None, shape="square", badge=None, extra=""):
    out = []
    fill = PAD[color]
    r = s * 0.14 if shape == "square" else s / 2
    lit = color in ("green", "red")
    if lit:
        out.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{r}" fill="{fill}" opacity="0.35" filter="url(#soft)"/>')
    stroke = "#FFFFFF" if lit else "#000000"
    out.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-opacity="{0.5 if lit else 0.2}" stroke-width="3"/>')
    if shape == "square":
        out.append(text(x + s*0.09, y + s*0.2, str(idx), s*0.12, "#00000078", 700))
    else:
        out.append(text(x + s/2, y + s*0.2, str(idx), s*0.12, "#00000078", 700, "middle"))
    if overlay:
        isz = s * 0.36
        out.append(icon(overlay, x + s/2 - isz/2, y + s/2 - isz/2, isz, "#00000069", 3.2))
    if badge == "undo":
        bx, by, br = x + s - s*0.17, y + s*0.17, s*0.135
        out.append(f'<circle cx="{bx}" cy="{by}" r="{br+4}" fill="{BG}"/>')
        out.append(f'<circle cx="{bx}" cy="{by}" r="{br}" fill="{GRAY}" stroke="#FFFFFF" stroke-width="3"/>')
        out.append(icon("undo", bx - br*0.6, by - br*0.6, br*1.2, DARK, 3))
    out.append(extra)
    return "\n".join(out)

def grid_pos(i, s=164, gap=16, top=146):
    cols = 4
    total = cols*s + (cols-1)*gap
    left = (W - total) // 2
    r, c = divmod(i, cols)
    return left + c*(s+gap), top + r*(s+gap), s

def pads(colors, overlays=None, special=None):
    overlays = overlays or {}
    special = special or {}
    out = []
    for i in range(12):
        if i in special:
            out.append(special[i]); continue
        x, y, s = grid_pos(i)
        out.append(pad(x, y, s, i+1, colors[i], overlays.get(i)))
    return "\n".join(out)

def pulse_dots(cx, cy, beat=0, dim=False, n=4):
    out = []
    for k in range(n):
        x = cx + (k - (n-1)/2) * 34
        on = (k == beat) and not dim
        if on:
            out.append(f'<circle cx="{x}" cy="{cy}" r="16" fill="{SKY}" opacity="0.25"/>')
        out.append(f'<circle cx="{x}" cy="{cy}" r="{10 if on else 8}" fill="{SKY if on else "#3A3A41"}"/>')
    return "\n".join(out)

def kid_bottom(redo=False, beat=0, pulse_dim=False, status=None):
    out = [big_button(28, 684, 236, 92, "undo", "Zurück", GRAY, "normal", False, 24),
           big_button(276, 684, 236, 92, "redo", "Wiederholen", GRAY, "normal" if redo else "disabled", False, 22),
           big_button(524, 684, 236, 92, "stop", "Alles still", GRAY, "normal", False, 24)]
    out.append(rect(772, 684, 380, 92, 18, SURF2))
    out.append(pulse_dots(962, 716, beat, pulse_dim))
    if status:
        out.append(text(962, 760, status, 15, DIM, 500, "middle"))
    else:
        out.append(text(962, 760, "Puls", 13, "#55555C", 500, "middle"))
    # Eltern-Zugang: klein, unauffällig, lange halten
    out.append(rect(1164, 684, 88, 92, 18, SURF2, "#2C2C31"))
    out.append(icon("lock", 1192, 700, 32, "#6E6E75", 2.2))
    out.append(text(1208, 756, "Eltern", 13, "#6E6E75", 600, "middle"))
    return "\n".join(out)

def kid_doc(num, title, plan, notes, mode=0):
    d = Doc(num, title, plan, notes, MODES[mode][2])
    d.add(mode_bar(mode), volume())
    return d

# ---------------------------------------------------------------- parent components
NAV = [("sliders", "Lautstärke & Pegel"), ("headphones", "Geräte & Audio"), ("pulse", "Takt & Loop"),
       ("history", "Verlauf & Undo"), ("layers", "Erweitert"), ("save", "Sets"), ("download", "Export")]
PACC = "#7FA7FF"

def parent_doc(num, title, plan, notes, nav_active):
    d = Doc(num, title, plan, notes, PACC)
    d.add(rect(28, 24, 260, 104, 20, SURF))
    d.add(icon("back", 48, 60, 32, TEXT, 2.6), text(92, 70, "Zur Kinderseite", 18, TEXT, 700),
          text(92, 96, "Eltern-Modus beenden", 13, DIM))
    d.add(icon("unlock", 312, 50, 34, PACC, 2.4), text(360, 72, "Elternbereich", 30, TEXT, 800),
          text(360, 102, "Änderungen gelten sofort · gespeichert in settings.toml", 14, DIM))
    d.add(volume(kid=False))
    y = 148
    for i, (ic, label) in enumerate(NAV):
        act = i == nav_active
        d.add(rect(28, y, 260, 60, 14, "#2F3550" if act else SURF2, PACC if act else None, 2))
        d.add(icon(ic, 46, y + 18, 24, PACC if act else DIM, 2.2),
              text(84, y + 37, label, 17, TEXT if act else "#C7C7CC", 700 if act else 500))
        y += 70
    d.add(text(40, 676, "Lokal · ohne Konto · ohne Internet", 13, "#6E6E75"))
    d.add(text(40, 698, "Neustart nötig nur für:", 13, "#6E6E75"))
    d.add(text(40, 718, "sample_rate, rows, cols, data_dir", 13, "#6E6E75"))
    return d

CX0, CX1 = 312, 1252  # Inhaltsbereich Eltern

def card(x, y, w, h, title=None, sub=None):
    out = [rect(x, y, w, h, 18, SURF2, "#2C2C31", 1.5)]
    if title:
        out.append(text(x + 22, y + 36, title, 19, TEXT, 700))
    if sub:
        out.append(text(x + 22, y + 60, sub, 13.5, DIM))
    return "\n".join(out)

def toggle(x, y, on, label, sub=None, badge=None):
    out = []
    tw, th = 64, 36
    out.append(rect(x, y, tw, th, 18, GREEN if on else "#48484F"))
    kx = x + (tw - 18 if on else 18)
    out.append(f'<circle cx="{kx}" cy="{y+18}" r="14" fill="#FFFFFF"/>')
    out.append(text(x + tw + 16, y + (16 if sub else 24), label, 16.5, TEXT, 600))
    if sub:
        out.append(text(x + tw + 16, y + 36, sub, 13, DIM))
    if badge:
        bw = len(badge) * 7.4 + 18
        lx = x + tw + 16 + tw_est(label, 16.5) + 12
        out.append(rect(lx, y + 1, bw, 22, 11, "#3A3A41"))
        out.append(text(lx + bw/2, y + 16.5, badge, 12, GRAY, 700, "middle"))
    return "\n".join(out)

def hslider(x, y, w, frac, left_label, right_label, value_label, color=PACC):
    out = [rect(x, y - 6, w, 12, 6, "#3A3A41"), rect(x, y - 6, w * frac, 12, 6, color),
           f'<circle cx="{x + w*frac:.1f}" cy="{y}" r="14" fill="#FFFFFF" stroke="{color}" stroke-width="4"/>',
           text(x, y + 34, left_label, 12.5, DIM), text(x + w, y + 34, right_label, 12.5, DIM, 400, "end"),
           text(x + w*frac, y - 22, value_label, 14, TEXT, 700, "middle")]
    return "\n".join(out)

def button(x, y, w, h, label, kind="secondary", ic=None, size=16):
    if kind == "primary":
        bg, fg, st = PACC, DARK, None
    elif kind == "danger":
        bg, fg, st = "#3A1F1F", "#FF8A80", "#FF3B3080"
    elif kind == "disabled":
        bg, fg, st = "#1A1A1E", "#55555C", "#2C2C31"
    else:
        bg, fg, st = SURF, TEXT, "#3A3A41"
    out = [rect(x, y, w, h, 12, bg, st, 1.5)]
    if ic:
        tw = len(label) * size * 0.55
        total = 22 + 10 + tw
        sx = x + (w - total) / 2
        out.append(icon(ic, sx, y + h/2 - 11, 22, fg, 2.2))
        out.append(text(sx + 32, y + h/2 + size*0.36, label, size, fg, 700))
    else:
        out.append(text(x + w/2, y + h/2 + size*0.36, label, size, fg, 700, "middle"))
    return "\n".join(out)

def select(x, y, w, value, sub=None, h=48):
    out = [rect(x, y, w, h, 12, SURF, "#3A3A41", 1.5), text(x + 16, y + (21 if sub else h/2 + 6), value, 15.5, TEXT, 600)]
    if sub:
        out.append(text(x + 16, y + 39, sub, 12, DIM))
    out.append(icon("chev", x + w - 36, y + h/2 - 11, 22, DIM, 2.2))
    return "\n".join(out)

def note(x, y, w, h, lines, kind="info"):
    col = {"info": "#7FA7FF", "warn": ORANGE, "ok": GREEN}[kind]
    out = [rect(x, y, w, h, 14, col + "18", col + "66", 1.5), icon("alert" if kind == "warn" else ("check" if kind == "ok" else "info"), x + 16, y + 16, 24, col, 2.2)]
    for i, l in enumerate(lines):
        out.append(text(x + 52, y + 33 + i * 21, l, 14, TEXT if i == 0 else "#C7C7CC", 700 if i == 0 else 400))
    return "\n".join(out)

def radio(x, y, on, label, sub=None, tag=None, dis=False):
    out = [f'<circle cx="{x+12}" cy="{y+12}" r="11" fill="none" stroke="{PACC if on else "#6E6E75"}" stroke-width="2.5"/>']
    if on:
        out.append(f'<circle cx="{x+12}" cy="{y+12}" r="6" fill="{PACC}"/>')
    out.append(text(x + 34, y + 18, label, 15.5, "#6E6E75" if dis else TEXT, 700 if on else 500))
    if tag:
        tx = x + 34 + tw_est(label, 15.5) + 10
        tw = len(tag) * 7 + 16
        out.append(rect(tx, y + 2, tw, 21, 10, "#2F3550" if on else "#3A3A41"))
        out.append(text(tx + tw/2, y + 17, tag, 11.5, PACC if on else GRAY, 700, "middle"))
    if sub:
        out.append(text(x + 34, y + 38, sub, 12.5, DIM))
    return "\n".join(out)

def meter(x, y, w, h, level, peak, clip=False, scale=True):
    # dBFS-Skala -48..0 ; Zielbereich -12..-6
    def px(db): return x + w * (db + 48) / 48
    out = [rect(x, y, w, h, 6, "#1A1A1E", "#3A3A41", 1)]
    out.append(f'<rect x="{px(-12):.1f}" y="{y}" width="{px(-6)-px(-12):.1f}" height="{h}" fill="{GREEN}" opacity="0.14"/>')
    lv = px(level)
    out.append(f'<rect x="{x+2}" y="{y+3}" width="{min(lv,px(-12))-x-2:.1f}" height="{h-6}" rx="3" fill="{GREEN}"/>')
    if lv > px(-12):
        out.append(f'<rect x="{px(-12):.1f}" y="{y+3}" width="{min(lv,px(-3))-px(-12):.1f}" height="{h-6}" fill="{YELLOW}"/>')
    if lv > px(-3):
        out.append(f'<rect x="{px(-3):.1f}" y="{y+3}" width="{lv-px(-3):.1f}" height="{h-6}" fill="{RED}"/>')
    out.append(f'<rect x="{px(peak)-1.5:.1f}" y="{y+1}" width="3" height="{h-2}" fill="#FFFFFF"/>')
    if scale:
        for db in (-48, -36, -24, -18, -12, -6, -3, 0):
            out.append(f'<line x1="{px(db):.1f}" y1="{y+h}" x2="{px(db):.1f}" y2="{y+h+6}" stroke="#6E6E75" stroke-width="1.5"/>')
            out.append(text(px(db), y + h + 20, f"{db}", 11.5, DIM, 500, "middle"))
        out.append(text((px(-12)+px(-6))/2, y - 8, "Ziel −12 … −6 dBFS", 11.5, GREEN, 700, "middle"))
    return "\n".join(out)

def waveform(x, y, w, h, seed=1, color=SKY, density=160):
    import random
    rnd = random.Random(seed)
    out = []
    step = w / density
    for i in range(density):
        t = i / density
        env = (0.25 + 0.75 * math.exp(-((t * 4) % 1) * 3.2))
        a = env * (0.55 + 0.45 * rnd.random()) * h / 2
        cx = x + i * step + step / 2
        out.append(f'<line x1="{cx:.1f}" y1="{y+h/2-a:.1f}" x2="{cx:.1f}" y2="{y+h/2+a:.1f}" stroke="{color}" stroke-width="{max(1.2, step*0.6):.1f}" stroke-linecap="round"/>')
    return "\n".join(out)

docs = []

# ============================================================ KINDERSEITE
# 01 Spielen (Grundansicht)
d = kid_doc("01", "Kinderseite – Spielen (Grundansicht)", "Plan §3 Kindbereich, §6.3, §9.1, §2.2 Regel 7",
            ["Strikt dünn: Modi, 12 Pads, Zurück/Wiederholen, Alles still, Puls, Lautstärke rechts oben. Kein Menü, keine Wellenform, kein Export, kein Gerätedialog.",
             "Padfarben wie heute: weiß = leer, gelb = Aufnahme da, grün = spielt/loopt, rot = nimmt auf. Schraffur rechts im Regler = über der Eltern-Grenze, nicht erreichbar."], 0)
cols = ["green", "yellow", "white", "white", "green", "white", "yellow", "white", "white", "green", "white", "white"]
d.add(pads(cols), kid_bottom(redo=False, beat=1))
docs.append(("01_kinderseite_spielen", d))

# 02 Aufnahme mit Pegel / zu laut
d = kid_doc("02", "Kinderseite – Aufnehmen mit Pegel- und „zu laut“-Zeichen", "Plan §7 (1), §3.1, §2.2 Regel 5",
            ["Pad 6 nimmt auf: große Sekunden-Restzeit, Fortschrittsbalken, grobe 3-Stufen-Pegelanzeige. Bei Clipping zusätzlich weißes Warnschild mit rotem Rand + Wort („zu laut“) – Form UND Farbe.",
             "Pads im Aufnehmen-Modus zeigen den roten Punkt. Zu kurze Aufnahme: kurze Statuszeile „Zu kurz – nochmal!“, kein Dialog."], 1)
cols = ["green", "yellow", "white", "white", "green", "red", "yellow", "white", "white", "green", "white", "white"]
ov = {i: "record" for i in range(12) if i != 5}
x, y, s = grid_pos(5)
rec = pad(x, y, s, 6, "red")
rec += text(x + s/2, y + s*0.58, "4", s*0.34, "#FFFFFF", 800, "middle")
inset = s * 0.08
rec += rect(x + inset, y + s - inset - 12, s - 2*inset, 12, 6, "#00000046") + rect(x + inset, y + s - inset - 12, (s - 2*inset) * 0.55, 12, 6, "#FFFFFF")
# grobe Stufen rechts oben im Pad
for k in range(3):
    rec += rect(x + s - 38 + k*10, y + 40 - k*8, 7, 12 + k*8, 2, "#FFFFFF")
# Warnschild "zu laut" neben dem Pad (über Pad 7, gut sichtbar)
wx, wy = x + s - 30, y - 34
badge = rect(wx, wy, 132, 52, 26, "#FFFFFF", RED, 4)
badge += icon("alert", wx + 12, wy + 13, 26, RED, 2.6) + text(wx + 46, wy + 33, "zu laut", 19, RED, 800)
d.add(pads(cols, ov, {5: rec}), badge, kid_bottom(redo=False, beat=2, status="Pad 6 nimmt auf"))
docs.append(("02_kinderseite_aufnahme_zu_laut", d))

# 03 Warten auf Loop-Anfang (Puls)
d = kid_doc("03", "Kinderseite – Warten auf den Loop-Anfang (ruhiger Puls)", "Plan §2.2 Regel 7, §13 Launch-Quantisierung, §3.2 Metronom",
            ["Loop-Modus: Pad 2 startet am nächsten Takt-Anfang. Bis dahin weicher, langsamer Puls-Ring (kein Blinken) und ein sich füllender Balken – vorhersehbar statt Überraschung.",
             "Unten nur visueller Puls (4 Punkte = Schläge des Takts). Kein Ton-Metronom auf der Kinderseite."], 2)
cols = ["green", "yellow", "white", "white", "green", "yellow", "yellow", "white", "white", "green", "white", "white"]
ov = {0: "stop", 4: "stop", 9: "stop", 5: "loop", 6: "loop"}
x, y, s = grid_pos(1)
wp = ""
for k, op in enumerate((0.10, 0.18, 0.30)):
    g = 20 - k * 7
    wp += f'<rect x="{x-g}" y="{y-g}" width="{s+2*g}" height="{s+2*g}" rx="{s*0.14+g}" fill="none" stroke="{SKY}" stroke-opacity="{op}" stroke-width="5"/>'
wp += pad(x, y, s, 2, "yellow", "loop")
wp += rect(x + inset, y + s - inset - 12, s - 2*inset, 12, 6, "#00000030") + rect(x + inset, y + s - inset - 12, (s - 2*inset) * 0.7, 12, 6, SKY)
d.add(pads(cols, ov, {1: wp}), kid_bottom(redo=False, beat=3, status="Gleich geht’s los …"))
docs.append(("03_kinderseite_warten_puls", d))

# 04 Freier Modus
d = kid_doc("04", "Kinderseite – Pad im freien Modus (Summen ohne Takt)", "Plan §2.3 Freier Modus pro Pad",
            ["Pad 7 ist im freien Modus: Form wechselt von Quadrat zu Kreis + Wellen-Symbol (nicht nur Farbe). Läuft in eigener Länge, wird nicht ins Raster geschnitten.",
             "Einstieg: Pad lange halten – ein Ring füllt sich sichtbar (Pad 3). Zurück geht mit demselben langen Halten oder über „Zurück“."], 0)
cols = ["green", "yellow", "yellow", "white", "green", "white", "green", "white", "white", "green", "white", "white"]
x, y, s = grid_pos(6)
fp = pad(x, y, s, 7, "green", "wave", shape="circle")
x3, y3, s3 = grid_pos(2)
hp = pad(x3, y3, s3, 3, "yellow")
cx, cy, rr = x3 + s3/2, y3 + s3*0.47, s3*0.25
hp += f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="none" stroke="#00000030" stroke-width="12"/>'
circ = 2*math.pi*rr
hp += f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="none" stroke="{DARK}" stroke-width="12" stroke-linecap="round" stroke-dasharray="{circ*0.62:.1f} {circ:.1f}" transform="rotate(-90 {cx} {cy})"/>'
hp += icon("wave", cx - 18, cy - 18, 36, DARK, 3)
hp += rect(x3 + s3/2 - 46, y3 + s3 - 36, 92, 26, 13, "#00000055") + text(x3 + s3/2, y3 + s3 - 18, "halten …", 14, "#FFFFFF", 700, "middle")
d.add(pads(cols, {}, {6: fp, 2: hp}), kid_bottom(redo=False, beat=0))
docs.append(("04_kinderseite_freier_modus", d))

# 05 Undo am Pad + Wiederholen
d = kid_doc("05", "Kinderseite – Zurück am Pad und Wiederholen", "Plan §6.2, §6.3 (undo mit pad, redo), §15 Nr. 1 und 10",
            ["Nach einer Änderung bekommt nur dieses Pad ein graues Zurück-Abzeichen (Farbe + Pfeil-Form): Tipp darauf nimmt nur die letzte Änderung an Pad 4 zurück.",
             "Globales „Zurück“ bleibt unten groß. „Wiederholen“ ist nur aktiv, wenn es etwas wiederherzustellen gibt (hier aktiv). Feingeste mit Kindern testen (Plan §16)."], 0)
cols = ["green", "yellow", "white", "yellow", "green", "white", "yellow", "white", "white", "green", "white", "white"]
x, y, s = grid_pos(3)
up = pad(x, y, s, 4, "yellow", badge="undo")
d.add(pads(cols, {}, {3: up}), kid_bottom(redo=True, beat=2, status="Pad 4: zurück möglich"))
docs.append(("05_kinderseite_zurueck_wiederholen", d))

# 06 Alles still
d = kid_doc("06", "Kinderseite – „Alles still“ (alle Loops angehalten)", "Plan §3 Kindbereich, §0 Ist-Stand",
            ["Ein Druck auf „Alles still“: alle Loops stoppen sanft, Aufnahmen bleiben erhalten (gelb). Puls ruht (graue Punkte), Statuszeile ruhig, keine Animation.",
             "„Alle löschen“ liegt NICHT mehr auf der Kinderseite (Plan: Kindseite strikt dünn) – siehe Mockup 12 (Elternbereich)."], 0)
cols = ["yellow", "yellow", "white", "white", "yellow", "white", "yellow", "white", "white", "yellow", "white", "white"]
d.add(pads(cols), kid_bottom(redo=False, pulse_dim=True, status="Alles still"))
d.add(rect(524, 684, 236, 92, 18, "none", GRAY, 3))
docs.append(("06_kinderseite_alles_still", d))

# 07 Verlauf (Kind)
d = kid_doc("07", "Kinderseite – Verlauf eines Pads (ältere Aufnahmen zurückholen)", "Plan §0 (Verlauf / restore_pad), §6.1, §15 Nr. 14",
            ["Verlauf-Modus, Pad 5 angetippt: große Kacheln mit den letzten Aufnahmen dieses Pads. Anhören (▶) und „Nehmen“ (✓). Keine Wellenform, keine Zeitachse.",
             "Neue Aufnahme ersetzt den Take; der alte landet hier (Session-View-Prinzip „Clip neu aufnehmen“)."], 4)
cols = ["green", "yellow", "white", "white", "green", "white", "yellow", "white", "white", "green", "white", "white"]
d.add(pads(cols, {i: "history" for i in (0, 1, 4, 6, 9)}), kid_bottom(beat=1))
d.add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#000000" opacity="0.62"/>')
d.add(rect(190, 170, 900, 470, 28, "#1F1F24", PURPLE, 3))
d.add(icon("history", 226, 200, 40, PURPLE, 2.6), text(282, 232, "Pad 5 – frühere Aufnahmen", 28, TEXT, 800))
for k, (lab, age, cur) in enumerate([("Jetzt", "läuft gerade", True), ("Vorher", "vor 2 Min.", False), ("Davor", "vor 5 Min.", False)]):
    tx = 226 + k * 284
    d.add(rect(tx, 270, 260, 250, 22, "#2B2B31", GREEN if cur else "#3A3A41", 3 if cur else 1.5))
    d.add(text(tx + 130, 312, lab, 24, TEXT, 800, "middle"), text(tx + 130, 340, age, 15, DIM, 500, "middle"))
    d.add(rect(tx + 24, 366, 100, 100, 20, SURF3), icon("play", tx + 52, 394, 44, GREEN))
    if cur:
        d.add(rect(tx + 136, 366, 100, 100, 20, "#1F3A26", GREEN, 2), icon("check", tx + 164, 394, 44, GREEN, 3.4))
    else:
        d.add(rect(tx + 136, 366, 100, 100, 20, SURF3), icon("check", tx + 164, 394, 44, TEXT, 3.4))
    d.add(text(tx + 74, 494, "Anhören", 14, DIM, 600, "middle"), text(tx + 186, 494, "Nehmen", 14, DIM, 600, "middle"))
d.add(rect(530, 548, 220, 70, 18, SURF), icon("x", 566, 568, 30, TEXT, 3), text(610, 593, "Schließen", 20, TEXT, 700))
docs.append(("07_kinderseite_verlauf", d))

# ============================================================ ELTERN
# 08 Parental Gate
d = Doc("08", "Eltern-Zugang (Parental Gate)", "Plan §3 Elternbereich, §16 (Gate ≠ Einwilligung)",
        ["Erreichbar über das kleine Schloss unten rechts auf der Kinderseite (2 s halten). Dann eine Rechenaufgabe mit großen Zifferntasten; falsch = einfach zurück, kein Alarm.",
         "Hinweis an Eltern: Das Gate schützt vor versehentlichem Öffnen, es ist keine datenschutzrechtliche Einwilligung."], PACC)
d.add(mode_bar(0), volume(), pads(["green", "yellow", "white", "white", "green", "white", "yellow", "white", "white", "green", "white", "white"]), kid_bottom(beat=1))
d.add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#000000" opacity="0.7"/>')
d.add(rect(330, 90, 620, 620, 28, "#1F1F24", PACC, 3))
d.add(icon("lock", 368, 124, 40, PACC, 2.6), text(424, 156, "Nur für Erwachsene", 28, TEXT, 800))
d.add(text(640, 222, "Wie viel ist 7 + 8 ?", 34, TEXT, 800, "middle"))
d.add(rect(500, 246, 280, 70, 16, SURF, PACC, 2), text(640, 294, "1 5", 34, TEXT, 800, "middle"))
keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
for i, k in enumerate(keys):
    r_, c_ = divmod(i, 3)
    kx, ky = 466 + c_ * 120, 336 + r_ * 78
    d.add(rect(kx, ky, 108, 66, 16, PACC if k == "OK" else SURF), text(kx + 54, ky + 43, k, 26, DARK if k == "OK" else TEXT, 800, "middle"))
d.add(text(640, 680, "Abbrechen – zurück zur Kinderseite", 16, DIM, 600, "middle"))
docs.append(("08_eltern_zugang_gate", d))

# 09 Lautstärke & Pegel
d = parent_doc("09", "Elternbereich – Lautstärke, Grenze, Pegel", "Plan §9.1–9.3, §7, §3.1, §1.2", 
               ["Lautstärke oben rechts wie auf der Kinderseite (gleiche Quelle). Grenze = dBFS-Ceiling + Peak-Limiter auf die Summe; Kindregler bleibt darunter.",
                "Eingang: Trim, Peak-Meter mit Zielzone, Soft-Clip, Auto-Gain (Standard AUS), gemerkte „zu laut“-Momente. Ehrlicher Hinweis: dB(FS) ≠ dB am Ohr."], 0)
d.add(card(CX0, 148, 456, 330, "Maximale Lautstärke (nur Eltern)", "Die App wird nie lauter als diese Grenze."))
d.add(hslider(CX0 + 30, 260, 396, 0.70, "−30 dBFS", "0 dBFS", "−6 dBFS"))
d.add(toggle(CX0 + 22, 314, True, "Peak-Limiter auf die Summe", "verhindert Kratzen, wenn viele Loops laufen"))
d.add(note(CX0 + 16, 374, 424, 92, ["Echte Lautstärke hängt vom Kopfhörer ab", "dBFS ist nicht dB am Ohr: Systemlautstärke", "und Kopfhörer zählen mit. WHO: 75 dBA, 40 h/Wo."], "warn"))
d.add(card(CX0 + 476, 148, 464, 330, "Aufnahmepegel (Mikrofon)", "Reserve statt „so laut wie möglich“"))
d.add(meter(CX0 + 500, 236, 416, 28, -9, -4))
d.add(text(CX0 + 500, 318, "Eingangs-Trim", 15, TEXT, 700))
d.add(hslider(CX0 + 500, 350, 416, 0.45, "−24 dB", "+12 dB", "−4 dB"))
d.add(toggle(CX0 + 498, 404, True, "Soft-Clip am Eingang", "weiche Spitzenbegrenzung – ersetzt keine Reserve"))
d.add(card(CX0, 494, 456, 282, "Automatik"))
d.add(toggle(CX0 + 22, 548, False, "Auto-Gain", "langsames Nachziehen, kein Pumpen", "STANDARD: AUS"))
d.add(text(CX0 + 22, 618, "Festes Trim ist vorhersehbarer (Reizempfindlichkeit).", 13, DIM))
d.add(text(CX0 + 22, 638, "Auto-Gain schützt NICHT vor Übersteuerung am Wandler.", 13, DIM))
d.add(toggle(CX0 + 22, 666, True, "Naht weich zeichnen (Crossfade)", "gegen Klicks am Loop-Ende · Standard an"))
d.add(toggle(CX0 + 22, 720, True, "Start-/Stopp-Pieps", "läuft durch dieselbe Grenze"))
d.add(card(CX0 + 476, 494, 464, 282, "Zu laut gewesen (nur lokal gemerkt)"))
for k, (t_, p_) in enumerate([("Heute 16:42", "Pad 6 · Spitze 0 dBFS · übersteuert"), ("Heute 16:40", "Pad 2 · Spitze −1 dBFS"), ("Gestern 18:05", "Pad 9 · Spitze 0 dBFS · übersteuert")]):
    yy = 548 + k * 56
    d.add(rect(CX0 + 498, yy, 420, 46, 10, SURF), icon("alert", CX0 + 512, yy + 11, 24, RED if "über" in p_ else ORANGE, 2.2),
          text(CX0 + 548, yy + 20, t_, 14, TEXT, 700), text(CX0 + 548, yy + 38, p_, 12.5, DIM))
d.add(text(CX0 + 498, 744, "Tipp: Trim etwas senken oder Mikro weiter weg.", 13, DIM))
docs.append(("09_eltern_lautstaerke_pegel", d))

# 10 Geräte & Audio
d = parent_doc("10", "Elternbereich – Geräte (Mikrofon / Kopfhörer) und Audio-System", "Plan §8, §11.1, §12.1–12.2, §3.1",
               ["Eingang und Ausgang getrennt wählbar, nach Audio-System gruppiert, gespeichert nach Gerätename. Wechsel live (Stream startet kurz neu, wird angesagt).",
                "Windows: WASAPI Shared = Standard; ASIO optional mit Warnung (exklusiv); DirectSound/MME nur Kompatibilität. Linux: ALSA (PipeWire/Pulse), macOS: CoreAudio."], 1)
d.add(card(CX0, 148, 456, 250, None))
d.add(icon("mic", CX0 + 22, 168, 30, PACC, 2.4), text(CX0 + 64, 192, "Mikrofon (Eingang)", 19, TEXT, 700))
d.add(select(CX0 + 22, 214, 412, "USB-Mikrofon „Kids Mic“", "WASAPI · 1 Kanal · 48 kHz", 56))
d.add(text(CX0 + 22, 300, "Aktueller Pegel", 13, DIM), meter(CX0 + 22, 310, 412, 18, -16, -10, scale=False))
d.add(text(CX0 + 22, 360, "Andere: Systemstandard · Laptop-Mikrofon (intern)", 13, DIM))
d.add(card(CX0 + 476, 148, 464, 250, None))
d.add(icon("headphones", CX0 + 498, 168, 30, PACC, 2.4), text(CX0 + 540, 192, "Lautsprecher / Kopfhörer (Ausgang)", 19, TEXT, 700))
d.add(select(CX0 + 498, 214, 420, "Kopfhörer (Klinke, kabelgebunden)", "WASAPI · Stereo · 48 kHz", 56))
d.add(button(CX0 + 498, 290, 200, 44, "Testton abspielen", "secondary", "play", 14))
d.add(text(CX0 + 498, 360, "Andere: Systemstandard · Lautsprecher (Realtek) · BT-Kopfhörer ⚠", 13, DIM))
d.add(card(CX0, 414, 456, 362, "Audio-System (Windows)", "Nur ändern, wenn nötig. Stream startet kurz neu."))
opts = [(True, "WASAPI (geteilt)", "Standard", "Nativ, mischt sich mit anderen Programmen"),
        (False, "ASIO", "optional", "Für Audio-Interfaces · oft exklusiv"),
        (False, "WASAPI (exklusiv)", None, "Gerät nur für die Loopstation"),
        (False, "DirectSound", "Kompatibilität", "Ältere Schicht, mehr Verzögerung"),
        (False, "MME", "letzter Ausweg", "Hohe Verzögerung")]
for k, (on, lab, tag, sub) in enumerate(opts):
    d.add(radio(CX0 + 26, 484 + k * 56, on, lab, sub, tag))
d.add(card(CX0 + 476, 414, 464, 172, "Verzögerung (Latenz)"))
d.add(radio(CX0 + 500, 466, True, "Automatisch", "aus den Geräten ermittelt: 23 ms", "empfohlen"))
d.add(radio(CX0 + 500, 520, False, "Von Hand"), rect(CX0 + 640, 514, 100, 36, 10, SURF, "#3A3A41", 1.5), text(CX0 + 690, 538, "– ms", 14, DIM, 600, "middle"))
d.add(text(CX0 + 500, 572, "Wird nach Geräte-/System-Wechsel neu berechnet.", 12, DIM))
d.add(note(CX0 + 476, 602, 464, 174, ["Für gutes Looping", "• Kabelgebundene Kinderkopfhörer mit eigener Begrenzung", "• Bluetooth ist meist zu langsam für Aufnahmen", "• Lautsprecher + Mikro = Echo/Rückkopplung", "• ASIO4ALL ist nur ein Wrapper, kein echter Treiber", "• Gerät fehlt? Systemstandard wird genutzt + Hinweis"], "warn"))
docs.append(("10_eltern_geraete_audio", d))

# 11 Takt & Loop
d = parent_doc("11", "Elternbereich – Takt, Tempo und Loop-Verhalten", "Plan §2.2 (Regeln 7–8), §2.3, §1.3, §3.1–3.2, §13",
               ["Zeigt BPM, Taktart und Quelle des Takts (Aufnahmelänge | Klatschen/Onset | Eltern-BPM | freies Pad). Eltern korrigieren hier – das Kind bekommt keinen Dialog.",
                "Eltern-BPM hat Vorrang. Plausibles Tempo 40–200 BPM (justierbar in settings.toml). Metronom: visuell beim Kind, Ton nur optional, leise."], 2)
d.add(card(CX0, 148, 940, 196, "Aktueller Takt der Sitzung"))
for k, (lab, val, sub) in enumerate([("Tempo", "96 BPM", "gemessen"), ("Taktart", "4/4", "Standard"), ("Takt-Länge", "2,50 s", "1 Takt = 4 Schläge"), ("Quelle", "Klatschen", "onset · Pad 1")]):
    bx = CX0 + 22 + k * 228
    d.add(rect(bx, 196, 212, 128, 14, SURF), text(bx + 18, 226, lab, 14, DIM, 600), text(bx + 18, 272, val, 32, TEXT, 800), text(bx + 18, 304, sub, 13, GRAY))
d.add(card(CX0, 360, 456, 416, "Takt korrigieren (Eltern-BPM)", "Vorrang vor gemessenem Takt (Regel 8)"))
d.add(text(CX0 + 22, 440, "Tempo", 15, TEXT, 700))
d.add(rect(CX0 + 22, 454, 64, 56, 12, SURF), text(CX0 + 54, 491, "−", 28, TEXT, 700, "middle"),
      rect(CX0 + 96, 454, 140, 56, 12, SURF, PACC, 2), text(CX0 + 166, 491, "96", 26, TEXT, 800, "middle"),
      rect(CX0 + 246, 454, 64, 56, 12, SURF), text(CX0 + 278, 491, "+", 28, TEXT, 700, "middle"),
      text(CX0 + 326, 489, "BPM (40–200)", 14, DIM))
d.add(text(CX0 + 22, 548, "Taktart", 15, TEXT, 700))
for k, ts in enumerate(["2/4", "3/4", "4/4", "6/8"]):
    d.add(rect(CX0 + 22 + k * 102, 562, 92, 48, 12, "#2F3550" if ts == "4/4" else SURF, PACC if ts == "4/4" else None, 2),
          text(CX0 + 68 + k * 102, 593, ts, 18, TEXT, 700, "middle"))
d.add(button(CX0 + 22, 640, 196, 48, "Übernehmen", "primary"), button(CX0 + 230, 640, 204, 48, "Gemessenen Takt", "secondary"))
d.add(text(CX0 + 22, 720, "Ohne Takt (freie Sitzung) wird nichts geraten:", 13, DIM))
d.add(text(CX0 + 22, 740, "lieber kein Raster als ein falsches.", 13, DIM))
d.add(card(CX0 + 476, 360, 464, 416, "Loop-Verhalten"))
tg = [(True, "Takt aus Klatschen erkennen", "Onset/Auto-Grid · aus = Aufnahmelänge wird Takt"),
      (True, "Loops am Takt einrasten", "loop_sync · Start/Stopp am Takt-Anfang"),
      (True, "Loop beginnt beim ersten Schlag", "Verschiebung, nicht Abschneiden"),
      (False, "Vorpause entfernen", "kürzt die Aufnahme (nur bewusst wählen)"),
      (True, "Freie Pads am Takt-Punkt starten", "behalten ihre eigene Länge"),
      (False, "Metronom-Ton (leise)", "Kinderseite zeigt nur den Puls")]
for k, (on, lab, sub) in enumerate(tg):
    d.add(toggle(CX0 + 498, 408 + k * 60, on, lab, sub))
docs.append(("11_eltern_takt_loop", d))

# 12 Verlauf & Undo/Redo
d = parent_doc("12", "Elternbereich – Verlauf mit Zurück / Wiederholen", "Plan §6.1–6.3, §10.3 (Undo-Stack bleibt), §0 (Alle löschen)",
               ["Liste der letzten Änderungen (neueste oben), global zurück/wiederholen oder gezielt ein Pad. Grenze 1000 Schritte. Wiederholen-Liste leert sich bei neuer Änderung.",
                "„Alle löschen“ wandert von der Kinderseite hierher, mit Bestätigung – und bleibt per Zurück umkehrbar."], 3)
d.add(button(CX0, 148, 226, 64, "Zurück", "secondary", "undo", 19), button(CX0 + 238, 148, 226, 64, "Wiederholen", "secondary", "redo", 19))
d.add(rect(CX0 + 478, 148, 462, 64, 14, SURF2, "#2C2C31", 1.5), text(CX0 + 500, 176, "Zurück möglich: 14 Schritte", 15, TEXT, 700),
      text(CX0 + 500, 198, "Wiederholen möglich: 2 Schritte · Strg+Z / Strg+Y", 13, DIM))
d.add(card(CX0, 228, 940, 456, "Änderungen dieser Sitzung"))
rows = [("redo", "Wiederherstellbar", "Pad 4 · Aufnahme gelöscht", "16:47", "wieder"),
        ("redo", "Wiederherstellbar", "Pad 4 · Loop gestoppt", "16:46", "wieder"),
        (None, "Jetzt", "Pad 6 · neue Aufnahme (2,5 s) – ersetzt Take 2", "16:45", "cur"),
        (None, "", "Takt gesetzt: 96 BPM · 4/4 · Quelle Klatschen (Pad 1)", "16:41", "u"),
        (None, "", "Pad 2 · Loop gestartet", "16:40", "u"),
        (None, "", "Pad 10 · Aufnahme (5,0 s = 2 Takte)", "16:38", "u"),
        (None, "", "Pad 7 · freier Modus an", "16:36", "u")]
for k, (ic, tag, lab, tm, kind) in enumerate(rows):
    yy = 276 + k * 56
    bg = "#2F3550" if kind == "cur" else (SURF if kind == "u" else "#1A1A1E")
    d.add(rect(CX0 + 22, yy, 896, 48, 10, bg, PACC if kind == "cur" else None, 2))
    col = "#8E8E93" if kind == "wieder" else TEXT
    d.add(text(CX0 + 44, yy + 30, tm, 14, DIM, 600), text(CX0 + 112, yy + 30, lab, 15.5, col, 700 if kind == "cur" else 500))
    if kind == "wieder":
        d.add(rect(CX0 + 690, yy + 10, 130, 28, 14, "#3A3A41"), text(CX0 + 755, yy + 29, "wiederholbar", 12, GRAY, 700, "middle"))
    if kind in ("u", "cur"):
        d.add(rect(CX0 + 768, yy + 8, 136, 32, 10, SURF3), icon("undo", CX0 + 782, yy + 14, 20, TEXT, 2.2), text(CX0 + 810, yy + 30, "nur dieses Pad", 12.5, TEXT, 600))
d.add(text(CX0 + 22, 676, "Ältere Takes eines Pads: Verlauf-Modus auf der Kinderseite (Mockup 07).", 13, DIM))
d.add(button(CX0, 700, 300, 60, "Alle Pads löschen …", "danger", "trash", 16))
d.add(text(CX0 + 320, 726, "Fragt nach. Danach mit „Zurück“ umkehrbar.", 13.5, DIM))
d.add(text(CX0 + 320, 746, "Tipp: vorher als Set sichern (Mockup 14).", 13.5, DIM))
docs.append(("12_eltern_verlauf_undo_redo", d))

# 13 Erweitert: Wellenform, Marker, Einzel-Export
d = parent_doc("13", "Elternbereich – Erweitert: Wellenform, Marker, einzelner Loop", "Plan §3.2, §4, §1.1, §13",
               ["Einzelnen Loop ansehen (Wellenform mit Taktlinien), Marker setzen für beat-genaues Strecken. Export eines einzelnen Loops: WAV Standard, MP3 nur mit ffmpeg.",
                "Bewusst keine Zeitachse, keine Spuren, keine Automation – das bleibt die Session-Ansicht mit Pads (Mini-DAW-Gefahr §3.3)."], 4)
d.add(text(CX0, 172, "Pad wählen", 14, DIM, 600))
for k in range(12):
    cc = ["green", "yellow", "white", "yellow", "green", "yellow", "green", "white", "white", "green", "white", "white"][k]
    bx = CX0 + 96 + k * 70
    d.add(rect(bx, 148, 60, 40, 10, PAD[cc], "#FFFFFF" if k == 5 else None, 3), text(bx + 30, 175, str(k+1), 16, DARK, 800, "middle"))
d.add(card(CX0, 204, 940, 330, "Pad 6 · Aufnahme 2,50 s · 1 Takt · im Raster"))
wx0, wy0, ww, wh = CX0 + 22, 264, 896, 150
d.add(rect(wx0, wy0, ww, wh, 10, "#141418"))
for b in range(5):
    xx = wx0 + ww * b / 4
    d.add(f'<line x1="{xx:.1f}" y1="{wy0}" x2="{xx:.1f}" y2="{wy0+wh}" stroke="#3A3A41" stroke-width="{2 if b in (0,4) else 1}" stroke-dasharray="{"" if b in (0,4) else "4 4"}"/>')
    if b < 4:
        d.add(text(xx + 6, wy0 + 16, f"Schlag {b+1}", 11, DIM))
d.add(waveform(wx0, wy0 + 10, ww, wh - 20, 6))
for mx, ml in ((0.02, "A"), (0.51, "B")):
    xx = wx0 + ww * mx
    d.add(f'<line x1="{xx:.1f}" y1="{wy0-6}" x2="{xx:.1f}" y2="{wy0+wh}" stroke="{ORANGE}" stroke-width="3"/>',
          f'<path d="M{xx-9:.1f} {wy0-18} h18 v10 l-9 8 l-9 -8 Z" fill="{ORANGE}"/>', text(xx + 12, wy0 - 6, f"Marker {ml}", 12, ORANGE, 700))
d.add(button(CX0 + 22, 428, 170, 48, "Marker setzen", "secondary"), button(CX0 + 202, 428, 170, 48, "Marker löschen", "secondary"),
      button(CX0 + 382, 428, 150, 48, "Anhören", "secondary", "play", 15))
d.add(button(CX0 + 640, 428, 278, 48, "Zwischen Markern strecken", "secondary"))
d.add(toggle(CX0 + 22, 486, False, "Marker auf Transiente einrasten", "rastet auf den nächsten Schlag in der Nähe ein; ohne Schlag bleibt der Marker, wo er ist"))
d.add(card(CX0, 550, 940, 226, "Diesen Loop exportieren", "Lokal auf diesem Rechner · kein Upload, kein Teilen"))
d.add(text(CX0 + 22, 640, "Format", 15, TEXT, 700))
d.add(radio(CX0 + 22, 656, True, "WAV", "unverändert, Standard"), radio(CX0 + 200, 656, False, "MP3", "braucht ffmpeg – nicht gefunden", dis=True))
d.add(toggle(CX0 + 470, 600, True, "Marker als Cue-Punkte mitschreiben", "wenn das Format es zuverlässig kann (sonst Begleitdatei)"))
d.add(text(CX0 + 22, 740, "Ziel: Dokumente/Loopstation/Export/pad06_2026-11-20_1645.wav", 13.5, DIM))
d.add(button(CX0 + 700, 704, 218, 54, "Als WAV sichern", "primary", "download", 16))
docs.append(("13_eltern_erweitert_wellenform_export", d))

# 14 Set speichern
d = parent_doc("14", "Elternbereich – Set speichern", "Plan §10.1–10.2",
               ["Speichert die komplette Sitzung als Kopie (Ereignisprotokoll, alle Aufnahmen als WAV, Einstellungen) – als .loopset-Datei (ZIP) oder Ordner. Kind spielt danach einfach weiter.",
                "Atomisch: erst temporär schreiben, dann umbenennen – ein Abbruch zerstört kein altes Set. Läuft eine Aufnahme, wird zuerst gewartet."], 5)
d.add(button(CX0, 148, 300, 60, "Set speichern", "primary", "save", 18), button(CX0 + 316, 148, 300, 60, "Set öffnen …", "secondary", "folder", 18))
d.add(card(CX0, 228, 580, 548, "Aktuelle Sitzung als Set sichern"))
d.add(text(CX0 + 22, 300, "Name", 15, TEXT, 700), rect(CX0 + 22, 314, 536, 52, 12, SURF, PACC, 2), text(CX0 + 40, 347, "Mias Trommel-Lied", 18, TEXT, 600),
      f'<line x1="{CX0+202}" y1="326" x2="{CX0+202}" y2="354" stroke="{PACC}" stroke-width="2"/>')
d.add(text(CX0 + 22, 402, "Speichern als", 15, TEXT, 700))
d.add(radio(CX0 + 22, 418, True, "Eine Datei (.loopset)", "gepackt, gut zum Aufheben", "empfohlen"), radio(CX0 + 22, 474, False, "Ordner", "gleiche Struktur, ungepackt"))
d.add(text(CX0 + 22, 556, "Ort", 15, TEXT, 700), select(CX0 + 22, 570, 536, "Dokumente/Loopstation/Sets"))
d.add(text(CX0 + 22, 652, "Datei: Mias Trommel-Lied 2026-11-20.loopset", 13.5, DIM))
d.add(button(CX0 + 22, 690, 250, 60, "Speichern", "primary", "save", 18), button(CX0 + 286, 690, 272, 60, "Abbrechen", "secondary"))
d.add(card(CX0 + 600, 228, 340, 340, "Was im Set steckt"))
for k, (lab, val) in enumerate([("Pads mit Aufnahme", "7 von 12"), ("Aufnahmen inkl. Verlauf", "19 WAV"), ("Takt", "96 BPM · 4/4"), ("Zurück-Schritte", "14 (bleiben erhalten)"), ("Einstellungen", "Kopie settings.toml"), ("Größe ca.", "11,4 MB")]):
    yy = 290 + k * 44
    d.add(text(CX0 + 622, yy, lab, 14, DIM), text(CX0 + 918, yy, val, 14, TEXT, 700, "end"))
d.add(note(CX0 + 600, 584, 340, 192, ["Sicher gespeichert", "Erst fertig schreiben, dann", "umbenennen: ein Abbruch über-", "schreibt kein altes Set halb.", "Nur lokal – keine Cloud."], "ok"))
docs.append(("14_eltern_set_speichern", d))

# 15 Set öffnen
d = parent_doc("15", "Elternbereich – Set öffnen", "Plan §10.3, §10.1 (Format-Version)",
               ["Liste gespeicherter Sets mit Datum und Inhalt. Vor dem Öffnen Rückfrage, wenn die aktuelle Sitzung ungesichert ist. Zurück-Schritte des Sets bleiben erhalten, Wiederholen startet leer.",
                "Versionsprüfung: zu neue Sets werden mit klarer Meldung abgelehnt. Fehlt ein Gerät aus dem Set, wird der Systemstandard genutzt und hier angezeigt."], 5)
d.add(button(CX0, 148, 300, 60, "Set speichern", "secondary", "save", 18), button(CX0 + 316, 148, 300, 60, "Set öffnen …", "primary", "folder", 18))
d.add(card(CX0, 228, 540, 548, "Gespeicherte Sets", "Dokumente/Loopstation/Sets"))
sets = [("Mias Trommel-Lied", "20.11.2026 · 16:48 · 7 Pads · 96 BPM", "ok", True),
        ("Regen-Geräusche", "18.11.2026 · 17:20 · 4 Pads · frei", "ok", False),
        ("Geburtstags-Beat", "02.11.2026 · 11:05 · 9 Pads · 120 BPM", "ok", False),
        ("Opas Set (anderer PC)", "Gerät „Focusrite“ fehlt → Systemstandard", "warn", False),
        ("Neues Set von Laptop", "Format v3 – neuere Loopstation nötig", "bad", False)]
for k, (nm, sub, st, sel) in enumerate(sets):
    yy = 300 + k * 88
    d.add(rect(CX0 + 22, yy, 496, 76, 14, "#2F3550" if sel else SURF, PACC if sel else None, 2))
    d.add(icon("folder", CX0 + 40, yy + 24, 28, PACC if st == "ok" else (ORANGE if st == "warn" else RED), 2.2))
    d.add(text(CX0 + 84, yy + 32, nm, 17, TEXT if st != "bad" else "#8E8E93", 700), text(CX0 + 84, yy + 56, sub, 13, DIM if st == "ok" else (ORANGE if st == "warn" else "#FF8A80")))
d.add(card(CX0 + 560, 228, 380, 300, "Mias Trommel-Lied"))
for k, (lab, val) in enumerate([("Gespeichert", "20.11.2026, 16:48"), ("Pads mit Aufnahme", "7"), ("Takt", "96 BPM · 4/4"), ("Zurück-Schritte", "14 (bleiben)"), ("Wiederholen", "startet leer"), ("Format", "v1 · passt")]):
    yy = 290 + k * 36
    d.add(text(CX0 + 582, yy, lab, 14, DIM), text(CX0 + 918, yy, val, 14, TEXT, 700, "end"))
d.add(rect(CX0 + 560, 544, 380, 232, 18, "#2A2414", ORANGE, 2))
d.add(icon("alert", CX0 + 580, 566, 28, ORANGE, 2.4), text(CX0 + 620, 588, "Aktuelle Sitzung ist nicht gesichert", 16, TEXT, 700))
d.add(text(CX0 + 582, 622, "Öffnen ersetzt, was gerade auf den Pads ist.", 13.5, "#E5E5EA"))
d.add(text(CX0 + 582, 642, "Jetzt zuerst als Set sichern?", 13.5, "#E5E5EA"))
d.add(button(CX0 + 582, 664, 336, 46, "Erst sichern, dann öffnen", "primary", None, 15))
d.add(button(CX0 + 582, 718, 160, 44, "Ohne sichern", "secondary", None, 14), button(CX0 + 758, 718, 160, 44, "Abbrechen", "secondary", None, 14))
docs.append(("15_eltern_set_oeffnen", d))

# 16 Export der Summe
d = parent_doc("16", "Elternbereich – Export der Summe (N Takte als WAV)", "Plan §5.1–5.3, §4, §13",
               ["Alles, was gerade zusammen klingt, N Takte lang als eine Datei. Keine Zeitachse: Loops wiederholen sich wie live; Länge = N × Takt (ganze Frames).",
                "Gleiche Lautstärke-Kette wie live inkl. Eltern-Grenze auf die Summe. Optional kurzer Ausklang. Ohne Takt: Eltern-BPM setzen oder Notbehelf ausdrücklich wählen."], 6)
d.add(card(CX0, 148, 580, 628, "Summe exportieren", "Session · 96 BPM · 4/4 · Quelle Klatschen"))
d.add(text(CX0 + 22, 240, "Wie viele Takte?", 15, TEXT, 700))
for k, n in enumerate(["4", "8", "16", "32"]):
    on = n == "8"
    d.add(rect(CX0 + 22 + k * 112, 256, 100, 64, 14, "#2F3550" if on else SURF, PACC if on else None, 2),
          text(CX0 + 72 + k * 112, 296, n, 24, TEXT, 800, "middle"))
d.add(rect(CX0 + 470, 256, 88, 64, 14, SURF), text(CX0 + 514, 294, "…", 22, DIM, 700, "middle"))
d.add(rect(CX0 + 22, 336, 536, 64, 14, "#141418"), text(CX0 + 40, 362, "Länge", 13, DIM), text(CX0 + 40, 388, "8 Takte × 2,50 s = 20,0 s", 18, TEXT, 800),
      text(CX0 + 540, 388, "960 000 Frames · 48 kHz", 13, DIM, 500, "end"))
d.add(text(CX0 + 22, 440, "Welche Pads?", 15, TEXT, 700))
d.add(radio(CX0 + 22, 454, True, "Nur was gerade loopt", "5 Pads"), radio(CX0 + 300, 454, False, "Alle belegten Pads als Loop", "7 Pads"))
d.add(toggle(CX0 + 22, 516, False, "Einmal-Pads am Anfang einrechnen", "Standard: weglassen"))
d.add(toggle(CX0 + 22, 572, True, "Kurzer Ausklang am Ende", "15 ms Fade gegen Knacken"))
d.add(text(CX0 + 22, 648, "Format", 15, TEXT, 700))
d.add(radio(CX0 + 22, 662, True, "WAV", "mono, 48 kHz", "Standard"), radio(CX0 + 300, 662, False, "MP3", "braucht ffmpeg – nicht gefunden", dis=True))
d.add(button(CX0 + 22, 708, 536, 56, "Summe als WAV exportieren", "primary", "download", 17))
d.add(card(CX0 + 600, 148, 340, 360, "Vorschau: was wiederholt wird"))
lanes = [("Pad 1", 1, GREEN, False), ("Pad 2", 1, GREEN, False), ("Pad 5", 2, GREEN, False), ("Pad 10", 0.5, GREEN, False), ("Pad 7", 1.37, SKY, True)]
lx0, lw = CX0 + 676, 248
for k, (nm, ln, col, free) in enumerate(lanes):
    yy = 202 + k * 52
    d.add(text(CX0 + 620, yy + 24, nm, 12.5, TEXT, 700))
    seg = lw / 8 * ln
    xx = lx0
    while xx < lx0 + lw - 0.5:
        sw_ = min(seg, lx0 + lw - xx)
        d.add(rect(xx + 1, yy + 6, max(2, sw_ - 2), 28, 6 if not free else 14, col, None, 0, 'opacity="0.85"'))
        xx += seg
for b in range(9):
    xx = lx0 + lw * b / 8
    d.add(f'<line x1="{xx:.1f}" y1="196" x2="{xx:.1f}" y2="462" stroke="#FFFFFF" stroke-opacity="{0.35 if b%4==0 else 0.12}" stroke-width="1"/>')
d.add(text(lx0, 484, "Takt 1", 11, DIM), text(lx0 + lw, 484, "8", 11, DIM, 400, "end"))
d.add(text(CX0 + 620, 500, "Blau = freies Pad: eigene Länge, am Ende geschnitten", 11.5, SKY))
d.add(note(CX0 + 600, 524, 340, 252, ["Eltern-Grenze gilt auch hier", "Lautstärke + Limiter wie live", "auf die Summe (−6 dBFS).", "", "Kein Takt in der Sitzung?", "→ BPM unter „Takt & Loop“ setzen", "oder Notbehelf „N × längstes", "Sample“ ausdrücklich wählen."], "info"))
docs.append(("16_eltern_export_summe", d))

import re, textwrap
try:
    import cairosvg
except ImportError:
    cairosvg = None
def fix_alpha(svg):
    def rep(m):
        attr, hx, a = m.group(1), m.group(2), m.group(3)
        return f'{attr}="#{hx}" {attr}-opacity="{int(a,16)/255:.2f}"'
    return re.sub(r'(fill|stroke)="#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})"', rep, svg)
os.makedirs(OUT, exist_ok=True)
for name, doc in docs:
    svg = fix_alpha(doc.svg())
    with open(f"{OUT}/{name}.svg", "w") as f:
        f.write(svg)
    if cairosvg is None:
        continue
    cairosvg.svg2png(bytestring=svg.encode(), write_to=f"{OUT}/{name}.png", output_width=W, output_height=H+CAP)
print("\n".join(n for n, _ in docs))
