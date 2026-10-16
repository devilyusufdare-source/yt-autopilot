"""Build an ASS subtitle file with big centred captions and the spoken word highlighted."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .tts import Word


@dataclass
class Group:
    words: list[Word]
    end: float


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (ASS stores colours as BGR)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def group_words(scene_words: list[list[Word]], per_group: int) -> list[Group]:
    """Chunk words into small groups; never cross a scene boundary, break after sentence ends."""
    groups: list[Group] = []
    for words in scene_words:
        words = [w for w in words if w.text.strip()]
        i, n = 0, len(words)
        while i < n:
            cur: list[Word] = []
            while i < n:
                cur.append(words[i])
                i += 1
                if cur[-1].text[-1] in ".!?" and len(cur) >= 2:
                    break  # sentence ended: start a fresh group
                if len(cur) >= per_group:
                    if n - i == 1:  # absorb a lonely last word
                        cur.append(words[i])
                        i += 1
                    break
            groups.append(Group(cur, cur[-1].end))
    # A group stays on screen until the next one starts, but not through long pauses.
    for k, g in enumerate(groups):
        nxt = groups[k + 1].words[0].start if k + 1 < len(groups) else g.end + 0.4
        g.end = nxt if nxt - g.end <= 0.45 else g.end + 0.45
    return groups


def _layout(tokens: list[str], max_chars: int) -> list[list[int]]:
    """Split token indexes into lines of at most max_chars characters (always >= 1 token per line)."""
    lines: list[list[int]] = [[]]
    length = 0
    for i, tok in enumerate(tokens):
        add = len(tok) + (1 if lines[-1] else 0)
        if lines[-1] and length + add > max_chars:
            lines.append([i])
            length = len(tok)
        else:
            lines[-1].append(i)
            length += add
    return lines


def build_ass(scene_words: list[list[Word]], cfg: Config, out: Path, top_label: str | None,
              total_duration: float, hook_card: str | None = None, hook_end: float = 0.0,
              end_text: str | None = None, labels: list[tuple[float, float, str]] | None = None) -> Path:
    """`labels` = timed top pills [(start, end, text), ...] (used by long videos for chapter names);
    `top_label` is one pill for the whole video."""
    w, h = cfg.width, cfg.height
    font = cfg.get("captions.font_name", "Poppins ExtraBold")
    size = int(cfg.get("captions.font_size", 96))
    upper = bool(cfg.get("captions.uppercase", True))
    per_group = int(cfg.get("captions.words_per_group", 3))
    max_chars = int(cfg.get("captions.max_chars_per_line", 15))
    text_c = _ass_color(cfg.get("captions.text_color", "#FFFFFF"))
    hi_c = _ass_color(cfg.get("captions.highlight_color", "#FFD400"))
    outline = int(cfg.get("captions.outline_px", 8))
    y = int(h * float(cfg.get("captions.y_percent", 56)) / 100)
    hi_tag = f"\\c&H{hi_c[4:]}&"  # override tags take &HBBGGRR&
    base_tag = f"\\c&H{text_c[4:]}&"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{text_c},{text_c},&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,{outline},4,5,80,80,0,1
Style: Label,{font},{int(size * float(cfg.get("captions.label_scale", 0.38)))},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,2,0,3,14,0,8,80,80,{int(h * 0.105)},1
Style: Hook,{font},{int(size * 1.12)},{text_c},{text_c},&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,{outline + 2},5,5,70,70,0,1
Style: End,{font},{int(size * 0.42)},{hi_c},{hi_c},&H00000000,&HA0000000,-1,0,0,0,100,100,2,0,3,14,0,2,80,80,{int(h * 0.16)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines_out = [header]
    if top_label:
        label = _escape(top_label.upper() if upper else top_label)
        lines_out.append(f"Dialogue: 0,{_ts(0)},{_ts(total_duration)},Label,,0,0,0,,{label}\n")
    for start, end, text in labels or []:
        if end > start and text:
            label = _escape(text.upper() if upper else text)
            lines_out.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Label,,0,0,0,,{label}\n")

    if hook_card and hook_end > 0:
        # Full-sentence hook on screen for the whole first scene; word-by-word captions start at scene 2.
        text = hook_card.upper() if upper else hook_card
        tokens = [_escape(t) for t in text.split()]
        lines = _layout(tokens, max_chars + 2)
        rendered = "\\N".join(" ".join(tokens[i] for i in line) for line in lines)
        lines_out.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,{{\\pos({w // 2},{y})}}{rendered}\n")
        scene_words = scene_words[1:]

    if end_text:
        et = _escape(end_text.upper() if upper else end_text)
        lines_out.append(f"Dialogue: 0,{_ts(max(0.0, total_duration - 1.6))},{_ts(total_duration)},End,,0,0,0,,{et}\n")

    for g in group_words(scene_words, per_group):
        tokens = [_escape(wd.text.upper() if upper else wd.text) for wd in g.words]
        layout = _layout(tokens, max_chars)
        for k, wd in enumerate(g.words):
            start = wd.start
            end = g.words[k + 1].start if k + 1 < len(g.words) else g.end
            if end <= start:
                continue
            rendered_lines = []
            for line in layout:
                parts = []
                for i in line:
                    if i == k:
                        parts.append(f"{{{hi_tag}}}{tokens[i]}{{{base_tag}}}")
                    else:
                        parts.append(tokens[i])
                rendered_lines.append(" ".join(parts))
            text = "\\N".join(rendered_lines)
            lines_out.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{\\pos({w // 2},{y})}}{text}\n")

    out.write_text("".join(lines_out), encoding="utf-8")
    return out
