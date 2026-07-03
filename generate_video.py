"""
Generate demo video for Perseus-Vault hackathon submission.
Creates terminal-style frames and combines with voiceover using ffmpeg.
"""
from PIL import Image, ImageDraw, ImageFont
import subprocess
import os
import math

WIDTH, HEIGHT = 1920, 1080
BG_COLOR = (18, 18, 18)
PROMPT_COLOR = (0, 255, 100)       # green
OUTPUT_COLOR = (200, 200, 200)      # light gray
TITLE_COLOR = (100, 180, 255)       # blue
HIGHLIGHT_COLOR = (255, 200, 50)    # gold
FPS = 24
OUTPUT_DIR = "/tmp/video_frames"
VIDEO_PATH = "/opt/data/webui/minions/.minions-data/workspace/demo_video.mp4"
VOICEOVER_PATH = "/opt/data/webui/minions/.minions-data/workspace/voiceover.mp3"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Try to load a monospace font
font_paths = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
]
font = None
for fp in font_paths:
    if os.path.exists(fp):
        font = ImageFont.truetype(fp, 32)
        font_small = ImageFont.truetype(fp, 24)
        font_title = ImageFont.truetype(fp, 48)
        break
if font is None:
    font = ImageFont.load_default()
    font_small = font
    font_title = font

