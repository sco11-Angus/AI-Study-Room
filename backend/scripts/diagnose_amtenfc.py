#!/usr/bin/env python
"""Diagnose AMTEN-FC PyTorch + ONNX model outputs.

Tests both models with random noise, zeros, ones, and a real image to check
whether the sigmoid output is stuck at 1.0 (a common sign of weight collapse
or preprocessing bugs).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import cv2
from app.detectors.antispoof_model import AMTENFC, block_dct
import torch


# ---------------------------------------------------------------------------
# Paths (weights live in backend/model_weights, script is in backend/scripts)
# ---------------------------------------------------------------------------
BASE = os.path.join(os.path.dirname(__file__), "..")
PTH_PATH = os.path.join(BASE, "model_weights", "best_amtenfc.pth")
ONNX_PATH = os.path.join(BASE, "model_weights", "antispoof_amtenet_vanet.onnx")

INPUT_SIZE = 128                # RGB spatial size
DCT_H = DCT_W = 63              # block_dct(128, bs=4, stride=2) → 63×63


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_pytorch_model(path: str):
    """Load AMTENFC PyTorch model from state dict."""
    print(f"[PyTorch] Loading {os.path.basename(path)} ...")
    model = AMTENFC(num_classes=1)
    state = torch.load(path, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    print("[PyTorch] Loaded OK.")
    return model


def load_onnx_session(path: str):
    """Load ONNX model via onnxruntime."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("[ONNX] onnxruntime not installed — skipping.")
        return None

    if not os.path.exists(path):
        print(f"[ONNX] File not found: {path}")
        return None

    print(f"[ONNX] Loading {os.path.basename(path)} ...")
    session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    inames = [inp.name for inp in session.get_inputs()]
    print(f"[ONNX] Loaded OK.  Inputs: {inames}")
    return session, inames


def infer_pytorch(model, rgb_nchw, dct_nchw):
    """Run PyTorch model; returns (logit, sigmoid_score)."""
    rgbt = torch.from_numpy(rgb_nchw).float()
    dctt = torch.from_numpy(dct_nchw).float()
    with torch.no_grad():
        logits = model(rgbt, dctt)                  # (1, 1)
        score = torch.sigmoid(logits).item()
    return float(logits.item()), float(score)


def infer_onnx(session, inames, rgb_nchw, dct_nchw):
    """Run ONNX model; returns (logit, sigmoid_score)."""
    feeds = {inames[0]: rgb_nchw.astype(np.float32),
             inames[1]: dct_nchw.astype(np.float32)}
    outputs = session.run(None, feeds)
    logit = float(outputs[0][0, 0])
    score = 1.0 / (1.0 + np.exp(-logit))
    return logit, float(np.clip(score, 0.0, 1.0))


def _cv2_imread_unicode(path: str):
    """cv2.imread with Unicode-path support for Windows."""
    try:
        bgr = cv2.imread(path)
        if bgr is not None:
            return bgr
    except Exception:
        pass
    # Fallback: read bytes via numpy then decode
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def preprocess_image(img_path: str):
    """BGR image → rgb(1,3,128,128) + dct(1,48,63,63)."""
    bgr = _cv2_imread_unicode(img_path)
    if bgr is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")
    rgb = cv2.cvtColor(cv2.resize(bgr, (INPUT_SIZE, INPUT_SIZE)),
                       cv2.COLOR_BGR2RGB)
    blob = rgb.astype(np.float32) / 255.0              # [0, 1]
    rgb_nchw = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]  # (1,3,128,128)

    dct_feat = block_dct(rgb, block_size=4, stride=2)  # (48,63,63)
    dct_nchw = dct_feat[np.newaxis, ...]                # (1,48,63,63)
    return rgb_nchw, dct_nchw


