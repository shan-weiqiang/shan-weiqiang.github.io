#!/usr/bin/env python3
"""Render .mmd to trimmed .png via headless Chromium + Mermaid CDN."""

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

CHROMIUM = "/usr/bin/chromium-browser"
PADDING = 12

WIDE_MMD = {
    "python_c_ext_three_approaches.mmd",
    "python_c_ext_ros2_bindings_publish_flow.mmd",
    "python_c_ext_pybind11_call_flow.mmd",
}
TALL_MMD = {
    "python_c_ext_ros2_bindings_architecture.mmd",
    "python_c_ext_pybind11_internals.mmd",
    "python_c_ext_extension_vs_binding_layers.mmd",
    "python_c_ext_marshalling_core.mmd",
    "python_c_ext_stack_layers.mmd",
}
MEDIUM_MMD = {
    "python_c_ext_cffi_modes.mmd",
    "python_c_ext_series_concept_map.mmd",
}


def trim_white(img: Image.Image, padding: int = PADDING) -> Image.Image:
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if not bbox:
        return img
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(img.width, bbox[2] + padding)
    bottom = min(img.height, bbox[3] + padding)
    return img.crop((left, top, right, bottom))


def window_size(mmd_name: str) -> tuple[int, int]:
    if mmd_name in TALL_MMD:
        return 2000, 1800
    if mmd_name in WIDE_MMD:
        return 2800, 900
    if mmd_name in MEDIUM_MMD:
        return 1800, 900
    return 1200, 900


def build_page(mmd: str) -> str:
    mmd_js = json.dumps(mmd)
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  html, body {{ margin: 0; padding: 8px; background: #fff; }}
</style>
</head><body>
<div id="mermaid" class="mermaid"></div>
<script>
  mermaid.initialize({{ startOnLoad: false, theme: "default" }});
  document.getElementById("mermaid").textContent = {mmd_js};
  mermaid.run();
</script>
</body></html>"""


def render_mmd(mmd_path: Path, png_path: Path) -> None:
    mmd = mmd_path.read_text()
    html_path = mmd_path.with_suffix(".render.html")
    html_path.write_text(build_page(mmd))

    raw_png = png_path.with_suffix(".raw.png")
    w, h = window_size(mmd_path.name)
    try:
        subprocess.run(
            [
                CHROMIUM,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                "--virtual-time-budget=30000",
                f"--window-size={w},{h}",
                f"--screenshot={raw_png}",
                f"file://{html_path.resolve()}",
            ],
            check=True,
            capture_output=True,
        )
        img = Image.open(raw_png).convert("RGB")
        trimmed = trim_white(img)
        trimmed.save(png_path, optimize=True)
        print(
            f"{png_path.name}: {trimmed.width}x{trimmed.height} "
            f"(canvas {img.width}x{img.height})"
        )
    finally:
        html_path.unlink(missing_ok=True)
        raw_png.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mmd", nargs="*", help=".mmd files")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    names = args.mmd or [
        "python_c_ext_ctypes_call_flow.mmd",
        "python_c_ext_cffi_modes.mmd",
        "python_c_ext_three_approaches.mmd",
    ]
    for name in names:
        render_mmd(here / name, here / name.replace(".mmd", ".png"))


if __name__ == "__main__":
    main()
