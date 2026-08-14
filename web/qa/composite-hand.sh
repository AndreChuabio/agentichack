#!/bin/bash
# composite-hand.sh -- matte a real Merit screenshot into a green-screen phone
# plate. The technique from the Loop Handoff, recreated as a committed,
# parametric script (the mini's original is untracked and its measured values
# were plate-specific).
#
#   qa/composite-hand.sh <plate.mp4> <ui.png> <out.mp4> \
#       [key] [similarity] [panel_wxh] [panel_xy]
#
#   qa/composite-hand.sh --probe <plate.mp4> <out_dir>
#       Extracts frames at 0s/2s/4s so the green screen box can be measured
#       before compositing. Measure, then run the composite with real values.
#
# HOW THE MATTE WORKS (the part that is easy to get backwards): the green is
# turned into transparency on a COPY of the plate, and that copy is layered
# over the UI panel. The person is never keyed directly -- keying the person
# and putting the UI behind them punches holes in skin wherever it nears the
# key color. The UI shows through only where the phone screen was green, so it
# inherits the phone's outline, tilt, and finger occlusion for free.
#
# THE UI PANEL: the screenshot renders at its true width, letterboxed inside an
# oversized dark panel positioned under the phone. Scaling it to fill instead
# pushes the page margin outside the phone and shaves the first characters off
# every line (paid-for lesson, verbatim from the handoff).
#
# ffmpeg notes that cost an evening each, do not remove:
#   - colorkey NEEDS format=rgba immediately before it, or the filtergraph
#     silently produces no frames and the encoder dies with -22.
#   - this ffmpeg may lack drawtext (no freetype); compose type in a browser.

set -euo pipefail

if [ "${1:-}" = "--probe" ]; then
  plate="${2:?plate required}"; outdir="${3:?out dir required}"
  mkdir -p "$outdir"
  for t in 0 2 4; do
    ffmpeg -hide_banner -loglevel error -ss "$t" -i "$plate" -frames:v 1 \
      "$outdir/probe-${t}s.png" -y
  done
  echo "probe frames in $outdir -- measure the green box, then composite"
  exit 0
fi

plate="${1:?plate.mp4 required}"
ui="${2:?ui.png required}"
out="${3:?out.mp4 required}"
key="${4:-0x10FF22}"
similarity="${5:-0.30}"
panel_wxh="${6:-330x650}"   # oversized dark panel the UI letterboxes into
panel_xy="${7:-112,460}"    # panel top-left in plate coordinates

panel_w="${panel_wxh%x*}"; panel_h="${panel_wxh#*x}"
panel_x="${panel_xy%,*}";  panel_y="${panel_xy#*,}"

# Layering, bottom to top:
#   [base]  untouched plate (the person, room, phone body)
#   [panel] dark panel + UI at true width, letterboxed, placed under the phone
#   [keyed] the plate again with green turned transparent -- everything except
#           the screen is opaque, so it covers the panel's overshoot exactly
ffmpeg -hide_banner -loglevel error \
  -i "$plate" -i "$ui" \
  -filter_complex "\
    [0:v]split=2[base][for_key]; \
    [1:v]scale=${panel_w}:-1[uiw]; \
    color=c=0x111111:s=${panel_wxh}[bg]; \
    [bg][uiw]overlay=(W-w)/2:(H-h)/2:shortest=1[panel]; \
    [base][panel]overlay=${panel_x}:${panel_y}[with_ui]; \
    [for_key]format=rgba,colorkey=${key}:${similarity}:0.05[keyed]; \
    [with_ui][keyed]overlay=0:0[outv]" \
  -map "[outv]" -map "0:a?" \
  -c:v libx264 -pix_fmt yuv420p -crf 19 -preset medium -c:a copy \
  "$out" -y

echo "composited: $out"
