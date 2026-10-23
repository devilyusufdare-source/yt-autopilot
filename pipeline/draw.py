"""Local illustration engine for the "drawn" visual style: Stable Diffusion Turbo on the runner's CPU.

No service, no key, no limit. First use downloads the model (~2.5 GB, cached by the workflow); a
512x896 picture takes about 15-40 s on a GitHub runner. Used by pipeline/visuals.py when
`visuals.draw_engine` is "local" (default). Install: pip install -r requirements-draw.txt
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL_ID = os.environ.get("DRAW_MODEL", "stabilityai/sd-turbo")
_pipe = None


def available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _pipeline():
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import AutoPipelineForText2Image
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    kwargs = {"torch_dtype": torch.float32}
    try:
        _pipe = AutoPipelineForText2Image.from_pretrained(MODEL_ID, safety_checker=None, **kwargs)
    except Exception:  # noqa: BLE001  (some repos only ship fp16 weights)
        _pipe = AutoPipelineForText2Image.from_pretrained(MODEL_ID, safety_checker=None, variant="fp16", torch_dtype=torch.float32)
    _pipe.set_progress_bar_config(disable=True)
    _pipe.to("cpu")
    return _pipe


def draw(prompt: str, out: Path, width: int = 512, height: int = 896, seed: int = 0, steps: int = 2) -> Path:
    """Render one picture to `out` (JPEG). Width/height multiples of 64."""
    import torch
    pipe = _pipeline()
    g = torch.Generator(device="cpu").manual_seed(int(seed) % (2 ** 31))
    image = pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0, width=width, height=height, generator=g).images[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out, "JPEG", quality=92)
    return out


if __name__ == "__main__":
    import sys
    import time
    p = " ".join(sys.argv[1:]) or "a pelican diving into the sea, hand-drawn ink illustration on cream paper, light watercolor wash"
    t = time.time()
    print(draw(p, Path("output/draw-test.jpg")), f"{time.time() - t:.0f}s")
