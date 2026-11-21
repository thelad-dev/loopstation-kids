# Basis-Bausteine, unveraendert aus loopstation-kids mockups/gen_mockups.py (Commit cb7f63b, Zeilen 1-370).
import re
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

