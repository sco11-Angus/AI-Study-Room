"""Verify torch-vggish-yamnet YAMNet model availability.

torch-vggish-yamnet auto-downloads pretrained weights (~14MB) on first use.
Run this script to trigger the download and confirm everything works.
"""
import sys

print("[check_yamnet] Verifying torch-vggish-yamnet YAMNet...")
try:
    import torch
    from torch_vggish_yamnet import yamnet
    from torch_vggish_yamnet.input_proc import WaveformToInput

    model = yamnet.yamnet(pretrained=True)
    model.eval()
    converter = WaveformToInput()
    classes = yamnet.CLASSES

    print(f"[check_yamnet] Model loaded! {len(classes)} classes")

    # Warm-up inference
    dummy = torch.zeros(16000, dtype=torch.float32)
    mel = converter(dummy, 16000)
    with torch.no_grad():
        emb, scores = model(mel)
    print(f"[check_yamnet] Inference OK — embeddings {list(emb.shape)}, scores {list(scores.shape)}")

    # List abnormal classes
    abnormal = ["Scream", "Shout", "Yell", "Crying", "Glass",
                 "Gunshot", "Explosion", "Thump", "Shatter", "Bang",
                 "Crash", "Groan", "Howl"]
    class_lower = [c.lower() for c in classes]
    print(f"\n[check_yamnet] Abnormal sound classes found:")
    for cls_name in abnormal:
        key = cls_name.lower()
        for cn in classes:
            if key == cn.lower() or key in cn.lower():
                print(f"  - {cn}")
                break

    print(f"\n[check_yamnet] Done — YAMNet ready.")
except ImportError as e:
    print(f"[check_yamnet] ERROR: {e}")
    print("  Install: pip install torch-vggish-yamnet")
    sys.exit(1)
