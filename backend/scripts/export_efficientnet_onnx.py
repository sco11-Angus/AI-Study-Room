"""将 EfficientNet-B0 FF++ PyTorch 模型导出为 ONNX。

来源: Xicor9/efficientnet-b0-ffpp-c23 (HuggingFace, MIT)
AUC: 0.933 (frame-level), 输入: 224×224 RGB
"""
import torch
import torch.nn as nn
from torchvision import models


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    pth_path = "model_weights/efficientnet_b0_ffpp_c23.pth"
    onnx_path = "model_weights/efficientnet_b0_ffpp_c23.onnx"

    # 重建模型架构 (与 HuggingFace 模型卡一致)
    model = models.efficientnet_b0(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 2)

    state_dict = torch.load(pth_path, map_location=device)
    model.load_state_dict(state_dict)
    model.to(device)
    model.eval()

    # 导出 ONNX
    dummy = torch.randn(1, 3, 224, 224).to(device)
    torch.onnx.export(
        model,
        dummy,
        onnx_path,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=13,
    )
    print(f"[export] 模型已导出: {onnx_path}")

    # 验证 ONNX 推理
    import onnxruntime as ort
    import numpy as np

    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    print(f"[verify] ONNX input: {inp.name}, shape={inp.shape}, dtype={inp.type}")
    out = session.get_outputs()[0]
    print(f"[verify] ONNX output: {out.name}, shape={out.shape}, dtype={out.type}")

    # 对比 PyTorch vs ONNX 输出
    dummy_np = dummy.cpu().numpy()
    onnx_out = session.run(None, {"input": dummy_np})[0]
    with torch.no_grad():
        torch_out = model(dummy).cpu().numpy()
    diff = np.abs(onnx_out - torch_out).max()
    print(f"[verify] PyTorch vs ONNX 最大误差: {diff:.6f}")

    # softmax → fake概率
    logits = onnx_out
    exp_logits = np.exp(logits - np.max(logits))
    probs = exp_logits / np.sum(exp_logits)
    print(f"[verify] 随机输入: fake_prob={probs[0,1]:.4f}, real_prob={probs[0,0]:.4f}")


if __name__ == "__main__":
    main()