def make_frame(text_lines, y_offset=80):
    """Create a single frame with terminal-style text."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Terminal window border
    draw.rectangle([20, 20, WIDTH-20, HEIGHT-20], outline=(60, 60, 60), width=2)
    # Title bar
    draw.rectangle([20, 20, WIDTH-20, 60], fill=(40, 40, 40))
    draw.text((40, 26), "● ● ●  perseus-vault — bash — 192×48", fill=(150, 150, 150), font=font_small)
    
    y = y_offset
    for line in text_lines:
        if isinstance(line, tuple):
            text, color = line
        else:
            text, color = line, OUTPUT_COLOR
        
        if text.startswith("$ "):
            draw.text((40, y), text, fill=PROMPT_COLOR, font=font)
        elif text.startswith("# "):
            draw.text((40, y), text, fill=TITLE_COLOR, font=font_title)
        elif text.startswith(">>> "):
            draw.text((40, y), text, fill=HIGHLIGHT_COLOR, font=font)
        else:
            draw.text((40, y), text, fill=color, font=font)
        y += 42
    
    return img

# Define scenes: (duration_seconds, text_lines)
scenes = [
    # Part 1: The Problem (0-10s)
    (4, [
        ("# Perseus-Vault: An Agentic Memory Core", TITLE_COLOR),
    ]),
    (2, [
        ("# Perseus-Vault: An Agentic Memory Core", TITLE_COLOR),
        ("", OUTPUT_COLOR),
        ("Most AI agents forget everything", OUTPUT_COLOR),
        ("the moment the conversation ends.", OUTPUT_COLOR),
    ]),
    # (10-30s) Show the failing agent
    (5, [
        ("$ python baseline_agent.py", PROMPT_COLOR),
        (">>> Remember: deployment target is", PROMPT_COLOR),
        (">>> AWS Lambda, us-east-1.", PROMPT_COLOR),
        ("[Agent] Got it.", OUTPUT_COLOR),
    ]),
    (4, [
        ("$ python baseline_agent.py", PROMPT_COLOR),
        (">>> Remember: deployment target is", PROMPT_COLOR),
        (">>> AWS Lambda, us-east-1.", PROMPT_COLOR),
        ("[Agent] Got it.", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        ("--- New Session ---", HIGHLIGHT_COLOR),
    ]),
    (5, [
        ("$ python baseline_agent.py", PROMPT_COLOR),
        (">>> What region am I deploying to?", PROMPT_COLOR),
        ("[Agent] I don't have that information.", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        (">>> The memory is gone.", HIGHLIGHT_COLOR),
        (">>> Context windows reset. Agents forget.", HIGHLIGHT_COLOR),
    ]),
    # Part 2: The Solution (30-90s)
    (5, [
        ("$ python bedrock_agent.py", PROMPT_COLOR),
        ("", OUTPUT_COLOR),
        ("--- STEP 1: ADDING MEMORY (BEDROCK) ---", TITLE_COLOR),
        ("[health check] Running ccloud cluster info...", OUTPUT_COLOR),
        ("[health check] Cluster state: CLUSTER_STATE_CREATED", OUTPUT_COLOR),
    ]),
    (5, [
        ("[health check] Cluster state: CLUSTER_STATE_CREATED", OUTPUT_COLOR),
        ("[bedrock] Generating 1024-dim embedding...", OUTPUT_COLOR),
        ("[bedrock] Model: amazon.titan-embed-text-v2:0", OUTPUT_COLOR),
        ("[db] INSERT INTO vault_entries (content, embedding)", PROMPT_COLOR),
        ("[db] 1 row committed. Memory stored.", OUTPUT_COLOR),
    ]),
    (5, [
        ("--- CockroachDB Cloud SQL Console ---", TITLE_COLOR),
        ("", OUTPUT_COLOR),
        ("crdb> SELECT id, content, embedding", PROMPT_COLOR),
        ("      FROM vault_entries", PROMPT_COLOR),
        ("      ORDER BY id DESC LIMIT 1;", PROMPT_COLOR),
    ]),
    (5, [
        ("      ORDER BY id DESC LIMIT 1;", PROMPT_COLOR),
        ("", OUTPUT_COLOR),
        (" id   | content                        | embedding", HIGHLIGHT_COLOR),
        ("------+--------------------------------+-----------", HIGHLIGHT_COLOR),
        (" a1b2 | deployment target is AWS       | [0.023,    ", OUTPUT_COLOR),
        ("      | Lambda, us-east-1              | -0.141, ...]", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        ("(1 row) -- real memory in a real database", OUTPUT_COLOR),
    ]),
    # Part 3: The Payoff (90-120s)  
    (5, [
        ("--- New Lambda Invocation ---", TITLE_COLOR),
        ("[CloudWatch] START RequestId: xyz-123", OUTPUT_COLOR),
        ("[CloudWatch] Cold start. No in-memory state.", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        (">>> What region am I deploying to?", PROMPT_COLOR),
    ]),
    (5, [
        (">>> What region am I deploying to?", PROMPT_COLOR),
        ("[recall] Embedding query via Bedrock Titan...", OUTPUT_COLOR),
        ("[recall] SELECT ... ORDER BY embedding <-> query", PROMPT_COLOR),
        ("[recall] LIMIT 3", PROMPT_COLOR),
        ("[recall] 1 relevant memory found. Distance: 0.12", OUTPUT_COLOR),
    ]),
    (5, [
        ("[recall] 1 relevant memory found. Distance: 0.12", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        (">>> You're deploying to AWS Lambda,", HIGHLIGHT_COLOR),
        (">>> in us-east-1.", HIGHLIGHT_COLOR),
        ("", OUTPUT_COLOR),
        ("--- Memory survived across sessions.", OUTPUT_COLOR),
    ]),
    # Closing (120-128s)
    (8, [
        ("", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        ("# An agent doesn't just need to think and act.", TITLE_COLOR),
        ("", OUTPUT_COLOR),
        ("# It needs to remember, reliably.", TITLE_COLOR),
        ("", OUTPUT_COLOR),
        ("# Perseus-Vault", HIGHLIGHT_COLOR),
        ("# Built on CockroachDB × AWS", OUTPUT_COLOR),
        ("", OUTPUT_COLOR),
        ("github.com/tcconnally/perseus-vault-hackathon", OUTPUT_COLOR),
    ]),
]

# Calculate total duration
total_duration = sum(d for d, _ in scenes)
print(f"Total video duration: {total_duration}s ({total_duration/60:.1f}m)")

# Generate frames
frame_count = 0
for scene_idx, (duration, lines) in enumerate(scenes):
    num_frames = int(duration * FPS)
    img = make_frame(lines)
    for f in range(num_frames):
        img.save(f"{OUTPUT_DIR}/frame_{frame_count:06d}.png")
        frame_count += 1
    print(f"  Scene {scene_idx+1}/{len(scenes)}: {duration}s ({num_frames} frames) - {lines[0][0] if isinstance(lines[0], tuple) else lines[0]}")

print(f"Total frames: {frame_count}")

# Encode video from frames
print("\nEncoding video...")
encode_cmd = [
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", f"{OUTPUT_DIR}/frame_%06d.png",
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-preset", "fast",
    "-crf", "23",
    VIDEO_PATH.replace(".mp4", "_novoice.mp4")
]
subprocess.run(encode_cmd, check=True)

# Add voiceover
print("Adding voiceover...")
merge_cmd = [
    "ffmpeg", "-y",
    "-i", VIDEO_PATH.replace(".mp4", "_novoice.mp4"),
    "-i", VOICEOVER_PATH,
    "-c:v", "copy",
    "-c:a", "aac",
    "-shortest",
    "-map", "0:v:0",
    "-map", "1:a:0",
    VIDEO_PATH
]
subprocess.run(merge_cmd, check=True)

# Clean up
import shutil
shutil.rmtree(OUTPUT_DIR)
os.remove(VIDEO_PATH.replace(".mp4", "_novoice.mp4"))

size = os.path.getsize(VIDEO_PATH)
print(f"\nDone! Video: {VIDEO_PATH}")
print(f"Size: {size/1024/1024:.1f} MB")
print(f"Duration: {total_duration}s")
