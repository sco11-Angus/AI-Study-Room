# FSD（Forensic Self-Descriptions）下载与配置指南

> FSD = 零样本 AI 生成图像检测器（CVPR 2025），论文 <https://arxiv.org/abs/2503.21003>。
> 本项目用它做**活体检测的第一道闸门**：先判断摄像头画面是否为 AI 生成/换脸（Stable Diffusion、Midjourney、Magic Hour 等 24 种生成器），是则直接拦截，否则进入完整活体检测流程。
>
> 代码接入点：`backend/app/detectors/antispoof_model.py`（`_load_fsd` / `_detect_fsd` / `detect_fsd_only`），由 `backend/app/detectors/liveness.py` 调用。

---

## 一、当前环境实测状态（2026-07-14）

| 项目 | 状态 | 说明 |
|------|------|------|
| FSD 源码 | ✅ 已存在 | `third_party/Forensic-Self-Descriptions-CVPR25/` |
| 预训练权重 | ✅ 已下载 | `~/.cache/fsd/v1.2.0/`（config.json / fre.pt / gmm.pt / fsd_transforms.pt，约 55MB） |
| 运行时依赖 | ✅ 已满足 | torch 2.13.0+cpu、numpy、scipy 1.18.0、Pillow 12.1.0 |
| `fsd` 包可导入 | ❌ **缺这一步** | 未 `pip install`，`import fsd` 失败 → FSD 静默降级不生效 |

**结论：只差"让 `fsd` 可被 import"这一步。** 补齐后 FSD 即生效（已实测 `FSDDetector.load(device="cpu")` 成功，version=1.2.0）。

---

## 二、下载源码（若目录为空 / 全新环境）

FSD 源码位于 `third_party/`。当前它是一个**未在父仓库登记的 git 克隆**（无 `.gitmodules` 条目）。全新环境直接克隆即可：

```bash
cd "D:/1/大二暑期实训/App/third_party"
git clone https://github.com/ductai199x/Forensic-Self-Descriptions-CVPR25.git
```

克隆后目录应包含：`fsd/`（Python 包）、`demo.py`、`pyproject.toml`、`README.md`。

---

## 三、安装依赖

FSD **推理路径**（`FSDDetector.score()`）实际只用到 torch / numpy / scipy / Pillow，本项目已全部具备。`pyproject.toml` 里列的 `scikit-learn`、`pillow-heif`、`ray`、`gradio` 仅供其 CLI / 训练 / 归因功能，**推理不需要**，无需安装。

如需在**全新环境**补齐核心依赖：

```bash
pip install "torch>=2.10" "scipy>=1.13" "pillow>=11" numpy
```

> 注：`pyproject.toml` 声称需要 torch>=2.10.0、python>=3.12。本机 Python 3.13 + torch 2.13.0+cpu 实测可用。CPU 版即可，无需 GPU。

---

## 四、让 `fsd` 包可被后端导入（关键步骤）

后端通过 `from fsd import FSDDetector` 加载。`fsd` 包在 `third_party/Forensic-Self-Descriptions-CVPR25/`，需让 Python 找到它。**任选一种**：

### 方式 A：可编辑安装（推荐，一次性）

```bash
cd "D:/1/大二暑期实训/App/third_party/Forensic-Self-Descriptions-CVPR25"
pip install -e . --no-deps
```

`--no-deps` 跳过 ray/gradio 等重依赖，只把 `fsd` 包注册进环境。装完 `python -c "import fsd"` 即可。

### 方式 B：设置 PYTHONPATH（不改环境，临时）

启动后端前设置环境变量：

```bash
# Git Bash
export PYTHONPATH="D:/1/大二暑期实训/App/third_party/Forensic-Self-Descriptions-CVPR25:$PYTHONPATH"
cd backend && python run.py
```

