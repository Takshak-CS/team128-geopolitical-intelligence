"""
narration.py — Phase 3: voice synthesis and video assembly
==========================================================
Takes the stats-based summary from preprocess.summarize(), strips it
to clean spoken prose, synthesizes a voice reading it (gTTS), and
assembles a short video brief (ffmpeg).

No external AI API required — the narration script comes from the
pipeline's own summarize() function, making this fully self-contained.

Requirements (on top of the main pipeline):
    pip install gTTS Pillow python-dotenv
    ffmpeg on PATH (winget install ffmpeg)
"""

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS

MEDIA_DIR = Path("media") / "briefings"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _strip_markdown(text: str) -> str:
    """Converts the markdown summary to clean, section-aware spoken prose."""
    sections = re.split(r'\n#{1,3}\s*', text)
    parts = []
    for section in sections:
        if not section.strip() or 'Auto-generated' in section:
            continue
        lines = section.strip().split('\n')
        body = '\n'.join(lines).strip()
        body = re.sub(r'\*\*(.+?)\*\*', r'\1', body)
        body = re.sub(r'\*(.+?)\*', r'\1', body)
        body = re.sub(r'·\s*BERT\s*[✓⚠·\s]*·?', ' ', body)
        body = re.sub(r'`[^`]+`\s*·?\s*', '', body)
        body = re.sub(r'\[([^\]]*source[^\]]*)]\([^)]+\)', '', body, flags=re.IGNORECASE)
        body = re.sub(r'\[([^\]]+)]\([^)]+\)', r'\1', body)
        body = re.sub(r'\*\*#\d+\*\*', '', body)
        body = re.sub(r'https?://\S+', '', body)
        body = re.sub(r'→', 'to', body)
        body = re.sub(r'[^\x00-\x7F]+', '', body)
        body = re.sub(r'[ \t]+', ' ', body)
        body = re.sub(r'---+', '', body)
        body = body.strip()
        if body and len(body) > 10:
            parts.append(body)
    return '\n\n'.join(parts)
def synthesize_voice(script_text: str, slug: str) -> Path:
    out_path = MEDIA_DIR / f"{slug}.mp3"
    clean = _strip_markdown(script_text)
    gTTS(text=clean, lang="en").save(str(out_path))
    return out_path, clean


def _load_font(size: int, bold: bool = False):
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(text, font, max_width, draw):
    """Word-wrap text to fit max_width pixels."""
    words = text.split()
    lines, current = [], []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _make_title_card(
    country_name: str,
    date: str,
    total_events: int,
    avg_goldstein: float,
    slug: str,
    clean_script: str,
) -> Path:
    card_path = MEDIA_DIR / f"{slug}_card.png"

    W, H = 1280, 720
    BG      = (10,  22,  32)
    SURFACE = (18,  32,  42)
    ACCENT  = (232, 118,  60)
    TEXT    = (237, 243, 245)
    MUTED   = (120, 150, 168)
    RULE    = ( 38,  60,  76)
    COOP    = ( 60, 180, 130)
    CONFLICT= (210,  80,  65)

    gs_color = COOP if avg_goldstein >= 1 else CONFLICT if avg_goldstein <= -1 else MUTED
    tone_word = "COOPERATIVE" if avg_goldstein >= 1 else "CONFLICTUAL" if avg_goldstein <= -1 else "NEUTRAL"

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Left accent bar
    draw.rectangle([0, 0, 5, H], fill=ACCENT)

    # Top bar
    draw.rectangle([0, 0, W, 58], fill=SURFACE)
    draw.text((22, 18), "GDELT PULSE  -  WIRE INTELLIGENCE", font=_load_font(17), fill=ACCENT)
    fmt_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    draw.text((W - 22, 20), fmt_date, font=_load_font(17), fill=MUTED, anchor="ra")

    # Country name - very large
    country_up = country_name.upper()
    draw.text((22, 82), country_up, font=_load_font(90, bold=True), fill=TEXT)

    # Tone classification stamp
    draw.rectangle([22, 196, 22 + 220, 228], fill=(*gs_color, 30) if False else SURFACE)
    draw.rectangle([22, 196, 22 + 220, 228], outline=gs_color, width=1)
    draw.text((132, 212), tone_word, font=_load_font(18), fill=gs_color, anchor="mm")

    # Rule
    draw.rectangle([22, 244, W - 22, 246], fill=RULE)

    # Stats - large numbers side by side
    draw.text((22,  268), str(total_events), font=_load_font(52, bold=True), fill=TEXT)
    draw.text((22,  330), "EVENTS RECORDED", font=_load_font(14), fill=MUTED)

    gs_str = f"{avg_goldstein:+.2f}"
    draw.text((340, 268), gs_str, font=_load_font(52, bold=True), fill=gs_color)
    draw.text((340, 330), "AVG GOLDSTEIN SCORE", font=_load_font(14), fill=MUTED)

    # Rule
    draw.rectangle([22, 362, W - 22, 364], fill=RULE)

    # Clean short summary (3 sentences max)
    summary_lines = [l.strip() for l in clean_script.split(". ") if l.strip()][:3]
    summary_text = ". ".join(summary_lines) + "."
    font_body = _load_font(17)
    wrapped = _wrap(summary_text, font_body, W - 44, draw)
    y = 382
    for line in wrapped[:4]:
        draw.text((22, y), line, font=font_body, fill=MUTED)
        y += 26

    # Bottom bar
    draw.rectangle([0, H - 46, W, H], fill=SURFACE)
    draw.text((22, H - 25), "Powered by GDELT V1  -  spaCy NER  -  KMeans Clustering  -  FastAPI  -  React",
              font=_load_font(13), fill=RULE)

    img.save(card_path)
    return card_path
def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it with: winget install ffmpeg\n"
            "Then close and reopen VS Code so the new PATH takes effect."
        )


def assemble_video(audio_path: Path, card_path: Path, slug: str) -> Path:
    _check_ffmpeg()
    out_path = MEDIA_DIR / f"{slug}.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(card_path),
        "-i", str(audio_path),
        "-filter_complex",
        "[1:a]showwaves=s=1180x100:mode=cline:colors=0xE8763C[wave];"
        "[0:v][wave]overlay=50:H-120[outv]",
        "-map", "[outv]", "-map", "1:a",
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-shortest",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr[-2000:]}")
    return out_path


def generate_briefing(
    raw_summary: str,
    country_name: str,
    date: str,
    country_code: str,
    total_events: int,
    avg_goldstein: float,
    force: bool = False,
) -> dict:
    slug = f"{date}_{country_code.upper()}"
    mp3_path    = MEDIA_DIR / f"{slug}.mp3"
    mp4_path    = MEDIA_DIR / f"{slug}.mp4"
    script_path = MEDIA_DIR / f"{slug}.txt"

    if not force and mp3_path.exists() and mp4_path.exists() and script_path.exists():
        return {
            "polished_script": script_path.read_text(encoding="utf-8"),
            "audio_file":      mp3_path.name,
            "video_file":      mp4_path.name,
            "cached":          True,
        }

    audio_result = synthesize_voice(raw_summary, slug)
    audio_path, clean_script = audio_result
    script_path.write_text(clean_script, encoding="utf-8")

    card_path  = _make_title_card(
        country_name, date, total_events, avg_goldstein, slug, clean_script
    )
    video_path = assemble_video(audio_path, card_path, slug)

    return {
        "polished_script": clean_script,
        "audio_file":      audio_path.name,
        "video_file":      video_path.name,
        "cached":          False,
    }