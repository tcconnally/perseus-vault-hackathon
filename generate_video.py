"""
Generate the Perseus Vault demo video for the hackathon submission.

Self-contained re-recorder:
  1. Synthesizes per-scene narration with OpenAI TTS (voice-over that MATCHES the
     current build: relational schema, ranked recall, decay, CockroachDB MCP).
  2. Renders terminal-style frames for each scene, timed to that scene's audio
     clip, so audio and video stay in sync.
  3. Concatenates the audio to voiceover.mp3 and muxes it with the frames into
     demo_video.mp4.

Requirements: pillow, ffmpeg/ffprobe on PATH, and OPENAI_API_KEY in the env.
Run:  python generate_video.py
"""

import math
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
BG_COLOR = (18, 18, 18)
PROMPT_COLOR = (0, 255, 100)       # green
OUTPUT_COLOR = (200, 200, 200)     # light gray
TITLE_COLOR = (100, 180, 255)      # blue
HIGHLIGHT_COLOR = (255, 200, 50)   # gold
FPS = 24
LINE_H = 48
SCENE_PAD_SEC = 0.8                # trailing silence per scene, for pacing

TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "onyx")
TTS_MODEL_FALLBACK = "tts-1"

_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.getenv("VIDEO_FRAMES_DIR", os.path.join(_HERE, ".video_frames"))
AUDIO_DIR = os.getenv("VIDEO_AUDIO_DIR", os.path.join(_HERE, ".video_audio"))
VIDEO_PATH = os.getenv("VIDEO_PATH", os.path.join(_HERE, "demo_video.mp4"))
VOICEOVER_PATH = os.getenv("VOICEOVER_PATH", os.path.join(_HERE, "voiceover.mp3"))

# --- fonts (cross-platform monospace) --------------------------------------
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]


def _load_fonts():
    for fp in FONT_CANDIDATES:
        if os.path.exists(fp):
            return (ImageFont.truetype(fp, 32),
                    ImageFont.truetype(fp, 24),
                    ImageFont.truetype(fp, 44))
    d = ImageFont.load_default()
    return d, d, d


font, font_small, font_title = _load_fonts()


def make_frame(text_lines, y_offset=90):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, WIDTH - 20, HEIGHT - 20], outline=(60, 60, 60), width=2)
    draw.rectangle([20, 20, WIDTH - 20, 60], fill=(40, 40, 40))
    draw.text((40, 26), "● ● ●  perseus-vault — bash — 192×48",
              fill=(150, 150, 150), font=font_small)
    y = y_offset
    for line in text_lines:
        text, color = line if isinstance(line, tuple) else (line, OUTPUT_COLOR)
        if text.startswith("# "):
            draw.text((40, y), text, fill=TITLE_COLOR, font=font_title)
            y += LINE_H + 8
        elif text.startswith("$ "):
            draw.text((40, y), text, fill=PROMPT_COLOR, font=font)
            y += LINE_H
        elif text.startswith(">>> "):
            draw.text((40, y), text, fill=HIGHLIGHT_COLOR, font=font)
            y += LINE_H
        else:
            draw.text((40, y), text, fill=color, font=font)
            y += LINE_H
    return img


