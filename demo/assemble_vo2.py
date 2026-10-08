#!/usr/bin/env python3
"""Gavel demo video v2: visuals synced to the narration, step by step.

Each narration paragraph gets a video segment; gold highlight boxes pop onto
the exact UI element at the moment the narrator names it.

Segments:
  p1 (concept)      -> animated title card, lines appear as narrated
  p2 (filing)       -> filing footage + freeze, highlights on form fields
  p3 (deliberation) -> transcript footage, justice cards highlighted by name
  p4 (rounds/votes) -> transcript footage, phase pulses on transcript panel
  p5 (verdict)      -> verdict footage + freeze, highlights on ruling/award/hash
  p6 (outro)        -> outro card
"""
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RAW = HERE / "gavel-trial-chapters.webm"
OUT = HERE / "gavel-demo-vo2.mp4"
W, H = 1280, 720
GOLD = "0xC9A227@0.95"

# Paragraph durations (measured from per-paragraph TTS renders)
DUR = {1: 12.3, 2: 17.2, 3: 27.4, 4: 15.4, 5: 20.9, 6: 6.8}

# Raw footage chapters (from phases.json)
SUBMIT, VERDICT, END = 11.64, 95.39, 109.49


def words(n):
    return open(HERE / f"narr/p{n}.txt").read().split()


def cue(n, phrase):
    """Estimate the time (s) a phrase starts in paragraph n, by word position."""
    ws = words(n)
    pl = phrase.lower().split()
    for i in range(len(ws) - len(pl) + 1):
        if [w.strip(".,:;!?").lower() for w in ws[i:i + len(pl)]] == pl:
            return round(i / len(ws) * DUR[n], 2)
    raise ValueError(f"phrase not found: {phrase!r} in p{n}")


def font(size, bold=True):
    p = f"/usr/share/fonts/truetype/dejavu/DejaVuSans-{('Bold' if bold else '')}.ttf".replace("-.t", ".t")
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


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


def box(x, y, w, h, t1, t2, t=4):
    return (f"drawbox=x={x}:y={y}:w={w}:h={h}:color={GOLD}:t={t}"
            f":enable='between(t,{t1},{t2})'")