```powershell
# PowerShell
$env:PYTHONPATH = "D:\1\大二暑期实训\App\third_party\Forensic-Self-Descriptions-CVPR25;$env:PYTHONPATH"
cd backend; python run.py
```

> 方式 A 更省心（重启后仍有效）；方式 B 适合临时验证，每次新终端都要重设。

---

## 五、权重（首次运行自动下载）

`FSDDetector.load()` 首次调用会自动从 GitHub Release 下载权重到 `~/.cache/fsd/v1.2.0/`：

| 文件 | 用途 |
|------|------|
| `config.json` | 模型配置 |
| `fre.pt` | 频域残差提取器（Forensic Residual Extractor） |
| `gmm.pt` | 高斯混合模型（真实图像分布） |
| `fsd_transforms.pt` | FSD 特征变换 |

本机这些**已下载完毕**，无需再动。

**手动下载（自动下载失败 / 网络受限时）**：从
<https://github.com/ductai199x/Forensic-Self-Descriptions-CVPR25/releases/tag/v1.2.0>
下载上述 4 个文件，放到 `C:\Users\<你的用户名>\.cache\fsd\v1.2.0\`。

自定义权重目录可在代码中显式指定：`FSDDetector.load(weights_dir="path/to/weights/")`。

---

## 六、验证 FSD 是否生效

### 6.1 独立验证包 + 权重

```bash
cd "D:/1/大二暑期实训/App/backend"
python -c "
import sys
sys.path.insert(0, r'D:\1\大二暑期实训\App\third_party\Forensic-Self-Descriptions-CVPR25')
from fsd import FSDDetector
d = FSDDetector.load(device='cpu')
print('FSD OK, version =', __import__('fsd').__version__)
"
```

预期输出：`FSD OK, version = 1.2.0`（本机已实测通过）。

### 6.2 后端日志确认

配置好后重启后端，日志应出现：

```
[antispoof] FSD 零样本检测器已加载 (CVPR 2025, max_size=512)
```

运行中每 30 帧打印一次评分：

```
[antispoof] FSD z=-8.421 (smooth=-9.102) is_fake=False mode=full_frame (第31帧)
```

**若看到** `[antispoof] FSD 检测器加载失败: No module named 'fsd'` → 说明第四步没做好，`fsd` 包仍未进入 Python 路径。

---

## 七、评分逻辑速览（便于调参）

`_detect_fsd()` 返回 `fsd_score ∈ [0,1]`，**1.0=真实，0.0=AI 生成**：

- FSD 输出原始 `z_score`，经 EMA 平滑（`alpha=0.5`，2 帧收敛）防单帧尖刺误触发。
- 归一化：`fsd_score = clip((z_smooth + 25) / 24, 0, 1)`
  - 真人 webcam：`z ≈ -5 ~ -15` → `fsd ≈ 0.4~0.8`（不干扰正常活体）
  - AI 生成（如 Magic Hour）：`z ≈ -40 ~ -72` → `fsd = 0.0`（触发拦截）
- 全帧模式（画面 ≥300px）取中心正方形分析全局伪影；人脸裁剪 <200px 时放大到 224×224。

静态融合（`predict` 路径）：`static_score = 0.60*fsd + 0.40*deepfake`，FSD 为主权重。

---

## 八、常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `No module named 'fsd'` | `fsd` 包未安装/未加 PYTHONPATH | 执行第四步 |
| `Failed to download ... releases/download/v1.2.0` | 网络无法访问 GitHub | 按第五步手动下载权重 |
| FSD 一直 `is_fake=True` 误拦真人 | 阈值/画面偏暗或过度压缩 | 调 `_detect_fsd` 归一化区间，或临时降低融合权重 |
| 后端启动变慢 | 首帧触发 FSD 权重加载（延迟加载） | 正常，仅首次；后续复用 |

> FSD 是延迟加载：只有活体检测拿到 `full_frame` 时才会触发 `_load_fsd()`，不影响后端启动速度。