# --- scenes: narration + on-screen terminal lines ---------------------------
SCENES = [
    {"say": "Perseus Vault. Agentic memory, built on CockroachDB and A W S.",
     "lines": [("# Perseus Vault", TITLE_COLOR),
               ("# Agentic Memory on CockroachDB x AWS", TITLE_COLOR)]},
    {"say": "Most A I agents forget everything the moment the conversation ends. "
            "Their memory is just a context window, and context windows reset.",
     "lines": [("# The problem", TITLE_COLOR), ("", OUTPUT_COLOR),
               ("Most AI agents forget everything", OUTPUT_COLOR),
               ("the moment the conversation ends.", OUTPUT_COLOR)]},
    {"say": "Tell a baseline agent your deployment target, and it says: got it.",
     "lines": [("$ python baseline_agent.py", PROMPT_COLOR),
               (">>> Remember: we deploy to AWS Lambda, us-east-1.", PROMPT_COLOR),
               ("[agent] Got it.", OUTPUT_COLOR)]},
    {"say": "But open a new session, ask what region you're deploying to, "
            "and the memory is simply gone.",
     "lines": [("--- New Session ---", HIGHLIGHT_COLOR),
               (">>> What region am I deploying to?", PROMPT_COLOR),
               ("[agent] I don't have that information.", OUTPUT_COLOR),
               (">>> The memory is gone.", HIGHLIGHT_COLOR)]},
    {"say": "Perseus Vault fixes this. It embeds each memory with Amazon Bedrock, "
            "and commits it to CockroachDB in a single transaction: content, "
            "metadata, vector, and an event record, together.",
     "lines": [("$ python bedrock_agent.py", PROMPT_COLOR),
               ("[bedrock] amazon.titan-embed-text-v2:0 -> 1024-d vector",
                OUTPUT_COLOR),
               ("[db] INSERT INTO memories (content, metadata,", PROMPT_COLOR),
               ("[db]   embedding, salience) ... RETURNING id", PROMPT_COLOR),
               ("[db] + memory_events (event_type='store')", PROMPT_COLOR),
               ("[db] committed transactionally.", OUTPUT_COLOR)]},
    {"say": "Because it's real distributed SQL, you can inspect it in plain "
            "language through the CockroachDB M C P Server, running against the "
            "very same cluster.",
     "lines": [("--- CockroachDB MCP Server ---", TITLE_COLOR), ("", OUTPUT_COLOR),
               (">>> \"show the newest memory and its salience\"", PROMPT_COLOR),
               ("[mcp] cockroachdb-mcp-server -> SQL", OUTPUT_COLOR),
               ("[mcp] SELECT id, content, salience FROM memories", OUTPUT_COLOR)]},
    {"say": "Every memory carries a salience score: how much it matters right now.",
     "lines": [(" id   | content                  | salience", HIGHLIGHT_COLOR),
               ("------+--------------------------+---------", HIGHLIGHT_COLOR),
               (" a1b2 | Phoenix -> Lambda,       | 1.00", OUTPUT_COLOR),
               ("      | us-east-1                |", OUTPUT_COLOR),
               ("", OUTPUT_COLOR),
               ("(1 row) distributed, transactional memory", OUTPUT_COLOR)]},
    {"say": "The agent runs stateless on A W S Lambda. On a cold start, with "
            "nothing in memory, it embeds the question and searches CockroachDB's "
            "distributed vector index.",
     "lines": [("--- New Lambda Invocation ---", TITLE_COLOR),
               ("[CloudWatch] Cold start. No in-memory state.", OUTPUT_COLOR),
               ("", OUTPUT_COLOR),
               (">>> What region am I deploying to?", PROMPT_COLOR),
               ("[recall] vector search -> candidate pool (C-SPANN)",
                OUTPUT_COLOR)]},
    {"say": "But recall is more than nearest neighbor. Perseus Vault re-ranks "
            "candidates by similarity, recency, and how often each memory is used, "
            "scaled by salience.",
     "lines": [("[recall] re-rank:", PROMPT_COLOR),
               ("[recall]   0.60 * similarity", PROMPT_COLOR),
               ("[recall] + 0.25 * recency", PROMPT_COLOR),
               ("[recall] + 0.15 * frequency", PROMPT_COLOR),
               ("[recall]   x salience", PROMPT_COLOR)]},
    {"say": "The right memory surfaces, and using it makes it stronger. "
            "You're deploying to A W S Lambda, in us-east-1. "
            "Memory survived across sessions.",
     "lines": [("[recall] top match score=0.94  reinforced +0.15", OUTPUT_COLOR),
               ("", OUTPUT_COLOR),
               (">>> You're deploying to AWS Lambda, us-east-1.", HIGHLIGHT_COLOR),
               ("", OUTPUT_COLOR),
               ("--- Memory survived across sessions. ---", OUTPUT_COLOR)]},
    {"say": "And what isn't used fades. A scheduled decay pass ages stale "
            "memories and archives them, so the working set stays sharp. "
            "Signal is kept alive by use; noise fades on its own.",
     "lines": [("$ python decay.py", PROMPT_COLOR),
               ("[decay] salience *= exp(-rate * days_idle)", OUTPUT_COLOR),
               ("[decay] stale memories archived (decayed_at set)", OUTPUT_COLOR),
               ("[decay] aged=42  archived=7", HIGHLIGHT_COLOR),
               ("--- Signal kept alive by use; noise fades. ---", OUTPUT_COLOR)]},
    {"say": "An agent doesn't just need to think and act. It needs to remember, "
            "reliably. Perseus Vault, built on CockroachDB and A W S.",
     "lines": [("# It needs to remember, reliably.", TITLE_COLOR),
               ("", OUTPUT_COLOR),
               ("# Perseus Vault", HIGHLIGHT_COLOR),
               ("# Built on CockroachDB x AWS", OUTPUT_COLOR),
               ("", OUTPUT_COLOR),
               ("github.com/tcconnally/perseus-vault-hackathon", OUTPUT_COLOR)]},
]


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def synth_scene_audio(text, raw_path):
    """Synthesize narration to mp3 via OpenAI TTS (with a model fallback)."""
    from openai import OpenAI
    client = OpenAI()
    for model in (TTS_MODEL, TTS_MODEL_FALLBACK):
        try:
            with client.audio.speech.with_streaming_response.create(
                model=model, voice=TTS_VOICE, input=text, response_format="mp3",
            ) as resp:
                resp.stream_to_file(raw_path)
            return
        except Exception as e:
            print(f"  TTS model {model} failed ({e}); trying fallback...")
    raise RuntimeError("All TTS models failed.")