def find_real_image():
    """Find a real face image (prefers test_photos, falls back to data/)."""
    candidates = [
        os.path.join(BASE, "test_photos", "2.jpg"),
        os.path.join(BASE, "test_photos", "3.jpg"),
        os.path.join(BASE, "test_photos", "4.jpg"),
        os.path.join(BASE, "test_photos", "5.jpg"),
        os.path.join(BASE, "data", "2.jpg"),
        os.path.join(BASE, "data", "3.jpg"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 72)
    print(" AMTEN-FC DIAGNOSTIC")
    print("=" * 72)

    # ---- Generate test inputs ----
    noise_rgb = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)
    noise_dct = np.zeros((1, 48, DCT_H, DCT_W), dtype=np.float32)

    zeros_rgb = np.zeros((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
    zeros_dct = np.zeros((1, 48, DCT_H, DCT_W), dtype=np.float32)

    ones_rgb  = np.ones((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
    ones_dct  = np.ones((1, 48, DCT_H, DCT_W), dtype=np.float32)

    # ------- PyTorch -------
    print("\n" + "-" * 40)
    print(" 1. PYTORCH MODEL")
    print("-" * 40)

    if not os.path.exists(PTH_PATH):
        print(f"[PyTorch] SKIP -- weight file missing: {PTH_PATH}")
        pytorch_ok = False
    else:
        model = load_pytorch_model(PTH_PATH)
        pytorch_ok = True

        tests = [
            ("random noise (+/-1)",  noise_rgb, noise_dct),
            ("all zeros",          zeros_rgb, zeros_dct),
            ("all ones",           ones_rgb,  ones_dct),
        ]

        for label, rgb_blob, dct_blob in tests:
            logit, score = infer_pytorch(model, rgb_blob, dct_blob)
            print(f"  {label:22s}  logit={logit:+10.6f}  sigmoid={score:.6f}")

        # Real image
        real_path = find_real_image()
        if real_path:
            print(f"\n  real image: {os.path.relpath(real_path, BASE)}")
            rr, dd = preprocess_image(real_path)
            logit, score = infer_pytorch(model, rr, dd)
            print(f"  {'(real face)':22s}  logit={logit:+10.6f}  sigmoid={score:.6f}")
        else:
            print("\n  (no real image found — skipping)")

        # Variation check
        all_scores = []
        for label, rgb_blob, dct_blob in tests:
            _, s = infer_pytorch(model, rgb_blob, dct_blob)
            all_scores.append(s)
        if real_path:
            _, s = infer_pytorch(model, rr, dd)
            all_scores.append(s)

        unique = set(round(s, 6) for s in all_scores)
        if len(unique) == 1:
            print(f"\n  !! WARNING: All PyTorch sigmoid scores identical: {list(unique)}")
        else:
            print(f"\n  [OK] PyTorch scores vary across inputs (unique values: {sorted(unique)})")

    # ------- ONNX -------
    print("\n" + "-" * 40)
    print(" 2. ONNX MODEL")
    print("-" * 40)

    onnx_ok = False
    if not os.path.exists(ONNX_PATH):
        print(f"[ONNX] SKIP -- weight file missing: {ONNX_PATH}")
    else:
        result = load_onnx_session(ONNX_PATH)
        if result is not None:
            session, inames = result
            onnx_ok = True

            tests = [
                ("random noise (+/-1)",  noise_rgb, noise_dct),
                ("all zeros",          zeros_rgb, zeros_dct),
                ("all ones",           ones_rgb,  ones_dct),
            ]

            for label, rgb_blob, dct_blob in tests:
                logit, score = infer_onnx(session, inames, rgb_blob, dct_blob)
                print(f"  {label:22s}  logit={logit:+10.6f}  sigmoid={score:.6f}")

            if real_path:
                print(f"\n  real image: {os.path.relpath(real_path, BASE)}")
                rr, dd = preprocess_image(real_path)
                logit, score = infer_onnx(session, inames, rr, dd)
                print(f"  {'(real face)':22s}  logit={logit:+10.6f}  sigmoid={score:.6f}")

            all_scores = []
            for label, rgb_blob, dct_blob in tests:
                _, s = infer_onnx(session, inames, rgb_blob, dct_blob)
                all_scores.append(s)
            if real_path:
                _, s = infer_onnx(session, inames, rr, dd)
                all_scores.append(s)

            unique = set(round(s, 6) for s in all_scores)
            if len(unique) == 1:
                print(f"\n  !! WARNING: All ONNX sigmoid scores identical: {list(unique)}")
            else:
                print(f"\n  [OK] ONNX scores vary across inputs (unique values: {sorted(unique)})")

    # ------- Summary -------
    print("\n" + "=" * 72)
    print(" SUMMARY")
    print("=" * 72)
    print(f"  PyTorch model: {'available' if pytorch_ok else 'MISSING'}")
    print(f"  ONNX model:    {'available' if onnx_ok else 'MISSING'}")
    print()


if __name__ == "__main__":
    main()
