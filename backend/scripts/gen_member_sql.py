"""从图片目录生成 member 表 INSERT SQL，用于测试人脸识别。

用法：
    python -m scripts.gen_member_sql --photo-dir path/to/photos

输出：
    member_inserts.sql（可直接 sqlite3 导入）

图片命名规则：
    <member_id>.jpg          → name 自动为 member_<member_id>
    <member_id>_张三.jpg      → name 取 "张三"
    <member_id>_1.jpg        → 同一 member_id 的多张图片合并为多参考特征
    <member_id>_2.jpg

依赖 dlib 模型：
    model_weights/shape_predictor_68_face_landmarks.dat
    model_weights/dlib_face_recognition_resnet_model_v1.dat
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.detectors.face import FaceMatcher


def parse_filename(filename: str) -> tuple[int, str]:
    """解析文件名，返回 (member_id, display_name)。

    >>> parse_filename("1.jpg")        → (1, "member_1")
    >>> parse_filename("1_张三.jpg")    → (1, "张三")
    >>> parse_filename("1_0.jpg")      → (1, "member_1")
    """
    stem = os.path.splitext(filename)[0]
    parts = stem.split("_", 1)
    try:
        member_id = int(parts[0])
    except ValueError:
        raise ValueError(f"无法解析 member_id: {filename}")

    if len(parts) == 1:
        name = f"member_{member_id}"
    else:
        # 第二部分可能是数字后缀（多帧）或中文名
        suffix = parts[1]
        try:
            int(suffix)  # 纯数字 → 多帧序号，使用默认名
            name = f"member_{member_id}"
        except ValueError:
            name = suffix  # 非数字 → 中文名

    return member_id, name


def main():
    parser = argparse.ArgumentParser(description="生成 member 表 INSERT SQL")
    parser.add_argument("--photo-dir", required=True, help="人脸照片目录")
    parser.add_argument("--output", default="member_inserts.sql", help="输出 SQL 文件名")
    args = parser.parse_args()

    photo_dir = args.photo_dir
    if not os.path.isdir(photo_dir):
        print(f"[ERROR] 目录不存在: {photo_dir}")
        sys.exit(1)

    files = sorted(
        f for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if not files:
        print(f"[ERROR] 目录中无 jpg/png 文件: {photo_dir}")
        sys.exit(1)

    print(f"[gen_member_sql] 找到 {len(files)} 张图片，加载模型...")
    matcher = FaceMatcher()

    # 按 member_id 分组（支持多帧 → 多参考特征）
    groups: dict[int, list[tuple[str, str]]] = defaultdict(list)
    member_names: dict[int, str] = {}
    for filename in files:
        try:
            mid, name = parse_filename(filename)
        except ValueError as e:
            print(f"  [跳过] {e}")
            continue
        filepath = os.path.join(photo_dir, filename)
        groups[mid].append((filepath, filename))
        member_names[mid] = name

    lines = [
        "-- 自动生成的 member 表测试数据",
        f"-- 来源: {photo_dir}",
        f"-- 共 {len(groups)} 个会员，{len(files)} 张参考图片",
        "",
    ]

    success = 0
    for member_id in sorted(groups.keys()):
        name = member_names[member_id]
        ref_features = []

        for filepath, filename in groups[member_id]:
            # cv2.imread 不支持中文路径，用 imdecode 代替
            img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                print(f"  [跳过] 无法读取图片: {filename}")
                continue

            feature = matcher.encode(img)
            if feature is None:
                print(f"  [跳过] 未检测到人脸: {filename}")
                continue

            ref_features.append(feature.tolist())
            print(f"  [OK] {filename} → member_id={member_id}, dim={len(feature)}")

        if not ref_features:
            print(f"  [警告] member_id={member_id} 没有成功提取到任何特征，跳过")
            continue

        # 统一以二维数组格式存储（单帧也是 [[...]]）
        feature_json = json.dumps(ref_features, ensure_ascii=False)
        escaped = feature_json.replace("'", "''")
        sql = (
            f"INSERT OR REPLACE INTO member (member_id, name, feature) "
            f"VALUES ({member_id}, '{name}', '{escaped}');"
        )
        lines.append(sql)
        success += 1
        n_refs = len(ref_features)
        print(f"  → 入库: member_id={member_id}, name={name}, refs={n_refs}")

    if success == 0:
        print("[gen_member_sql] 没有成功提取到任何人脸特征。")
        sys.exit(1)

    # 写入文件
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output)
    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[gen_member_sql] 完成！共 {success} 个会员 → {output_path}")
    print(f"  导入方式: sqlite3 study_room.db < {output_path}")


if __name__ == "__main__":
    main()