def seg_filter(src, vf_chain, dur):
    vf = ",".join(vf_chain + ["format=yuv420p"])
    return vf


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    tmp = HERE / "asm2"
    tmp.mkdir(exist_ok=True)
    cards = HERE / "cards2"
    cards.mkdir(exist_ok=True)

    # ---- seg1: animated title card ----
    concept = [
        "Disputants lock funds in escrow.",
        "A panel of AI justices debates the evidence \u2014 in public.",
        "The ruling is hashed on-chain. The escrow auto-pays the winner.",
    ]
    t1, t2, t3 = cue(1, "Disputants lock"), cue(1, "A panel"), cue(1, "The ruling")
    bounds = [(0, t1), (t1, t2), (t2, t3), (t3, DUR[1])]
    card_paths = []
    for i in range(4):
        p = cards / f"title{i}.png"
        card("The AI Small-Claims Court", concept[:i]).save(p)
        card_paths.append(p)
    for i, (a, b) in enumerate(bounds):
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(card_paths[i]),
             "-t", f"{b - a:.2f}", "-vf", "scale=1280:720,format=yuv420p",
             str(tmp / f"s1_{i}.mp4")])
    run(["ffmpeg", "-y", "-v", "error",
         "-i", str(tmp / "s1_0.mp4"), "-i", str(tmp / "s1_1.mp4"),
         "-i", str(tmp / "s1_2.mp4"), "-i", str(tmp / "s1_3.mp4"),
         "-filter_complex", "[0][1][2][3]concat=n=4:v=1:a=0",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg1.mp4")])

    # ---- seg2: filing (footage 0..SUBMIT, freeze to fill) ----
    pad2 = DUR[2] - SUBMIT
    c_load = cue(2, "files her case")
    c_sow = cue(2, "signed statement")
    vf2 = [
        box(140, 358, 1000, 62, c_load, c_load + 2.5),          # Load demo dispute btn
        box(140, 640, 1000, 80, c_sow, c_sow + 3.2),            # claim description
        f"tpad=stop_mode=clone:stop_duration={pad2:.2f}",
    ]
    run(["ffmpeg", "-y", "-v", "error", "-ss", "0", "-t", f"{SUBMIT:.2f}",
         "-i", str(RAW), "-vf", seg_filter(None, vf2, DUR[2]),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg2.mp4")])

    # ---- seg3: deliberation (SUBMIT..SUBMIT+27.4), justice highlights ----
    s3 = SUBMIT
    c_text = cue(3, "The Textualist")
    c_cons = cue(3, "The Consumer Advocate")
    c_prec = cue(3, "The Precedent Analyst")
    c_pub = cue(3, "public transcript")
    vf3 = [
        box(90, 300, 345, 250, c_text, c_text + 3.0),            # Textualist card
        box(445, 300, 350, 250, c_cons, c_cons + 3.0),          # Consumer Advocate
        box(805, 300, 350, 250, c_prec, c_prec + 3.0),          # Precedent Analyst
        box(90, 560, 1070, 160, c_pub, DUR[3]),                 # transcript panel
    ]
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s3:.2f}", "-t", f"{DUR[3]:.2f}",
         "-i", str(RAW), "-vf", seg_filter(None, vf3, DUR[3]),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg3.mp4")])

    # ---- seg4: deliberation cont. (SUBMIT+27.4 .. +42.8), phase pulses ----
    s4 = SUBMIT + DUR[3]
    c_open = cue(4, "Openings")
    c_reb = cue(4, "Rebuttals")
    c_close = cue(4, "Closing positions")
    c_vote = cue(4, "each justice votes")
    vf4 = [
        box(90, 560, 1070, 160, c_open, c_open + 1.6),
        box(90, 560, 1070, 160, c_reb, c_reb + 1.6),
        box(90, 560, 1070, 160, c_close, c_close + 1.6),
        box(90, 300, 1060, 250, c_vote, c_vote + 2.2),          # the bench
    ]
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s4:.2f}", "-t", f"{DUR[4]:.2f}",
         "-i", str(RAW), "-vf", seg_filter(None, vf4, DUR[4]),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg4.mp4")])

    # ---- seg5: verdict (VERDICT..END, freeze to fill) ----
    pad5 = DUR[5] - (END - VERDICT)
    c_rules = cue(5, "rules for Maya")
    c_award = cue(5, "Awarded")
    c_hash = cue(5, "hashed with")
    vf5 = [
        box(210, 408, 860, 62, c_rules, c_rules + 3.0),         # RULED FOR THE CLAIMANT
        box(545, 470, 225, 45, c_award, c_award + 3.0),         # Awarded $500
        box(145, 530, 990, 190, c_hash, c_hash + 4.0),           # reasoning/hash panel
        f"tpad=stop_mode=clone:stop_duration={pad5:.2f}",
    ]
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{VERDICT:.2f}",
         "-t", f"{END - VERDICT:.2f}", "-i", str(RAW),
         "-vf", seg_filter(None, vf5, DUR[5]),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg5.mp4")])

    # ---- seg6: outro card ----
    card("Built for BLI Legal Tech Hackathon 2",
         ["Live demo trial: Maya Chen v. Brightline Media \u2014 $500 USDC.",
          "github.com/QuincyGB/gavel"]).save(cards / "outro.png")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(cards / "outro.png"),
         "-t", f"{DUR[6]:.2f}", "-vf", "scale=1280:720,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         str(tmp / "seg6.mp4")])

    # ---- concat video ----
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file 'seg{i}.mp4'\n" for i in range(1, 7)))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(tmp / "video.mp4")])

    # ---- concat audio with small gaps ----
    aud = tmp / "alist.txt"
    alines = []
    for i in range(1, 7):
        alines.append(f"file '../narr/p{i}.mp3'")
    aud.write_text("\n".join(alines) + "\n")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(aud), "-c", "copy", str(tmp / "audio.mp3")])

    # ---- mux ----
    run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp / "video.mp4"),
         "-i", str(tmp / "audio.mp3"),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-af", "apad,atrim=0:100.5",
         "-shortest", str(OUT)])
    print("wrote", OUT, f"{OUT.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
