"""导出 AMTENFC 双输入模型为 ONNX 格式。

对齐 shreyash1706/Solving-Deepfakes-with-Traces-Frequency-and-Attention。
输入: (rgb: [1,3,128,128], dct: [1,48,63,63])
输出: logits [1, 1] → sigmoid → real_score

用法：
    python backend/scripts/export_antispoof_onnx.py [--weights model_weights/best_amtenfc.pth]

输出：
    model_weights/antispoof_amtenet_vanet.onnx
"""
from __future__ import annotations

import argparse
import os
import sys

# 将 backend 加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import torch
import torch.nn as nn


def export_onnx(model: nn.Module, onnx_path: str):
    """将双输入 AMTENFC 模型导出为 ONNX 格式。

    Args:
        model: AMTENFC 实例
        onnx_path: 输出 ONNX 文件路径
    """
    model.eval()
    dummy_rgb = torch.randn(1, 3, 128, 128)
    dummy_dct = torch.randn(1, 48, 63, 63)

    torch.onnx.export(
        model,
        (dummy_rgb, dummy_dct),
        onnx_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["rgb", "dct"],
        output_names=["logits"],
        dynamic_axes={
            "rgb": {0: "batch_size"},
            "dct": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
        verbose=False,
    )
    print(f"[export] ONNX 模型已导出: {onnx_path}")

    # 验证 ONNX 模型
    try:
        import onnx
        onnx_model = onnx.load(onnx_path)
        onnx.checker.check_model(onnx_model)
        print("[export] ONNX 模型验证通过")
        # 打印输入输出信息
        for inp in onnx_model.graph.input:
            shape = [d.dim_value for d in inp.type.tensor_type.shape.dim]
            print(f"  输入: {inp.name} {shape}")
        for out in onnx_model.graph.output:
            shape = [d.dim_value for d in out.type.tensor_type.shape.dim]
            print(f"  输出: {out.name} {shape}")
    except ImportError:
        print("[export] (跳过 onnx 库验证，未安装 onnx 包)")
    except Exception as e:
        print(f"[export] ONNX 验证警告: {e}")

    # 用 onnxruntime 做推理验证
    try:
        import onnxruntime as ort
        import numpy as np
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        rgb_in = np.random.randn(1, 3, 128, 128).astype(np.float32)
        dct_in = np.random.randn(1, 48, 63, 63).astype(np.float32)
        out = session.run(None, {"rgb": rgb_in, "dct": dct_in})
        print(f"[export] onnxruntime 推理验证通过, 输出 shape: {out[0].shape}")
    except ImportError:
        print("[export] (跳过 onnxruntime 推理验证，未安装)")
    except Exception as e:
        print(f"[export] onnxruntime 推理验证失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="导出 AMTENFC 双输入模型为 ONNX")
    parser.add_argument(
        "--weights",
        type=str,
        default=None,
        help="预训练 .pth 权重文件路径（可选，不提供则随机初始化导出）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出 ONNX 文件路径（默认: model_weights/antispoof_amtenet_vanet.onnx）",
    )
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    weights_dir = os.path.join(project_root, "model_weights")
    os.makedirs(weights_dir, exist_ok=True)

    onnx_path = args.output or os.path.join(weights_dir, "antispoof_amtenet_vanet.onnx")

    # 导入模型定义
    from app.detectors.antispoof_model import AMTENFC

    print("[export] 构建 AMTENFC 模型 ...")
    model = AMTENFC(num_classes=1)

    # 加载预训练权重
    if args.weights:
        weights_path = args.weights
    else:
        weights_path = os.path.join(weights_dir, "best_amtenfc.pth")

    if os.path.exists(weights_path):
        print(f"[export] 加载预训练权重: {weights_path}")
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        # 兼容 DataParallel 或直接 state_dict
        if "model_state_dict" in state:
            state = state["model_state_dict"]
        state = {k.replace("module.", ""): v for k, v in state.items()}
        missing, unexpected = model.load_state_dict(state, strict=False)
        if missing:
            print(f"[export] 缺失的 key ({len(missing)}): {missing[:5]}...")
        if unexpected:
            print(f"[export] 多余的 key ({len(unexpected)}): {unexpected[:5]}...")
        print("[export] 权重加载成功")
    else:
        print(f"[export] 未找到预训练权重 ({weights_path})")
        print("[export] WARNING: 使用随机初始化权重导出 -- 需要通过训练获得有意义的权重！")
        print("[export] 训练步骤：")
        print("  1. 准备数据集（140k Real/Fake Faces 或类似）")
        print("  2. 运行 AMTEN_freq_cbam.py 中的 train_model()")
        print("  3. 将 best_amtenfc.pth 放入 model_weights/")
        print("  4. 重新运行此脚本")

    # 计算参数量
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[export] 模型参数量: {total_params:,} (可训练: {trainable_params:,})")

    # 导出
    export_onnx(model, onnx_path)
    print(f"[export] 完成! 模型已保存到: {onnx_path}")


if __name__ == "__main__":
    main()
