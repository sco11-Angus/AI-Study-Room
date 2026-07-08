"""从图片目录生成 member 表 INSERT SQL，用于测试人脸识别。

用法：
    python -m scripts.gen_member_sql --photo-dir path/to/photos

输出：
    member_inserts.sql（可直接 sqlite3 导入）

图片命名规则：
    <member_id>.jpg          → name 自动为 member_<member_id>
    <member_id>_张三.jpg      → name 取 "张三"

依赖 dlib 模型：
    model_weights/shape_predictor_68_face_landmarks.dat
    model_weights/dlib_face_recognition_resnet_model_v1.dat
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.detectors.face import FaceMatcher


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

    lines = [
        "-- 自动生成的 member 表测试数据",
        f"-- 来源: {photo_dir}",
        "",
    ]

    success = 0
    for filename in files:
        stem = os.path.splitext(filename)[0]
        try:
            member_id = int(stem.split("_")[0])
        except ValueError:
            print(f"  [跳过] 无法解析 member_id: {filename}")
            continue

        name = "_".join(stem.split("_")[1:]) or f"member_{member_id}"

        path = os.path.join(photo_dir, filename)
        # cv2.imread 不支持中文路径，用 imdecode 代替
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"  [跳过] 无法读取图片: {filename}")
            continue

        feature = matcher.encode(img)
        if feature is None:
            print(f"  [跳过] 未检测到人脸: {filename}")
            continue

        feature_json = json.dumps(feature.tolist(), ensure_ascii=False)
        # 用单引号包裹 JSON 字符串，转义内部的单引号
        escaped = feature_json.replace("'", "''")
        sql = (
            f"INSERT OR REPLACE INTO member (member_id, name, feature) "
            f"VALUES ({member_id}, '{name}', '{escaped}');"
        )
        lines.append(sql)
        success += 1
        print(f"  [OK] {filename} → member_id={member_id}, name={name}, dim={len(feature)}")

    if success == 0:
        print("[gen_member_sql] 没有成功提取到任何人脸特征。")
        sys.exit(1)

    # 写入文件
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output)
    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[gen_member_sql] 完成！共 {success} 条记录 → {output_path}")
    print(f"  导入方式: sqlite3 study_room.db < {output_path}")


if __name__ == "__main__":
    main()
