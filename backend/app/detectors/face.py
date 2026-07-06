"""人脸识别 — Dlib 特征匹配 (系统设计说明书 §7.2)。

告警瞬间裁剪入侵者面部，提取 128 维特征，与注册会员库欧氏距离匹配。
"""


class FaceMatcher:
    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold  # 欧氏距离阈值

    def encode(self, face_img):
        """提取 128 维人脸特征向量。"""
        # TODO: dlib face_recognition_model 提取特征
        ...

    def match(self, feature) -> str:
        """与会员特征库比对，返回 会员ID 或 'stranger'。"""
        # TODO: 遍历 member.feature，取最近邻，超阈值判为 stranger
        ...
