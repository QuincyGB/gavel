#!/usr/bin/env python3
"""Assemble the Gavel demo video: title card + trial recording + outro card.

Usage: python assemble_video.py
Reads:  gavel-trial-raw.webm
Writes: gavel-demo.mp4 (1280x720, h264)
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RAW = HERE / "gavel-trial-raw.webm"
OUT = HERE / "gavel-demo.mp4"
W, H = 1280, 720


def font(size, bold=True):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(p).exists():
            from PIL import ImageFont as IF
            return IF.truetype(p, size)
    from PIL import ImageFont as IF
    return IF.load_default()


def card(title, lines, accent="#c9a227"):
    img = Image.new("RGB", (W, H), "#14100b")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 90], fill="#1f1811")
    d.text((W // 2, 45), "GAVEL", font=font(44), fill=accent, anchor="mm")
    d.text((W // 2, 200), title, font=font(52), fill="#f5efe0", anchor="mm")
    y = 300
    for line in lines:
        d.text((W // 2, y), line, font=font(28, bold=False), fill="#cfc4ab", anchor="mm")
        y += 52
    return img


def main():
    if not RAW.exists():
        print("missing", RAW, file=sys.stderr)
        sys.exit(1)

    cards = HERE / "cards"
    cards.mkdir(exist_ok=True)
    card(
        "The AI Small-Claims Court",
        [
            "Disputants lock funds in escrow.",
            "A panel of AI justices debates the evidence — in public.",
            "The ruling is hashed on-chain. The escrow auto-pays the winner.",
        ],
    ).save(cards / "title.png")
    card(
        "Built for BLI Legal Tech Hackathon 2",
        [
            "Live demo trial: Maya Chen v. Brightline Media Ltd. — $500 USDC.",
            "github.com/QuincyGB/gavel",
        ],
    ).save(cards / "outro.png")

    # Card clips (4s each) + raw recording, then concat.
    tmp = HERE / "asm"
    tmp.mkdir(exist_ok=True)
    for name in ["title", "outro"]:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(cards / f"{name}.png"),
             "-t", "4", "-vf", "scale=1280:720,format=yuv420p", str(tmp / f"{name}.mp4")],
            check=True,
        )
    # Normalize the raw recording to mp4/h264.
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(RAW),
         "-vf", "scale=1280:720,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", str(tmp / "trial.mp4")],
        check=True,
    )
    # Concat.
    lst = tmp / "list.txt"
    lst.write_text("file 'title.mp4'\nfile 'trial.mp4'\nfile 'outro.mp4'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(OUT)],
        check=True,
    )
    print("wrote", OUT, f"{OUT.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
