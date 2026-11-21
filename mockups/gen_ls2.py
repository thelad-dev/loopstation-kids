# Generator der Loopstation-2-Konzept-Mockups (Scout 2026-11-21).
# Baut auf den Bausteinen der vorhandenen Mockups auf (ls2_base.py = gen_mockups.py bis zur ersten Ansicht).
# Aufruf: python gen_ls2.py  -> schreibt *.svg neben dieses Skript. PNG-Vorschau optional mit --png (PySide6).
import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ls2_base import *  # noqa: F401,F403  (Farben, icon, text, rect, pad, volume, big_button, toggle, ...)

OUT = os.path.dirname(os.path.abspath(__file__))

# Zusaetzliche Symbole fuer die neue Elternansicht (24er-Raster, eigene Pfade).
ICONS.update({
    "grid": ("s", ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"]),
    "gear": ("s", ["M12 15a3 3 0 1 0 0.01 0", "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"]),
    "chevup": ("s", ["M18 15l-6-6-6 6"]),
    "scissors": ("s", ["M6 9a3 3 0 1 0 0.01 0", "M6 15a3 3 0 1 0 0.01 0", "M20 4L8.12 15.88", "M14.47 14.48L20 20", "M8.12 8.12L12 12"]),
    "flag": ("s", ["M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z", "M4 22v-7"]),
    "stretch": ("s", ["M3 12h18", "M7 8l-4 4 4 4", "M17 8l4 4-4 4"]),
    "fx": ("s", ["M12 2v4", "M12 18v4", "M4.93 4.93l2.83 2.83", "M16.24 16.24l2.83 2.83", "M2 12h4", "M18 12h4", "M12 9a3 3 0 1 0 0.01 0"]),
    "keyboard": ("s", ["M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z", "M6 10h.01", "M10 10h.01", "M14 10h.01", "M18 10h.01", "M7 14h10"]),
    "cpu": ("s", ["M6 6h12v12H6z", "M9 9h6v6H9z", "M9 1v3", "M15 1v3", "M9 20v3", "M15 20v3", "M20 9h3", "M20 14h3", "M1 9h3", "M1 14h3"]),
    "kid": ("s", ["M12 7a3 3 0 1 0 0.01 0", "M5 21v-2a7 7 0 0 1 14 0v2"]),
})

def fix_alpha(svg):  # wie in gen_mockups.py: #RRGGBBAA -> fill/stroke-opacity (fuer Renderer ohne 8-stellige Farben)
    import re as _re
    def rep(m):
        attr, hx, a = m.group(1), m.group(2), m.group(3)
        return f'{attr}="#{hx}" {attr}-opacity="{int(a,16)/255:.2f}"'
    return _re.sub(r'(fill|stroke)="#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})"', rep, svg)

PACC = "#7FA7FF"      # Eltern-Akzent wie heute (parent_gate.PARENT_ACCENT)
SEL = "#7FA7FF"
MUTED = "#6E6E75"
LINE = "#2C2C31"

CAP2 = 170  # hoeherer Beschriftungsstreifen als in gen_mockups.py (mehr Anmerkungen je Ansicht)

class Doc2(Doc):
    """Wie Doc, aber Streifen mit Titel, Bezug in eigener Zeile und bis zu 6 Zeilen Anmerkungen."""
    def __init__(self, num, title, plan, notes, accent=PACC):
        super().__init__(num, title, plan, notes, accent)
    def svg(self):
        import textwrap
        full = super().svg()
        head = full[:full.index('\n<rect x="0" y="%d"' % H)]
        head = head.replace(f'height="{H+CAP}" viewBox="0 0 {W} {H+CAP}"', f'height="{H+CAP2}" viewBox="0 0 {W} {H+CAP2}"')
        cap = (f'\n<rect x="0" y="{H}" width="{W}" height="{CAP2}" fill="#F4F4F6"/>'
               f'<rect x="0" y="{H}" width="{W}" height="4" fill="{self.accent}"/>'
               + text(24, H+32, f"Loopstation 2 · {self.num} · {self.title}", 19, DARK, 700)
               + text(24, H+52, self.plan, 13, "#55555C", 600))
        lines = []
        for n in self.notes:
            lines += textwrap.wrap(n, 196)
        for i, line in enumerate(lines[:6]):
            cap += text(24, H+76+i*17.5, line, 12.8, "#3A3A41")
        return head + cap + "\n</svg>\n"

# ------------------------------------------------------------------ Bausteine Elternansicht
RAIL = [("grid", "Pads"), ("history", "Verlauf"), ("save", "Sets"), ("download", "Export"),
        None, ("sliders", "Pegel"), ("headphones", "Geräte"), ("gear", "System")]

def rail(active="Pads", x=20, y=20, h=760):
    out = [rect(x, y, 76, h, 18, SURF2, LINE, 1.5)]
    yy = y + 14
    for item in RAIL:
        if item is None:
            out.append(f'<line x1="{x+16}" y1="{yy+4}" x2="{x+60}" y2="{yy+4}" stroke="#3A3A41" stroke-width="1.5"/>')
            yy += 14
            continue
        ic, label = item
        act = label == active
        if act:
            out.append(rect(x + 6, yy, 64, 66, 14, "#2F3550", PACC, 1.5))
        out.append(icon(ic, x + 26, yy + 10, 24, PACC if act else DIM, 2.2))
        out.append(text(x + 38, yy + 54, label, 12, TEXT if act else "#C7C7CC", 700 if act else 500, "middle"))
        yy += 74
    # Tastatur-Hilfe unten
    out.append(icon("keyboard", x + 26, y + h - 64, 24, MUTED, 2))
    out.append(text(x + 38, y + h - 24, "Tasten ?", 11, MUTED, 600, "middle"))
    return "\n".join(out)

def mode_switch(x, y, w=220, h=56, parent=True):
    out = [rect(x, y, w, h, 16, SURF, "#3A3A41", 1.5)]
    half = w / 2
    if parent:
        out.append(rect(x + half, y + 4, half - 4, h - 8, 12, PACC))
    else:
        out.append(rect(x + 4, y + 4, half - 4, h - 8, 12, GREEN))
    out.append(icon("kid", x + 18, y + h/2 - 11, 22, DARK if not parent else "#C7C7CC", 2.2))
    out.append(text(x + 46, y + h/2 + 6, "Kinder", 16, DARK if not parent else "#C7C7CC", 700))
    out.append(icon("unlock" if parent else "lock", x + half + 14, y + h/2 - 11, 22, DARK if parent else "#C7C7CC", 2.2))
    out.append(text(x + half + 42, y + h/2 + 6, "Eltern", 16, DARK if parent else "#C7C7CC", 700))
    return "\n".join(out)

def tempo_chip(x, y, w=290, h=56, bpm="96 BPM", sig="4/4", src="aus Klatschen · 2,50 s", beat=1):
    out = [rect(x, y, w, h, 16, SURF, "#3A3A41", 1.5)]
    for k in range(4):
        cx = x + 22 + k * 16
        on = k == beat
        out.append(f'<circle cx="{cx}" cy="{y + h/2}" r="{6 if on else 5}" fill="{SKY if on else "#3A3A41"}"/>')
    out.append(text(x + 96, y + 25, f"{bpm} · {sig}", 17, TEXT, 800))
    out.append(text(x + 96, y + 44, src, 12.5, DIM, 500))
    out.append(icon("chev", x + w - 34, y + h/2 - 10, 20, DIM, 2.2))
    return "\n".join(out)

def icon_button(x, y, ic, label=None, w=52, h=56, state="normal", color=TEXT):
    fill = SURF if state != "disabled" else "#1A1A1E"
    fg = color if state != "disabled" else "#55555C"
    out = [rect(x, y, w, h, 14, fill, "#3A3A41" if state != "disabled" else LINE, 1.5)]
    if label:
        out.append(icon(ic, x + w/2 - 11, y + 8, 22, fg, 2.3))
        out.append(text(x + w/2, y + h - 9, label, 11, fg, 600, "middle"))
    else:
        out.append(icon(ic, x + w/2 - 12, y + h/2 - 12, 24, fg, 2.3))
    return "\n".join(out)

def top_bar(x0=108, redo=False, vol_x=880, beat=1):
    out = [mode_switch(x0, 28), tempo_chip(x0 + 232, 28, beat=beat)]
    bx = x0 + 536
    out.append(icon_button(bx, 28, "undo", "Zurück", 64))
    out.append(icon_button(bx + 72, 28, "redo", "Wieder", 64, state="normal" if redo else "disabled"))
    out.append(icon_button(bx + 144, 28, "stop", "Still", 64, color=TEXT))
    out.append(volume(vol_x, 24, 1256 - vol_x, 64, 0.55, 0.75, kid=True).replace('r="27"', 'r="22"'))
    return "\n".join(out)

def mini_wave(x, y, w, h, seed, color="#00000055", density=36):
    rnd = random.Random(seed)
    out = []
    step = w / density
    for i in range(density):
        t = i / density
        env = 0.25 + 0.75 * math.exp(-((t * 4) % 1) * 3.0)
        a = env * (0.5 + 0.5 * rnd.random()) * h / 2
        cx = x + i * step + step / 2
        out.append(f'<line x1="{cx:.1f}" y1="{y+h/2-a:.1f}" x2="{cx:.1f}" y2="{y+h/2+a:.1f}" stroke="{color}" stroke-width="{max(1.2, step*0.55):.1f}" stroke-linecap="round"/>')
    return "\n".join(out)

def slot(x, y, w, h, idx, color="white", name=None, bars=None, selected=False, free=False, state_icon=None, seed=1, waiting=None):
    """Pad der Elternansicht: gleiche Zustandsfarbe wie Kinderseite und Launchpad, dazu Name, Laenge, Mini-Welle."""
    out = []
    fill = PAD[color]
    lit = color in ("green", "red")
    r = 14 if not free else h / 2
    if lit:
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" opacity="0.30" filter="url(#soft)"/>')
    if selected:
        out.append(rect(x - 7, y - 7, w + 14, h + 14, r + 6, "none", SEL, 4))
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="#000000" stroke-opacity="0.18" stroke-width="2"/>')
    big = h >= 120
    fs = 15 if big else 13
    if free:
        out.append(text(x + w/2, y + h*0.30, f"{idx} · {name}" if big else str(idx), fs, "#000000B0", 700, "middle"))
    else:
        out.append(text(x + 14, y + (26 if big else 22), str(idx), fs, "#00000080", 800))
        if name:
            out.append(text(x + 40, y + (26 if big else 22), name, fs, "#000000B0", 700))
    if color != "white" and not free:
        wy = y + h * (0.42 if big else 0.40)
        out.append(mini_wave(x + 14, wy, w - 28, h * (0.30 if big else 0.28), seed, "#00000050", 40 if big else 30))
    if free:
        out.append(icon("wave", x + w/2 - 16, y + h/2 - 12, 32, "#00000070", 2.6))
    if bars and free:
        out.append(text(x + w/2, y + h*0.80, bars, 12.5 if big else 11.5, "#00000090", 700, "middle"))
    elif bars:
        out.append(text(x + w - 14, y + h - (14 if big else 11), bars, 12.5 if big else 11.5, "#00000090", 700, "end"))
    if state_icon:
        sz = 22 if big else 18
        out.append(rect(x + 10, y + h - sz - (14 if big else 9), sz + 10, sz + 6, 8, "#0000001F"))
        out.append(icon(state_icon, x + 15, y + h - sz - (11 if big else 6), sz, "#000000A0", 2.4))
    if waiting is not None:
        out.append(rect(x + 2, y + h - 8, (w - 4), 6, 3, "#00000020"))
        out.append(rect(x + 2, y + h - 8, (w - 4) * waiting, 6, 3, SKY))
    return "\n".join(out)

DEMO = [  # (Farbe, Name, Laenge, Zustandssymbol, frei)
    ("green", "Klatschen", "1 Takt", "loop", False), ("yellow", "Lied A", "2 Takte", "play", False),
    ("white", None, None, "record", False), ("white", None, None, "record", False),
    ("green", "Trommel", "2 Takte", "loop", False), ("yellow", "Summen", "frei 3,1 s", None, True),
    ("yellow", "Pfeifen", "1 Takt", "play", False), ("white", None, None, "record", False),
    ("white", None, None, "record", False), ("green", "Rassel", "1 Takt", "loop", False),
    ("white", None, None, "record", False), ("white", None, None, "record", False),
]

def slot_grid(x0, y0, w, h, cols=4, rows=3, gap=14, selected=4, demo=DEMO, waiting=None):
    sw = (w - (cols - 1) * gap) / cols
    sh = (h - (rows - 1) * gap) / rows
    out = []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        color, name, bars, st, free = demo[i]
        x = x0 + c * (sw + gap)
        y = y0 + r * (sh + gap)
        if free:
            d = min(sw, sh)
            out.append(slot(x + (sw - d) / 2 if sw > sh else x, y, d if sw > sh else sw, sh, i + 1, color, name, bars,
                            i == selected, True, None, i))
        else:
            out.append(slot(x, y, sw, sh, i + 1, color, name, bars, i == selected, False, st, i + 3,
                            waiting if (waiting is not None and i == 6) else None))
    return "\n".join(out), sw, sh

def detail_tabs(x, y, tabs, active):
    out = []
    xx = x
    for t in tabs:
        tw = tw_est(t, 15) + 30
        act = t == active
        dis = "später" in t
        out.append(rect(xx, y, tw, 38, 12, "#2F3550" if act else "none", PACC if act else None, 1.5))
        out.append(text(xx + tw/2, y + 25, t, 15, PACC if act else ("#55555C" if dis else "#C7C7CC"), 700 if act else 600, "middle"))
        xx += tw + 8
    return "\n".join(out), xx

def beat_wave(x, y, w, h, bars=2, beats=4, seed=5, trim=None, markers=(), play=None):
    """Wellenform mit Schlag-Linien, optional Kuerz-Griffen (Anteil 0..1) und Markern [(pos, Buchstabe)]."""
    out = [rect(x, y, w, h, 10, "#141417", LINE, 1)]
    n = bars * beats
    for k in range(n + 1):
        lx = x + w * k / n
        strong = k % beats == 0
        out.append(f'<line x1="{lx:.1f}" y1="{y}" x2="{lx:.1f}" y2="{y+h}" stroke="{"#4A4A52" if strong else "#2E2E34"}" stroke-width="{2 if strong else 1}"/>')
        if k < n:
            lab = f"{k // beats + 1}.{k % beats + 1}"
            out.append(text(lx + 6, y + 16, lab, 11, "#8E8E93" if strong else "#5A5A60", 700 if strong else 500))
    out.append(waveform(x + 4, y + 24, w - 8, h - 34, seed, SKY, 190))
    if trim:
        a, b = trim
        ax, bx = x + w * a, x + w * b
        if a > 0:
            out.append(f'<rect x="{x}" y="{y}" width="{ax-x:.1f}" height="{h}" fill="#0E0E10" opacity="0.72"/>')
        if b < 1:
            out.append(f'<rect x="{bx:.1f}" y="{y}" width="{x+w-bx:.1f}" height="{h}" fill="#0E0E10" opacity="0.72"/>')
        for gx, lab in ((ax, "Anfang"), (bx, "Ende")):
            out.append(f'<line x1="{gx:.1f}" y1="{y-6}" x2="{gx:.1f}" y2="{y+h+6}" stroke="{PACC}" stroke-width="3"/>')
            out.append(rect(gx - 9, y + h/2 - 22, 18, 44, 6, PACC))
            out.append(f'<line x1="{gx-3:.1f}" y1="{y+h/2-10}" x2="{gx-3:.1f}" y2="{y+h/2+10}" stroke="#111114" stroke-width="1.5"/>')
            out.append(f'<line x1="{gx+3:.1f}" y1="{y+h/2-10}" x2="{gx+3:.1f}" y2="{y+h/2+10}" stroke="#111114" stroke-width="1.5"/>')
            out.append(text(gx, y + h + 22, lab, 12, PACC, 700, "middle"))
    for pos, letter in markers:
        mx = x + w * pos
        out.append(f'<line x1="{mx:.1f}" y1="{y}" x2="{mx:.1f}" y2="{y+h}" stroke="{ORANGE}" stroke-width="2.5"/>')
        out.append(f'<path d="M{mx:.1f} {y} h18 l-5 9 l5 9 h-18 z" fill="{ORANGE}"/>')
        out.append(text(mx + 6, y + 14, letter, 11, DARK, 800))
    if play is not None:
        px = x + w * play
        out.append(f'<line x1="{px:.1f}" y1="{y}" x2="{px:.1f}" y2="{y+h}" stroke="#FFFFFF" stroke-width="2"/>')
    return "\n".join(out)

def small_btn(x, y, label, ic=None, kind="secondary", h=42, size=14.5):
    w = tw_est(label, size) + (44 if ic else 28)
    return button(x, y, w, h, label, kind, ic, size), x + w

def annot(x, y, n):
    """Nummerierte Anmerkung (blauer Kreis) - verweist auf die Liste im Beschriftungsstreifen."""
    return (f'<circle cx="{x}" cy="{y}" r="13" fill="#FFD60A" stroke="#111114" stroke-width="2"/>'
            + text(x, y + 5, str(n), 14, DARK, 800, "middle"))

docs = []

# ============================================================ L2-01 Kinderseite unveraendert
d = Doc2("L2-01", "Kinderseite – bleibt dünn (unverändert gegenüber 1.1.3)", "Konzept §2.1 · heute mockups/01",
         ["Unverändert: Modusleiste, 12 große Pads, Zurück/Wiederholen, Alles still, nonverbaler Puls, Lautstärke rechts oben mit Eltern-Grenze, kleines Eltern-Schloss (2 s halten + Rechenaufgabe).",
          "Neu ist nur, wohin das Schloss führt: nicht mehr in ein modales Einstellungsfenster, sondern in die Eltern-Pad-Ansicht desselben Fensters (L2-02). Pads, Farben und Launchpad-LEDs bleiben identisch."],
         GREEN)
d.add(mode_bar(0), volume())
cols = ["green", "yellow", "white", "white", "green", "yellow", "yellow", "white", "white", "green", "white", "white"]
special = {}
x, y, s = grid_pos(5)
special[5] = pad(x, y, s, 6, "yellow", None, "circle", extra=icon("wave", x + s/2 - 26, y + s/2 - 26, 52, "#00000069", 3.2))
d.add(pads(cols, special=special), kid_bottom(redo=False, beat=1))
docs.append(("L2-01_kinderseite_unveraendert", d))

# ============================================================ L2-02 Eltern-Pad-Ansicht, Detailfeld zu (Variante A)
d = Doc2("L2-02", "Eltern-Pad-Ansicht (Variante A) – Raster oben, Detailfeld eingeklappt", "Konzept §2.2 · ersetzt Elternbereich-Dialog",
         ["(1) Kinder|Eltern-Umschalter: Eltern -> Kinder ein Tipp, Kinder -> Eltern über das Schloss mit Sperre. (2) Takt immer sichtbar, Tipp öffnet Takt korrigieren + Metronom. (3) Zurück/Wiederholen/Alles still wie bei Kindern.",
          "(4) Dieselben 12 Pads, spielbar wie auf der Kinderseite, mit Name, Länge, Mini-Welle und Zustandssymbol; Tipp auf den Rand wählt, Tipp auf das Symbol startet/stoppt. (5) Werkzeugleiste links: Verlauf, Sets, Export, Pegel, Geräte, System öffnen eine Seitenleiste über dem Raster.",
          "(6) Detailfeld des gewählten Pads unten, eingeklappt nur eine Zeile (Tab, Doppelklick oder Taste Enter klappt auf). Tasten: Pfeile wählen, Leertaste spielt, R nimmt auf, Entf löscht (mit Zurück), Strg+Z/Y."])
d.add(rail("Pads"), top_bar())
g, sw, sh = slot_grid(108, 112, 1148, 588, selected=4)
d.add(g)
# eingeklapptes Detailfeld
d.add(rect(108, 716, 1148, 64, 16, SURF2, LINE, 1.5))
d.add(rect(124, 730, 36, 36, 10, GREEN), text(142, 754, "5", 15, DARK, 800, "middle"))
d.add(text(176, 744, "Pad 5 · Trommel", 17, TEXT, 800), text(176, 766, "2 Takte · im Raster · Rubber Band · Spitze −9 dBFS", 13, DIM, 500))
tabs, _ = detail_tabs(640, 729, ["Loop", "Pad", "Aufnahme", "Effekte (später)"], None)
d.add(tabs)
d.add(icon_button(1196, 728, "chevup", None, 44, 40))
d.add(annot(116, 36, 1), annot(348, 36, 2), annot(652, 36, 3), annot(372, 124, 4), annot(30, 34, 5), annot(118, 724, 6))
docs.append(("L2-02_eltern_pad_ansicht_A", d))

# ============================================================ L2-03 Detailfeld offen: Loop (Wellenform, Kuerzen, Marker)
d = Doc2("L2-03", "Detailfeld offen – Loop: Wellenform, Kürzen, Marker, Strecken", "Konzept §2.2 · heute „Erweitert“ (mockups/13)",
         ["Das Raster rückt zusammen (Pads bleiben spielbar und gewählt), das Detailfeld zeigt den Loop des gewählten Pads auf den Schlag-Linien (1.1 … 2.4).",
          "(1) Griffe Anfang/Ende kürzen direkt in der Welle, die Länge rastet auf Takte (Schalter); (2) Marker A/B orange, Klick in die Welle + M setzt einen Marker; (3) Abspielkopf weiß beim Anhören.",
          "(4) Eine Aktionszeile statt drei Karten: Anhören · Marker · Strecken · Exportieren, rechts die Kürz-Bilanz mit Verwerfen/Übernehmen. Zurück nimmt alles zurück, das Original bleibt im Verlauf."])
d.add(rail("Pads"), top_bar())
g, sw, sh = slot_grid(108, 112, 1148, 300, selected=4, gap=10)
d.add(g)
d.add(rect(108, 426, 1148, 354, 16, SURF2, LINE, 1.5))
d.add(rect(124, 440, 36, 36, 10, GREEN), text(142, 464, "5", 15, DARK, 800, "middle"))
d.add(text(176, 456, "Pad 5 · Trommel", 17, TEXT, 800), text(176, 476, "Aufnahme 4,00 s · 2 Takte · im Raster", 13, DIM, 500))
tabs, _ = detail_tabs(640, 440, ["Loop", "Pad", "Aufnahme", "Effekte (später)"], "Loop")
d.add(tabs, icon_button(1196, 439, "chev", None, 44, 40))
d.add(beat_wave(132, 496, 1100, 150, bars=2, trim=(0.0, 0.875), markers=((0.25, "A"), (0.505, "B")), play=0.38))
x = 132
b, x = small_btn(x, 692, "Anhören", "play"); d.add(b)
b, x = small_btn(x + 10, 692, "Marker", "flag"); d.add(b)
b, x = small_btn(x + 10, 692, "Strecken", "stretch"); d.add(b)
b, x = small_btn(x + 10, 692, "Export", "download"); d.add(b)
d.add(toggle(x + 22, 695, True, "Takt rasten"))
d.add(text(640, 668, "Kürzen: neu 3,50 s · 2 Takte (mit Stille aufgefüllt) · vorher 4,00 s", 13.5, TEXT, 700, "middle"))
b, _ = small_btn(1232 - 318, 692, "Verwerfen"); d.add(b)
d.add(button(1232 - 170, 692, 170, 42, "Übernehmen", "primary", "check", 14.5))
d.add(annot(1219, 548, 1), annot(258, 506, 2), annot(566, 628, 3), annot(124, 690, 4))
docs.append(("L2-03_eltern_detail_loop_kuerzen", d))

# ============================================================ L2-04 Detailfeld: Pad-Einstellungen, Takes, Pegel
d = Doc2("L2-04", "Detailfeld – Pad: Name, freier Modus, Lautstärke je Pad, Takes, Pegel der Aufnahme", "Konzept §2.2 · neu (heute verteilt auf Verlauf-Modus, Pegel-Seite)",
         ["Alles, was zu genau diesem Pad gehört, an einer Stelle: Name (nur Eltern sehen ihn), freier Modus, Pad-Lautstärke (neu, Ereignis pad_gain), Start am Takt.",
          "Takes: frühere Aufnahmen des Pads zum Anhören und Zurückholen (heute nur über den Kinder-Modus „Verlauf“ erreichbar). Pegel der letzten Aufnahme mit Zielzone, „zu laut“ hier statt auf einer eigenen Seite.",
          "Effekte bleiben ausgegraut, bis der Rust-Kern sie trägt (E3)."])
d.add(rail("Pads"), top_bar())
g, sw, sh = slot_grid(108, 112, 1148, 300, selected=4, gap=10)
d.add(g)
d.add(rect(108, 426, 1148, 354, 16, SURF2, LINE, 1.5))
d.add(rect(124, 440, 36, 36, 10, GREEN), text(142, 464, "5", 15, DARK, 800, "middle"))
d.add(text(176, 456, "Pad 5 · Trommel", 17, TEXT, 800), text(176, 476, "Aufnahme 4,00 s · 2 Takte · im Raster", 13, DIM, 500))
tabs, _ = detail_tabs(640, 440, ["Loop", "Pad", "Aufnahme", "Effekte (später)"], "Pad")
d.add(tabs, icon_button(1196, 439, "chev", None, 44, 40))
# Spalte 1: Pad
d.add(text(132, 516, "Name", 13, DIM, 700))
d.add(rect(132, 526, 300, 44, 12, SURF, PACC, 1.5), text(148, 554, "Trommel", 16, TEXT, 600))
d.add(toggle(132, 590, False, "Freier Modus", "eigene Länge, nie gestreckt"))
d.add(toggle(132, 646, True, "Start am Takt", "wartet auf den nächsten Takt"))
d.add(text(132, 722, "Pad-Lautstärke", 13, DIM, 700))
d.add(hslider(132, 748, 300, 0.8, "", "", "−2 dB"))
# Spalte 2: Takes
d.add(text(476, 516, "Takes dieses Pads", 13, DIM, 700))
for k, (lab, sub, cur) in enumerate([("Jetzt", "4,00 s · heute 16:42", True), ("Vorher", "3,80 s · 16:40", False), ("Davor", "4,20 s · 16:31", False)]):
    yy = 528 + k * 62
    d.add(rect(476, yy, 360, 54, 12, "#2F3550" if cur else SURF, PACC if cur else "#3A3A41", 1.5))
    d.add(mini_wave(490, yy + 12, 90, 30, k + 11, SKY, 22))
    d.add(text(596, yy + 24, lab, 15, TEXT, 700), text(596, yy + 43, sub, 12, DIM, 500))
    d.add(icon_button(736, yy + 7, "play", None, 40, 40))
    if not cur:
        d.add(icon_button(784, yy + 7, "undo", None, 40, 40))
# Spalte 3: Pegel
d.add(text(880, 516, "Pegel der Aufnahme", 13, DIM, 700))
d.add(meter(880, 546, 352, 28, -9, -7))
d.add(text(880, 618, "Spitze −7 dBFS · im Ziel", 15, GREEN, 700))
d.add(text(880, 640, "Mikrofon-Trim und Grenze: Werkzeug „Pegel“", 12.5, DIM, 500))
d.add(rect(880, 662, 352, 96, 14, "#FF9F0A14", "#FF9F0A55", 1.5))
d.add(icon("alert", 896, 676, 22, ORANGE, 2.2), text(928, 692, "Zu laut gewesen: einmal", 14.5, TEXT, 700))
d.add(text(928, 714, "Take „Davor“ · Spitze 0 dBFS", 12.5, "#C7C7CC", 500), text(928, 736, "Tipp: Mikro weiter weg oder Trim senken", 12.5, DIM, 500))
docs.append(("L2-04_eltern_detail_pad_takes_pegel", d))

# ============================================================ L2-05 Werkzeug als Seitenleiste (Pegel)
d = Doc2("L2-05", "Werkzeug als Seitenleiste – Pegel (gleiches Muster für Verlauf, Sets, Export, Geräte, System)", "Konzept §2.3 · heute Seiten 09–16",
         ["Einstellungen und Werkzeuge verdrängen das Raster nicht mehr: sie öffnen sich rechts als Leiste (480 px), das Raster bleibt sichtbar und spielbar – Pegel prüft man, während das Kind spielt.",
          "Ein einziges Speicher-Verhalten: alles wirkt sofort und wird sofort gesichert (heute: Pegel sofort, Rest erst nach „Speichern“, Untertitel sagt aber „gelten sofort“). Neustart-Felder tragen ihr Zeichen direkt am Feld.",
          "ESC oder erneuter Tipp auf das Werkzeug schließt die Leiste. Keine internen Schlüssel (sample_rate, data_dir) im Text."])
d.add(rail("Pegel"), top_bar())
g, sw, sh = slot_grid(108, 112, 640, 588, selected=4, gap=12)
d.add(g)
d.add(rect(108, 716, 640, 64, 16, SURF2, LINE, 1.5))
d.add(rect(124, 730, 36, 36, 10, GREEN), text(142, 754, "5", 15, DARK, 800, "middle"))
d.add(text(176, 744, "Pad 5 · Trommel", 17, TEXT, 800), text(176, 766, "2 Takte · im Raster", 13, DIM, 500))
d.add(icon_button(688, 728, "chevup", None, 44, 40))
# Seitenleiste
d.add(f'<rect x="764" y="104" width="496" height="680" rx="18" fill="#000000" opacity="0.35" filter="url(#soft)"/>')
d.add(rect(772, 108, 484, 672, 18, "#17171B", PACC, 1.5))
d.add(icon("sliders", 796, 128, 26, PACC, 2.2), text(834, 149, "Pegel", 22, TEXT, 800))
d.add(text(834, 170, "wirkt sofort · automatisch gesichert", 13, GREEN, 600))
d.add(icon_button(1196, 122, "x", None, 44, 44))
d.add(text(796, 214, "Höchste Lautstärke (nur Eltern)", 15, TEXT, 700))
d.add(hslider(812, 258, 420, 0.8, "−30 dBFS", "0 dBFS", "−6 dBFS"))
d.add(toggle(796, 312, True, "Limiter auf die Summe", "immer an"))
d.add(rect(796, 364, 436, 66, 12, "#FF9F0A14", "#FF9F0A55", 1.5))
d.add(icon("alert", 810, 378, 22, ORANGE, 2.2), text(842, 392, "dBFS ist nicht dB am Ohr", 14, TEXT, 700))
d.add(text(842, 414, "Kopfhörer zählen mit · WHO: 75 dBA, 40 h/Woche", 12.5, "#C7C7CC", 500))
d.add(text(796, 470, "Mikrofon", 15, TEXT, 700))
d.add(meter(796, 494, 436, 24, -14, -10))
d.add(hslider(812, 590, 420, 0.5, "−24 dB", "+24 dB", "Trim 0 dB"))
d.add(toggle(796, 634, True, "Soft-Clip am Eingang", "immer an"))
d.add(toggle(796, 680, False, "Pegel automatisch nachziehen", "Standard aus · festes Trim ist vorhersehbarer"))
d.add(toggle(796, 726, True, "Naht weich zeichnen", "gegen Klicks am Loop-Ende"))
docs.append(("L2-05_eltern_werkzeug_seitenleiste_pegel", d))

# ============================================================ L2-06 Variante B: Raster links, Detail rechts
d = Doc2("L2-06", "Variante B – Raster links, Detailfeld rechts", "Konzept §2.4 · Vergleich mit A",
         ["Vorteil: Detail immer sichtbar, Pads bleiben quadratisch wie auf der Kinderseite, auf 1920 × 1080 viel Platz. Nachteil: Welle nur ~470 px breit (Marker und Kürzen fummeliger), bei 1024 px werden Pads und Welle zu klein.",
          "Werkzeuge und Takt wie in A. Empfehlung bleibt A (Welle in voller Breite, näher an der Session-Ansicht mit Detail unten), B als Breitbild-Layout ab 1600 px denkbar."])
d.add(rail("Pads"), top_bar())
gx0, gy0, gw = 108, 112, 600
side = (gw - 3 * 12) / 4
for i in range(12):
    r, c = divmod(i, 4)
    color, name, bars, st, free = DEMO[i]
    d.add(slot(gx0 + c * (side + 12), gy0 + r * (side + 12), side, side, i + 1, color, name, bars, i == 4, free, None if free else st, i + 3))
d.add(rect(724, 112, 532, 668, 16, SURF2, LINE, 1.5))
d.add(rect(740, 128, 36, 36, 10, GREEN), text(758, 152, "5", 15, DARK, 800, "middle"))
d.add(text(790, 144, "Pad 5 · Trommel", 17, TEXT, 800), text(790, 164, "4,00 s · 2 Takte · im Raster", 13, DIM, 500))
tabs, _ = detail_tabs(740, 184, ["Loop", "Pad", "Aufnahme", "Effekte"], "Loop")
d.add(tabs)
d.add(beat_wave(744, 240, 492, 170, bars=2, trim=(0.0, 0.875), markers=((0.25, "A"), (0.505, "B"))))
x = 744
b, x = small_btn(x, 444, "Anhören", "play"); d.add(b)
b, x = small_btn(x + 8, 444, "Marker", "flag"); d.add(b)
b, x = small_btn(x + 8, 444, "Strecken", "stretch"); d.add(b)
d.add(toggle(744, 506, True, "Takt rasten", "ganze Takte"))
d.add(text(744, 586, "Neu 3,50 s · 2 Takte (aufgefüllt)", 15, TEXT, 700), text(744, 608, "vorher 4,00 s", 12.5, DIM, 500))
b, _ = small_btn(744, 630, "Verwerfen"); d.add(b)
d.add(button(870, 630, 170, 42, "Übernehmen", "primary", "check", 14.5))
d.add(text(744, 730, "Pads quadratisch, 141 px bei 1280 × 800", 12.5, DIM, 500))
d.add(text(744, 750, "bei 1024 × 640: 105 px, Welle 360 px", 12.5, ORANGE, 600))
d.add(rect(108, 736, 600, 44, 12, SURF2, LINE, 1.5), text(124, 764, "Unter dem Raster: Platz für Szenen-/Spurknöpfe (Option S)", 13, DIM, 500))
docs.append(("L2-06_eltern_variante_B_raster_links", d))

# ============================================================ L2-07 Option S: Spuren und Szenen
d = Doc2("L2-07", "Option S – Spuren und Szenen auf demselben 4 × 3-Raster", "Konzept §2.5 · Entscheidung für 2.0",
         ["Spalten = Spuren (je Spur spielt höchstens ein Pad, ein neues löst das alte am Takt ab), Zeilen = Szenen (▶ rechts startet die ganze Zeile am Takt). Unten je Spur Stopp, Lautstärke und Stumm.",
          "Für Kinder bleibt alles wie heute (Schalter „Spalten als Spuren“ wirkt nur, wenn Eltern ihn setzen; Standard aus). Datenmodell Spur × Szene × Slot gehört trotzdem von Anfang an in den Rust-Kern (E1), damit E2 kein Umbau wird.",
          "Launchpad: Szenen-Knöpfe rechts = ▶ der Zeilen, untere Reihe = Spur-Stopp (siehe L2-08)."])
d.add(rail("Pads"), top_bar())
names = ["Stimme", "Klatschen", "Trommel", "Geräusche"]
gx0, gy0, gw, gh = 108, 148, 1040, 420
sw = (gw - 3 * 14) / 4; sh = (gh - 2 * 14) / 3
for c, nm in enumerate(names):
    x = gx0 + c * (sw + 14)
    d.add(rect(x, 108, sw, 32, 10, SURF), text(x + 14, 129, f"Spur {c+1} · {nm}", 14, TEXT, 700))
demo_s = [("yellow", "Lied A", "2 Takte", "play", False), ("green", "Klatschen", "1 Takt", "loop", False), ("green", "Trommel", "2 Takte", "loop", False), ("white", None, None, "record", False),
          ("green", "Lied B", "2 Takte", "loop", False), ("yellow", "Stampfen", "1 Takt", "play", False), ("yellow", "Trommel 2", "2 Takte", "play", False), ("yellow", "Rassel", "1 Takt", "play", False),
          ("white", None, None, "record", False), ("yellow", "Schnipsen", "1 Takt", "play", False), ("white", None, None, "record", False), ("white", None, None, "record", False)]
for i in range(12):
    r, c = divmod(i, 4)
    color, name, bars, st, free = demo_s[i]
    d.add(slot(gx0 + c * (sw + 14), gy0 + r * (sh + 14), sw, sh, i + 1, color, name, bars, i == 6, free, st, i + 7))
for r in range(3):
    y = gy0 + r * (sh + 14)
    d.add(rect(1160, y, 96, sh, 14, SURF, "#3A3A41", 1.5), icon("play", 1194, y + sh/2 - 22, 28, GREEN if r == 1 else TEXT), text(1208, y + sh/2 + 28, f"Szene {r+1}", 12.5, DIM, 600, "middle"))
# Mixer-Zeile
d.add(rect(108, 584, 1148, 196, 16, SURF2, LINE, 1.5))
d.add(text(124, 612, "Spuren", 15, TEXT, 800), text(196, 612, "(Detailfeld-Tab „Mixer“, nur mit Option S)", 13, DIM, 500))
for c, nm in enumerate(names):
    x = gx0 + c * (sw + 14)
    d.add(icon_button(x + 8, 630, "stop", "Stopp", 64, 56))
    d.add(icon_button(x + 80, 630, "vol_lo", "Stumm", 64, 56))
    d.add(hslider(x + 20, 736, sw - 40, [0.7, 0.8, 0.65, 0.5][c], "", "", ["−3 dB", "−2 dB", "−4 dB", "−6 dB"][c], SKY))
d.add(icon_button(1160, 630, "stop", "Alle", 96, 56))
docs.append(("L2-07_option_S_spuren_szenen", d))

# ============================================================ L2-08 Launchpad-Spiegelung
d = Doc2("L2-08", "Launchpad-Spiegelung – Kindermodus und Elternmodus", "Konzept §2.6 · midi/launchpad.py (Programmer-Modus)",
         ["Links Kindermodus wie heute: nur das 4 × 3-Feld oben links leuchtet in den Pad-Farben, alles andere bleibt dunkel (reizarm). Neu optional: oberste Reihe = die fünf Modi in ihren Farben.",
          "Rechts Elternmodus: gewähltes Pad atmet weich (LED-Puls, kein Blinken), rechte Knopfspalte = Szenen-▶ (Option S) bzw. Zurück/Wiederholen/Alles still, unterste Reihe = Spur-Stopp. Pfeiltasten oben wählen das Pad wie die Pfeiltasten am Rechner.",
          "Grundlage nur Novations öffentliches Programmer's Reference; die heutige Abbildung (note_for/pad_for) bleibt, sie wird nur um Knopf-Ereignisse erweitert. Test am echten Gerät steht weiter aus."])

def launchpad(x, y, size, mode):
    out = [rect(x, y, size, size, 22, "#1A1A1E", "#3A3A41", 2)]
    cell = (size - 40) / 9
    gap = cell * 0.14
    colmap = {"green": GREEN, "yellow": YELLOW, "white": "#E8E8EA", "red": RED}
    kid_cols = ["green", "yellow", "white", "white", "green", "yellow", "yellow", "white", "white", "green", "white", "white"]
    for row in range(9):
        for col in range(9):
            cx = x + 20 + col * cell
            cy = y + 20 + row * cell
            top = row == 0
            right = col == 8
            if top and right:
                out.append(f'<circle cx="{cx+cell/2:.1f}" cy="{cy+cell/2:.1f}" r="{cell*0.22:.1f}" fill="#2A2A30"/>')
                continue
            if top or right:
                fill = "#26262B"
                if mode == "kid" and top and col < 5:
                    fill = [GREEN, RED, BLUE, ORANGE, PURPLE][col]
                if mode == "parent":
                    if top and col < 4:
                        fill = "#5A5A60"  # Pfeile
                    if right and 1 <= row <= 3:
                        fill = GREEN if row == 2 else "#4A4A52"
                    if right and row == 6:
                        fill = GRAY
                    if right and row == 7:
                        fill = "#8E8E93"
                    if right and row == 8:
                        fill = RED
                out.append(f'<circle cx="{cx+cell/2:.1f}" cy="{cy+cell/2:.1f}" r="{cell*0.36:.1f}" fill="{fill}"/>')
                continue
            r, c = row - 1, col
            fill = "#232327"
            if r < 3 and c < 4:
                fill = colmap[kid_cols[r * 4 + c]]
            if mode == "parent" and r == 7 and c < 4:
                fill = "#7A2A28"
            out.append(f'<rect x="{cx+gap/2:.1f}" y="{cy+gap/2:.1f}" width="{cell-gap:.1f}" height="{cell-gap:.1f}" rx="{cell*0.14:.1f}" fill="{fill}"/>')
            if mode == "parent" and r == 1 and c == 0:
                out.append(f'<rect x="{cx+gap/2-4:.1f}" y="{cy+gap/2-4:.1f}" width="{cell-gap+8:.1f}" height="{cell-gap+8:.1f}" rx="{cell*0.18:.1f}" fill="none" stroke="{SKY}" stroke-width="3" stroke-dasharray="6 4"/>')
    return "\n".join(out)

d.add(text(60, 60, "Kindermodus", 22, TEXT, 800), text(60, 86, "wie heute + optional Modus-Reihe", 14, DIM, 500))
d.add(launchpad(60, 110, 520, "kid"))
d.add(text(700, 60, "Elternmodus", 22, TEXT, 800), text(700, 86, "gewähltes Pad atmet · Knöpfe bekommen Aufgaben", 14, DIM, 500))
d.add(launchpad(700, 110, 520, "parent"))
d.add(text(700, 668, "obere Reihe: ← → ↑ ↓ wählen das Pad", 13, "#C7C7CC", 500))
d.add(text(700, 690, "rechte Spalte: Szenen ▶ (Option S), Zurück, Wiederholen, Alles still", 13, "#C7C7CC", 500))
d.add(text(700, 712, "untere Pad-Reihe: Spur-Stopp (Option S) · gestrichelt: gewähltes Pad (LED-Puls)", 13, "#C7C7CC", 500))
d.add(text(60, 668, "oberste Reihe (optional): Spielen · Aufnehmen · Loop · Löschen · Verlauf", 13, "#C7C7CC", 500))
d.add(text(60, 690, "übrige 52 Pads dunkel: nichts lenkt ab", 13, "#C7C7CC", 500))
docs.append(("L2-08_launchpad_spiegelung", d))

# ============================================================ L2-09 Moduswechsel und Sperre
d = Doc2("L2-09", "Moduswechsel mit Sperre – Kinder → Eltern nur über das Schloss, Eltern → Kinder ein Tipp", "Konzept §2.3 · parent_gate.py, parent_tile.py",
         ["Gleiches Fenster, kein modaler Dialog: die Kinderseite wird abgedunkelt, die Rechenaufgabe liegt darüber; Musik läuft weiter. Nach richtiger Antwort blendet das Fenster in die Eltern-Pad-Ansicht über (L2-02).",
          "Zurück zu den Kindern: Umschalter oben links oder Taste F1; nach N Minuten ohne Eingabe (Standard 10, einstellbar) kehrt die Ansicht von selbst zur Kinderseite zurück. Die Sperre bleibt 5 min offen, falls Eltern gleich wieder wechseln (einstellbar, 0 = immer fragen)."],
         PACC)
d.add(mode_bar(0), volume())
cols = ["green", "yellow", "white", "white", "green", "yellow", "yellow", "white", "white", "green", "white", "white"]
d.add(pads(cols), kid_bottom(beat=2))
d.add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0E0E10" opacity="0.78"/>')
d.add(rect(370, 150, 540, 470, 26, "#1B1B1F", PACC, 2))
d.add(icon("lock", 610, 180, 60, PACC, 2.4))
d.add(text(640, 290, "Für Erwachsene", 26, TEXT, 800, "middle"))
d.add(text(640, 340, "27 + 18 = ?", 40, TEXT, 800, "middle"))
d.add(rect(470, 382, 200, 76, 16, SURF, PACC, 2), text(570, 432, "45", 34, TEXT, 800, "middle"))
d.add(button(686, 382, 124, 76, "OK", "primary", "check", 22))
d.add(text(640, 510, "Zahl eingeben wie heute · Musik läuft weiter · ESC bricht ab", 15, DIM, 500, "middle"))
d.add(rect(430, 540, 420, 52, 14, SURF), text(640, 573, "Sperre 5 Minuten offen lassen", 15, "#C7C7CC", 600, "middle"))
docs.append(("L2-09_moduswechsel_sperre", d))

def render_png(name, svg):
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import QByteArray
    app = QGuiApplication.instance() or QGuiApplication(["x"])
    r = QSvgRenderer(QByteArray(svg.encode()))
    img = QImage(W, H + CAP2, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img); r.render(p); p.end()
    img.save(os.path.join(OUT, name + ".png"))

if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name, doc in docs:
        svg = fix_alpha(doc.svg()).replace("Mockup L2-", "Loopstation 2 · L2-")
        with open(os.path.join(OUT, name + ".svg"), "w") as f:
            f.write(svg)
        if "--png" in sys.argv:
            render_png(name, svg)
    print("\n".join(n for n, _ in docs))
