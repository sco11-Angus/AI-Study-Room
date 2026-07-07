"""批量会员照片编码入库脚本（B9）。

用法：
    python -m scripts.enroll_faces --photo-dir path/to/photos

照片命名规则：`<member_id>.jpg` 或 `<member_id>_<name>.jpg`，如 `1.jpg`、`2_张三.jpg`。
每张照片提取 128 维特征，写入 member.feature 字段。

依赖 dlib 模型：
    model_weights/shape_predictor_68_face_landmarks.dat
    model_weights/dlib_face_recognition_resnet_model_v1.dat
"""
import argparse
import json
import os
import sys

import cv2

# 确保 backend 包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.models.database import SessionLocal, init_db
from app.models.entities import Member
from app.detectors.face import FaceMatcher


def enroll_photos(photo_dir: str, dry_run: bool = False):
    """遍历目录中所有 jpg/png，提取特征写入 DB。"""
    if not os.path.isdir(photo_dir):
        print(f"[enroll] 目录不存在: {photo_dir}")
        return

    init_db()
    matcher = FaceMatcher()

    files = sorted(
        f for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )

    if not files:
        print(f"[enroll] 目录中无 jpg/png 文件: {photo_dir}")
        return

    print(f"[enroll] 找到 {len(files)} 张照片，开始编码...")

    for filename in files:
        # 解析 member_id
        stem = os.path.splitext(filename)[0]  # e.g. "1" or "2_张三"
        try:
            member_id = int(stem.split("_")[0])
        except ValueError:
            print(f"[enroll] 跳过（无法解析 ID）: {filename}")
            continue

        path = os.path.join(photo_dir, filename)
        img = cv2.imread(path)
        if img is None:
            print(f"[enroll] 跳过（无法读取）: {filename}")
            continue

        feature = matcher.encode(img)
        if feature is None:
            print(f"[enroll] 跳过（未检测到人脸）: {filename}")
            continue

        feature_json = json.dumps(feature.tolist())
        print(f"[enroll] {filename} -> member_id={member_id}, vector_dim={len(feature)}")

        if dry_run:
            continue

        session = SessionLocal()
        try:
            member = session.query(Member).filter_by(member_id=member_id).first()
            if member:
                member.feature = feature_json
            else:
                name = "_".join(stem.split("_")[1:]) if "_" in stem else f"member_{member_id}"
                member = Member(member_id=member_id, name=name, feature=feature_json)
                session.add(member)
            session.commit()
            print(f"[enroll]   -> 已写入 DB")
        except Exception:
            session.rollback()
            print(f"[enroll]   -> DB 写入失败: {filename}")
            raise
        finally:
            session.close()

    print("[enroll] 完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="会员人脸批量入库")
    parser.add_argument("--photo-dir", required=True, help="会员照片目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()
    enroll_photos(args.photo_dir, args.dry_run)
