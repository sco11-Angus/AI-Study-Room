"""训练 AMTENFC 反欺骗模型（对齐 repo 架构）。

由于网络限制无法下载 140k 数据集，本脚本使用：
  - 本地人脸照片（增强 → real 类）
  - 合成伪造图片（多种变换 → fake 类）

架构严格对齐 shreyash1706/Solving-Deepfakes-with-Traces-Frequency-and-Attention。

用法:
    python backend/scripts/train_antispoof.py [--epochs 50] [--batch 32]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

from app.detectors.antispoof_model import AMTENFC, block_dct

# 随机种子
torch.manual_seed(42)
np.random.seed(42)

INPUT_SIZE = 128
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ==============================================================================
# 数据增强 — 将少量真实图片扩展为训练集
# ==============================================================================

def _imread_unicode(filepath: str) -> np.ndarray | None:
    """cv2.imread 兼容中文路径"""
    try:
        with open(filepath, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def load_real_images(photo_dir: str) -> list[np.ndarray]:
    """加载本地真实人脸照片"""
    images = []
    for fname in sorted(os.listdir(photo_dir)):
        if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
            img = _imread_unicode(os.path.join(photo_dir, fname))
            if img is not None and img.shape[0] > 50 and img.shape[1] > 50:
                images.append(img)
    return images


def augment_real(img: np.ndarray, count: int = 40) -> list[np.ndarray]:
    """从一张真实图片生成多种增强版本（保持真实特征）"""
    variants = []
    h, w = img.shape[:2]
    for _ in range(count):
        v = img.copy()
        # 随机裁剪 + resize
        scale = np.random.uniform(0.7, 1.0)
        crop_h = int(h * scale)
        crop_w = int(w * scale)
        y0 = np.random.randint(0, max(1, h - crop_h))
        x0 = np.random.randint(0, max(1, w - crop_w))
        v = v[y0:y0 + crop_h, x0:x0 + crop_w]
        v = cv2.resize(v, (INPUT_SIZE, INPUT_SIZE))

        # 亮度/对比度微调
        alpha = np.random.uniform(0.85, 1.15)
        beta = np.random.randint(-10, 10)
        v = cv2.convertScaleAbs(v, alpha=alpha, beta=beta)

        # 轻微旋转
        if np.random.random() < 0.5:
            angle = np.random.uniform(-8, 8)
            M = cv2.getRotationMatrix2D((INPUT_SIZE // 2, INPUT_SIZE // 2), angle, 1.0)
            v = cv2.warpAffine(v, M, (INPUT_SIZE, INPUT_SIZE),
                               borderMode=cv2.BORDER_REFLECT)

        # 水平翻转
        if np.random.random() < 0.5:
            v = cv2.flip(v, 1)

        variants.append(v)
    return variants


def generate_fake(img: np.ndarray, count: int = 40) -> list[np.ndarray]:
    """从真实图片生成伪造版本（模拟 deepfake 伪影）"""
    variants = []
    h, w = img.shape[:2]
    for _ in range(count):
        v = img.copy()
        v = cv2.resize(v, (INPUT_SIZE, INPUT_SIZE))

        # 随机选择 1-3 种伪造变换组合
        ops = np.random.choice(['blur', 'jpeg', 'noise', 'warp',
                                'color_shift', 'grid', 'downscale'], size=np.random.randint(1, 4), replace=False)

        for op in ops:
            if op == 'blur':
                k = np.random.choice([3, 5, 7])
                v = cv2.GaussianBlur(v, (k, k), 0)
            elif op == 'jpeg':
                quality = np.random.randint(30, 70)
                _, buf = cv2.imencode('.jpg', v, [cv2.IMWRITE_JPEG_QUALITY, quality])
                v = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            elif op == 'noise':
                noise = np.random.randn(*v.shape).astype(np.float32) * np.random.randint(5, 20)
                v = np.clip(v.astype(np.float32) + noise, 0, 255).astype(np.uint8)
            elif op == 'warp':
                # 局部扭曲模拟 face swap 边缘
                map_x = np.arange(INPUT_SIZE, dtype=np.float32) + np.sin(np.linspace(0, 2*np.pi, INPUT_SIZE)) * np.random.uniform(1, 3)
                map_y = np.arange(INPUT_SIZE, dtype=np.float32) + np.cos(np.linspace(0, 2*np.pi, INPUT_SIZE)) * np.random.uniform(1, 3)
                map_x = np.tile(map_x, (INPUT_SIZE, 1))
                map_y = np.tile(map_y.reshape(-1, 1), (1, INPUT_SIZE))
                v = cv2.remap(v, map_x.astype(np.float32), map_y.astype(np.float32), cv2.INTER_LINEAR)
            elif op == 'color_shift':
                v = cv2.cvtColor(v, cv2.COLOR_BGR2HSV).astype(np.float32)
                v[:, :, 0] = (v[:, :, 0] + np.random.uniform(-10, 10)) % 180
                v[:, :, 1] = np.clip(v[:, :, 1] * np.random.uniform(0.8, 1.2), 0, 255)
                v = cv2.cvtColor(v.astype(np.uint8), cv2.COLOR_HSV2BGR)
            elif op == 'grid':
                # GAN 网格伪影
                grid = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.float32)
                freq = np.random.randint(2, 6)
                amp = np.random.uniform(2, 8)
                for c in range(3):
                    for i in range(0, INPUT_SIZE, INPUT_SIZE // freq):
                        grid[i:i + 1, :, c] = amp
                        grid[:, i:i + 1, c] = amp
                    grid[:, :, c] = cv2.GaussianBlur(grid[:, :, c], (3, 3), 1)
                v = np.clip(v.astype(np.float32) + grid, 0, 255).astype(np.uint8)
            elif op == 'downscale':
                s = np.random.uniform(0.4, 0.8)
                small = cv2.resize(v, (0, 0), fx=s, fy=s)
                v = cv2.resize(small, (INPUT_SIZE, INPUT_SIZE))

        variants.append(v)
    return variants


# ==============================================================================
# Dataset
# ==============================================================================

class FaceAntiSpoofDataset(Dataset):
    """实时计算 DCT 特征（无需预计算的 .npy 文件）"""

    def __init__(self, images: list[np.ndarray], labels: list[int],
                 augment: bool = False):
        self.images = images
        self.labels = labels
        self.augment = augment

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        bgr = self.images[idx].copy()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        # 训练时随机增强
        if self.augment:
            if np.random.random() < 0.5:
                rgb = cv2.flip(rgb, 1)
            if np.random.random() < 0.3:
                alpha = np.random.uniform(0.9, 1.1)
                beta = np.random.randint(-5, 5)
                rgb = cv2.convertScaleAbs(rgb, alpha=alpha, beta=beta)

        rgb = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE))
        rgb_tensor = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1)

        # 实时计算 DCT
        dct_feat = block_dct(rgb, block_size=4, stride=2)  # (48, 63, 63)
        dct_tensor = torch.from_numpy(dct_feat)

        label = torch.tensor(self.labels[idx], dtype=torch.float32)
        return rgb_tensor, dct_tensor, label


def load_dataset_from_dir(dataset_dir: str):
    """从目录加载真实数据集，Real/ 和 Fake/ 子文件夹。"""
    images = []
    labels = []
    for cls_name, label in [('Real', 1), ('Fake', 0)]:
        cls_dir = os.path.join(dataset_dir, cls_name)
        if not os.path.isdir(cls_dir):
            continue
        for fname in sorted(os.listdir(cls_dir)):
            if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                img = _imread_unicode(os.path.join(cls_dir, fname))
                if img is not None:
                    images.append(img)
                    labels.append(label)
    return images, labels


# ==============================================================================
# 训练
# ==============================================================================

def train_model(model, train_loader, val_loader, criterion, optimizer,
                scheduler, num_epochs: int, checkpoint_dir: str,
                start_epoch: int = 0, best_acc: float = 0.0):
    checkpoint_path = os.path.join(checkpoint_dir, "amtenfc_checkpoint.pth")
    best_path = os.path.join(checkpoint_dir, "best_amtenfc.pth")

    for epoch in range(start_epoch, num_epochs):
        # ---- Train ----
        model.train()
        running_loss = 0.0
        running_corrects = 0
        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{num_epochs} [Train]")
        for rgb, dct, labels in pbar:
            rgb = rgb.to(DEVICE)
            dct = dct.to(DEVICE)
            labels = labels.unsqueeze(1).to(DEVICE)

            optimizer.zero_grad()
            outputs = model(rgb, dct)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item() * rgb.size(0)
            preds = (torch.sigmoid(outputs) > 0.5).float()
            running_corrects += (preds == labels).sum().item()
            pbar.set_postfix(loss=f"{loss.item():.4f}")

        epoch_loss = running_loss / len(train_loader.dataset)
        epoch_acc = running_corrects / len(train_loader.dataset)

        # ---- Val ----
        model.eval()
        val_loss = 0.0
        val_corrects = 0
        with torch.no_grad():
            for rgb, dct, labels in val_loader:
                rgb = rgb.to(DEVICE)
                dct = dct.to(DEVICE)
                labels = labels.unsqueeze(1).to(DEVICE)
                outputs = model(rgb, dct)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * rgb.size(0)
                probs = torch.sigmoid(outputs)
                preds = (probs > 0.5).float()
                val_corrects += (preds == labels).sum().item()

        val_loss /= len(val_loader.dataset)
        val_acc = val_corrects / len(val_loader.dataset)
        scheduler.step(val_acc)

        print(f"Epoch {epoch+1:3d} | Train Loss: {epoch_loss:.4f} Acc: {epoch_acc:.4f} | "
              f"Val Loss: {val_loss:.4f} Acc: {val_acc:.4f}")

        # 保存检查点
        torch.save({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'best_acc': best_acc,
        }, checkpoint_path)

        # 保存最佳模型
        if val_acc > best_acc:
            best_acc = val_acc
            torch.save(model.state_dict(), best_path)
            print(f"  -> Best model saved (val_acc={best_acc:.4f})")

    print(f"\nTraining complete. Best val_acc: {best_acc:.4f}")
    return best_path, best_acc


# ==============================================================================
# 主流程
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Train AMTENFC anti-spoofing model")
    parser.add_argument("--epochs", type=int, default=80, help="训练轮数")
    parser.add_argument("--batch", type=int, default=32, help="批次大小")
    parser.add_argument("--aug-per-image", type=int, default=50,
                        help="合成模式：每张真实图片生成的变体数量")
    parser.add_argument("--lr", type=float, default=5e-4, help="学习率")
    parser.add_argument("--dataset", type=str, default=None,
                        help="真实数据集目录（含 Real/ 和 Fake/ 子文件夹，如 backend/training_data/hardfake）")
    parser.add_argument("--resume", action="store_true",
                        help="从 checkpoint 恢复训练")
    args = parser.parse_args()

    # ---- 路径 ----
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    weights_dir = os.path.join(project_root, "model_weights")
    os.makedirs(weights_dir, exist_ok=True)

    print(f"Device: {DEVICE}")

    # ---- 加载数据 ----
    if args.dataset and os.path.isdir(args.dataset):
        # ---- 真实数据集模式 ----
        print(f"Loading real dataset: {args.dataset}")
        images, labels = load_dataset_from_dir(args.dataset)
        real_count = sum(labels)
        fake_count = len(labels) - real_count
        print(f"Loaded: {real_count} Real + {fake_count} Fake = {len(images)} total")

        indices = np.random.permutation(len(images))
        split = int(len(images) * 0.8)
        train_idx, val_idx = indices[:split], indices[split:]

        train_images = [images[i] for i in train_idx]
        train_labels = [labels[i] for i in train_idx]
        val_images = [images[i] for i in val_idx]
        val_labels = [labels[i] for i in val_idx]

        train_dataset = FaceAntiSpoofDataset(train_images, train_labels, augment=True)
        val_dataset = FaceAntiSpoofDataset(val_images, val_labels, augment=False)

    else:
        # ---- 合成数据模式（fallback） ----
        photo_dir = os.path.join(project_root, "test_photos")
        print(f"Photo dir: {photo_dir}")

        real_images = load_real_images(photo_dir)
        if not real_images:
            print("ERROR: 未找到真实人脸照片! 请将照片放入 backend/test_photos/")
            print("或使用 --dataset 指定数据集目录")
            sys.exit(1)
        print(f"Found {len(real_images)} real face photos")

        print("Generating augmented real images...")
        all_real = []
        for img in real_images:
            all_real.extend(augment_real(img, count=args.aug_per_image))

        print("Generating synthetic fake images...")
        all_fake = []
        for img in real_images:
            all_fake.extend(generate_fake(img, count=args.aug_per_image))

        total_real = len(all_real)
        total_fake = len(all_fake)
        print(f"Synthetic dataset: {total_real} real + {total_fake} fake = {total_real + total_fake} total")

        indices_real = np.random.permutation(total_real)
        indices_fake = np.random.permutation(total_fake)
        sp = 0.85
        n_train_real = int(total_real * sp)
        n_train_fake = int(total_fake * sp)

        train_images = (
            [all_real[i] for i in indices_real[:n_train_real]] +
            [all_fake[i] for i in indices_fake[:n_train_fake]]
        )
        train_labels = [1] * n_train_real + [0] * n_train_fake
        val_images = (
            [all_real[i] for i in indices_real[n_train_real:]] +
            [all_fake[i] for i in indices_fake[n_train_fake:]]
        )
        val_labels = [1] * (total_real - n_train_real) + [0] * (total_fake - n_train_fake)

        train_dataset = FaceAntiSpoofDataset(train_images, train_labels, augment=True)
        val_dataset = FaceAntiSpoofDataset(val_images, val_labels, augment=False)

    train_loader = DataLoader(train_dataset, batch_size=args.batch, shuffle=True,
                              num_workers=0, pin_memory=False)
    val_loader = DataLoader(val_dataset, batch_size=args.batch, shuffle=False,
                            num_workers=0, pin_memory=False)

    # ---- 构建模型 ----
    model = AMTENFC(num_classes=1).to(DEVICE)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model params: {total_params:,}")

    # ---- 优化器 & 调度器（严格对齐 repo）----
    optimizer = optim.AdamW(model.parameters(), lr=args.lr,
                            betas=(0.9, 0.999), eps=1e-8, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='max', factor=0.5, patience=5)
    criterion = nn.BCEWithLogitsLoss()

    start_epoch = 0
    best_acc = 0.0

    # ---- 恢复训练 ----
    if args.resume:
        ckpt_path = os.path.join(weights_dir, "amtenfc_checkpoint.pth")
        if os.path.exists(ckpt_path):
            ckpt = torch.load(ckpt_path, map_location=DEVICE)
            model.load_state_dict(ckpt["model_state_dict"])
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
            start_epoch = ckpt["epoch"] + 1
            best_acc = ckpt.get("best_acc", 0.0)
            print(f"Resumed from epoch {start_epoch}, best_acc={best_acc:.4f}")
        else:
            print("No checkpoint found, starting from scratch")

    # ---- 训练 ----
    t0 = time.time()
    best_path, best_acc = train_model(
        model, train_loader, val_loader, criterion,
        optimizer, scheduler, num_epochs=args.epochs,
        checkpoint_dir=weights_dir,
        start_epoch=start_epoch, best_acc=best_acc,
    )
    elapsed = time.time() - t0
    print(f"Training time: {elapsed / 60:.1f} min")

    # ---- 导出 ONNX ----
    print("\nExporting ONNX...")
    onnx_path = os.path.join(weights_dir, "antispoof_amtenet_vanet.onnx")
    model.eval()
    dummy_rgb = torch.randn(1, 3, 128, 128)
    dummy_dct = torch.randn(1, 48, 63, 63)
    torch.onnx.export(
        model, (dummy_rgb, dummy_dct), onnx_path,
        export_params=True, opset_version=14, do_constant_folding=True,
        input_names=["rgb", "dct"], output_names=["logits"],
        dynamic_axes={"rgb": {0: "batch_size"}, "dct": {0: "batch_size"},
                      "logits": {0: "batch_size"}},
    )
    print(f"ONNX exported: {onnx_path}")

    # 验证 ONNX
    import onnxruntime as ort
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    out = session.run(None, {
        "rgb": np.random.randn(1, 3, 128, 128).astype(np.float32),
        "dct": np.random.randn(1, 48, 63, 63).astype(np.float32),
    })
    print(f"ONNX verify OK, output shape: {out[0].shape}")

    print(f"\nDone! Best model: {best_path} (acc={best_acc:.4f})")
    print(f"ONNX model: {onnx_path}")


if __name__ == "__main__":
    main()
