"""生成合成人脸数据集 — 用于在没有真实数据集时训练反欺骗模型。

生成两类图片：
  - real: 模拟真实人脸（椭圆面型 + 五官 + 皮肤纹理 + 光照变化）
  - fake:  对 real 施加 deepfake 伪影（JPEG/模糊/噪声/扭曲/网格/压缩）

用法:
    python backend/scripts/generate_dataset.py --count 500
"""
import argparse
import os
import sys

import cv2
import numpy as np

INPUT_SIZE = 128


def _imwrite_unicode(filepath: str, img: np.ndarray) -> bool:
    """cv2.imwrite 兼容中文路径"""
    _, buf = cv2.imencode(os.path.splitext(filepath)[1], img)
    with open(filepath, 'wb') as f:
        f.write(buf.tobytes())
    return True


def _imread_unicode(filepath: str) -> np.ndarray | None:
    """cv2.imread 兼容中文路径"""
    try:
        with open(filepath, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def perlin_noise_2d(shape, res, seed=42):
    """生成类 Perlin 噪声纹理"""
    np.random.seed(seed)

    def f(t):
        return 6 * t ** 5 - 15 * t ** 4 + 10 * t ** 3

    delta = (res[0] / shape[0], res[1] / shape[1])
    d = (shape[0] // res[0], shape[1] // res[1])
    grid = np.mgrid[0:res[0]:delta[0], 0:res[1]:delta[1]].transpose(1, 2, 0) % 1
    angles = 2 * np.pi * np.random.rand(res[0] + 1, res[1] + 1)
    gradients = np.dstack((np.cos(angles), np.sin(angles)))
    g00 = gradients[:-1, :-1].repeat(d[0], 0).repeat(d[1], 1)
    g10 = gradients[1:, :-1].repeat(d[0], 0).repeat(d[1], 1)
    g01 = gradients[:-1, 1:].repeat(d[0], 0).repeat(d[1], 1)
    g11 = gradients[1:, 1:].repeat(d[0], 0).repeat(d[1], 1)
    n00 = np.sum(g00 * grid, axis=2)
    n10 = np.sum(g10 * (grid - [1, 0]), axis=2)
    n01 = np.sum(g01 * (grid - [0, 1]), axis=2)
    n11 = np.sum(g11 * (grid - [1, 1]), axis=2)
    t = f(grid)
    return np.sqrt(2) * ((n00 * (1 - t[:, :, 0]) * (1 - t[:, :, 1]) +
                          n10 * t[:, :, 0] * (1 - t[:, :, 1]) +
                          n01 * (1 - t[:, :, 0]) * t[:, :, 1] +
                          n11 * t[:, :, 0] * t[:, :, 1]))


def generate_real_face(seed: int) -> np.ndarray:
    """生成一张合成"真人"脸部图像"""
    h, w = INPUT_SIZE, INPUT_SIZE
    np.random.seed(seed)

    # 肤色范围
    base = np.random.uniform(0.4, 0.85)
    r_base = base + np.random.uniform(0.05, 0.2)
    g_base = base + np.random.uniform(-0.05, 0.1)
    b_base = base - np.random.uniform(0.05, 0.15)

    # 面部椭圆
    cx, cy = w // 2 + np.random.randint(-8, 8), h // 2 + np.random.randint(-5, 5)
    rx = w // 2 - np.random.randint(5, 20)
    ry = h // 2 - np.random.randint(0, 10)
    yy, xx = np.mgrid[0:h, 0:w]
    face_mask = ((xx - cx) ** 2 / rx ** 2 + (yy - cy) ** 2 / ry ** 2) <= 1.0

    # 皮肤纹理
    noise = perlin_noise_2d((h, w), (4, 4), seed=seed * 1000)
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-8)

    # 构造 RGB
    img = np.zeros((h, w, 3), dtype=np.float32)
    for ch, base_c in enumerate([b_base, g_base, r_base]):
        ch_img = np.full((h, w), base_c, dtype=np.float32)
        ch_img += noise * np.random.uniform(0.02, 0.08)
        # 面部高光渐变
        grad = 1.0 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(rx, ry)
        grad = np.clip(grad * 0.15, 0, 0.15)
        ch_img += grad
        # 只保留面部区域
        ch_img = ch_img * (face_mask.astype(np.float32) * 0.95 + 0.05 * np.random.uniform(0.2, 0.35))
        img[:, :, ch] = ch_img

    # 五官
    def add_feature(center_x, center_y, rx_f, ry_f, intensity, color_adj):
        fy, fx = np.mgrid[0:h, 0:w]
        dist = (fx - center_x) ** 2 / rx_f ** 2 + (fy - center_y) ** 2 / ry_f ** 2
        feat_mask = np.clip(1.0 - dist, 0, 1) * intensity
        feat_mask = cv2.GaussianBlur(feat_mask.astype(np.float32), (5, 5), 2)
        for ch, adj in enumerate(color_adj):
            img[:, :, ch] = img[:, :, ch] * (1 - feat_mask * 0.5) + adj * feat_mask * 0.5

    # 眼睛
    eye_y = cy - ry // 3 + np.random.randint(-5, 5)
    add_feature(cx - rx // 3, eye_y, rx // 5, ry // 6, 0.7, [0.1, 0.1, 0.1])
    add_feature(cx + rx // 3, eye_y, rx // 5, ry // 6, 0.7, [0.1, 0.1, 0.1])

    # 鼻子
    add_feature(cx, cy + ry // 8, rx // 6, ry // 7, 0.4, [0.2, 0.18, 0.16])

    # 嘴巴
    add_feature(cx, cy + ry // 3, rx // 3, ry // 8, 0.5, [0.3, 0.15, 0.15])

    # 眉毛
    add_feature(cx - rx // 3, eye_y - ry // 7, rx // 4, ry // 12, 0.3, [0.15, 0.12, 0.1])
    add_feature(cx + rx // 3, eye_y - ry // 7, rx // 4, ry // 12, 0.3, [0.15, 0.12, 0.1])

    # 边缘淡出
    edge_dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    edge_alpha = np.clip(2.0 - edge_dist * 2, 0, 1)
    edge_alpha = cv2.GaussianBlur(edge_alpha.astype(np.float32), (15, 15), 8)
    edge_alpha = np.expand_dims(edge_alpha, 2)

    bg = np.random.uniform(0.15, 0.45, (h, w, 3)).astype(np.float32)
    img = img * edge_alpha + bg * (1 - edge_alpha)

    # 夹紧并转 uint8
    img = np.clip(img * 255, 0, 255).astype(np.uint8)

    # 轻微噪声
    noise = np.random.randint(-3, 4, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    return img


def generate_fake_from_real(real_img: np.ndarray, seed: int) -> np.ndarray:
    """对真实人脸施加 deepfake 伪影"""
    np.random.seed(seed)
    v = real_img.copy()

    # 随机选择 1-3 种伪造变换
    all_ops = ['blur', 'jpeg', 'noise', 'warp', 'grid', 'downscale', 'color_shift',
               'smoothing', 'edge_artifact', 'contrast_boost']
    n_ops = np.random.randint(1, 4)
    ops = list(np.random.choice(all_ops, size=n_ops, replace=False))

    for op in ops:
        if op == 'blur':
            k = np.random.choice([5, 7, 9])
            v = cv2.GaussianBlur(v, (k, k), 0)
        elif op == 'jpeg':
            q = np.random.randint(25, 60)
            _, buf = cv2.imencode('.jpg', v, [cv2.IMWRITE_JPEG_QUALITY, q])
            v = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        elif op == 'noise':
            std = np.random.randint(8, 25)
            noise = np.random.randn(*v.shape).astype(np.float32) * std
            v = np.clip(v.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        elif op == 'warp':
            amp = np.random.uniform(2, 5)
            x = np.arange(INPUT_SIZE, dtype=np.float32)
            map_x = x + np.sin(np.linspace(0, np.pi * np.random.uniform(1, 3), INPUT_SIZE)) * amp
            map_y = x + np.cos(np.linspace(0, np.pi * np.random.uniform(1, 3), INPUT_SIZE)) * amp
            v = cv2.remap(v, np.tile(map_x, (INPUT_SIZE, 1)).astype(np.float32),
                          np.tile(map_y.reshape(-1, 1), (1, INPUT_SIZE)).astype(np.float32),
                          cv2.INTER_LINEAR)
        elif op == 'grid':
            freq = np.random.randint(2, 5)
            amp = np.random.uniform(3, 10)
            grid = np.zeros((INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
            for i in range(0, INPUT_SIZE, INPUT_SIZE // freq):
                grid[i:i + 1, :] = amp
                grid[:, i:i + 1] = amp
            grid = cv2.GaussianBlur(grid, (3, 3), 1)
            v = np.clip(v.astype(np.float32) + np.stack([grid] * 3, 2), 0, 255).astype(np.uint8)
        elif op == 'downscale':
            s = np.random.uniform(0.3, 0.7)
            small = cv2.resize(v, (0, 0), fx=s, fy=s)
            v = cv2.resize(small, (INPUT_SIZE, INPUT_SIZE))
        elif op == 'color_shift':
            hsv = cv2.cvtColor(v, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 0] = (hsv[:, :, 0] + np.random.uniform(-15, 15)) % 180
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * np.random.uniform(0.7, 1.4), 0, 255)
            hsv[:, :, 2] = np.clip(hsv[:, :, 2] * np.random.uniform(0.8, 1.3), 0, 255)
            v = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        elif op == 'smoothing':
            v = cv2.bilateralFilter(v, 9, 75, 75)
        elif op == 'edge_artifact':
            edges = cv2.Canny(v, 50, 150)
            edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
            edge_amp = np.random.uniform(5, 20)
            for c in range(3):
                v[:, :, c] = np.clip(v[:, :, c].astype(np.int16) +
                                     (edges * edge_amp).astype(np.int16), 0, 255).astype(np.uint8)
        elif op == 'contrast_boost':
            v = cv2.convertScaleAbs(v, alpha=np.random.uniform(1.2, 1.5), beta=np.random.randint(-20, 20))

    return v


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic face dataset")
    parser.add_argument("--count", type=int, default=500,
                        help="每类生成的图片数量（默认 500）")
    parser.add_argument("--output", type=str, default=None,
                        help="输出目录（默认: backend/training_data/faces）")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.output or os.path.join(project_root, "training_data", "faces")
    real_dir = os.path.join(out_dir, "real")
    fake_dir = os.path.join(out_dir, "fake")
    os.makedirs(real_dir, exist_ok=True)
    os.makedirs(fake_dir, exist_ok=True)

    n = args.count
    print(f"Generating {n} real + {n} fake synthetic faces...")

    for i in range(n):
        # Real
        real = generate_real_face(seed=i * 2)
        _imwrite_unicode(os.path.join(real_dir, f"{i:05d}.jpg"), real)

        fake = generate_fake_from_real(real, seed=i * 2 + 1)
        _imwrite_unicode(os.path.join(fake_dir, f"{i:05d}.jpg"), fake)

        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{n} done")

    real_count = len(os.listdir(real_dir))
    fake_count = len(os.listdir(fake_dir))
    print(f"Done! {real_count} real + {fake_count} fake images in {out_dir}")


if __name__ == "__main__":
    main()