def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set (needed for TTS narration).")
    for d in (OUTPUT_DIR, AUDIO_DIR):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    padded_clips = []
    frame_count = 0
    print(f"Synthesizing narration ({TTS_VOICE}) and rendering {len(SCENES)} scenes...")
    for i, scene in enumerate(SCENES):
        raw = os.path.join(AUDIO_DIR, f"scene_{i:02d}_raw.mp3")
        padded = os.path.join(AUDIO_DIR, f"scene_{i:02d}.wav")
        synth_scene_audio(scene["say"], raw)
        # Normalize to a common wav format and add trailing silence for pacing.
        _run(["ffmpeg", "-y", "-i", raw, "-af", f"apad=pad_dur={SCENE_PAD_SEC}",
              "-ar", "44100", "-ac", "2", padded])
        dur = probe_duration(padded)
        padded_clips.append(padded)

        num_frames = max(1, math.ceil(dur * FPS))
        img = make_frame(scene["lines"])
        for _ in range(num_frames):
            img.save(os.path.join(OUTPUT_DIR, f"frame_{frame_count:06d}.png"))
            frame_count += 1
        print(f"  scene {i+1:2d}/{len(SCENES)}: {dur:5.1f}s  {num_frames} frames")

    # Concatenate scene audio -> voiceover.mp3
    print("Concatenating voiceover...")
    concat_list = os.path.join(AUDIO_DIR, "concat.txt")
    with open(concat_list, "w") as f:
        for c in padded_clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
          "-c:a", "libmp3lame", "-q:a", "3", VOICEOVER_PATH])

    # Encode frames -> silent video
    print("Encoding video...")
    silent = VIDEO_PATH.replace(".mp4", "_novoice.mp4")
    _run(["ffmpeg", "-y", "-framerate", str(FPS),
          "-i", os.path.join(OUTPUT_DIR, "frame_%06d.png"),
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
          "-crf", "20", silent])

    # Mux voiceover
    print("Muxing voiceover...")
    _run(["ffmpeg", "-y", "-i", silent, "-i", VOICEOVER_PATH,
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
          "-map", "0:v:0", "-map", "1:a:0", VIDEO_PATH])

    os.remove(silent)
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    total = probe_duration(VIDEO_PATH)
    size = os.path.getsize(VIDEO_PATH) / 1024 / 1024
    print(f"\nDone. {VIDEO_PATH}  ({total:.1f}s, {size:.1f} MB)")


if __name__ == "__main__":
    main()
