"""Zone-Emotion Risk Linkage: emotion-aware danger zone sensitivity adjustment.

When an ANGRY person enters a danger_zone, the intrusion alarm threshold is 
temporarily lowered (more sensitive). When the person leaves or emotion 
normalizes, the threshold recovers after EMOTION_RISK_COOLDOWN seconds.
"""
import logging
import time
from collections import OrderedDict

from ..config import Config

logger = logging.getLogger(__name__)

# Maximum number of tracked persons
_MAX_TRACKED = 32

# How long to keep a person's emotion after last update (seconds)
_EMOTION_STALE_TTL = 15.0


class ZoneEmotionRisk:
    """Tracks persons' emotions and adjusts zone intrusion sensitivity.

    Integrated into InferenceEngine's shared context. Receives emotion updates
    from EmotionRecognizer (via FightPlugin feed_audio path) and person box 
    positions from FaceDetector/IntrusionPlugin.
    """

    def __init__(self):
        # face_id -> {"emotion": str, "confidence": float, "person_box": tuple, "last_update": float}
        self._persons: OrderedDict[str, dict] = OrderedDict()
        # region_id -> (modified_threshold, recovery_time)
        self._zone_modifiers: dict[int, tuple[float, float]] = {}

    def update_emotion(self, face_id: str, emotion: str, confidence: float) -> None:
        """Update tracked person's emotion state."""
        if face_id not in self._persons:
            self._persons[face_id] = {}
            # Evict oldest if too many
            if len(self._persons) > _MAX_TRACKED:
                self._persons.popitem(last=False)
        
        self._persons[face_id]["emotion"] = emotion
        self._persons[face_id]["confidence"] = confidence
        self._persons[face_id]["last_update"] = time.time()

    def update_position(self, face_id: str, person_box: tuple) -> None:
        """Update tracked person's position."""
        if face_id not in self._persons:
            self._persons[face_id] = {}
            if len(self._persons) > _MAX_TRACKED:
                self._persons.popitem(last=False)
        
        self._persons[face_id]["person_box"] = person_box
        self._persons[face_id]["last_update"] = time.time()

    def check_zone_risk(self, person_box: tuple, region_polygons: dict[int, list]) -> float:
        """Check if any ANGRY person is inside any danger_zone.
        
        Args:
            person_box: (x1, y1, x2, y2) in pixel coordinates
            region_polygons: {region_id: [[x1,y1], [x2,y2], ...]}
        
        Returns:
            Risk score [0, 1] - higher means more risky
        """
        risk = 0.0
        now = time.time()
        
        # Cleanup stale entries
        stale_ids = [
            fid for fid, p in self._persons.items()
            if now - p.get("last_update", 0) > _EMOTION_STALE_TTL
        ]
        for fid in stale_ids:
            del self._persons[fid]

        for face_id, person in self._persons.items():
            emotion = person.get("emotion", "NEUTRAL")
            pbox = person.get("person_box")
            conf = person.get("confidence", 0.0)
            
            # Only ANGRY emotion triggers zone risk
            if emotion.upper() != "ANGRY" or pbox is None:
                continue
            
            # Check if this angry person overlaps any danger zone
            for region_id, polygon in region_polygons.items():
                if self._box_in_polygon(pbox, polygon):
                    risk = max(risk, conf)
                    logger.info("[zone_emotion] ANGRY person in danger_zone region=%d "
                               "face=%s conf=%.3f", region_id, face_id, conf)
        
        return min(risk, 1.0)

    def get_zone_threshold_modifier(self, region_id: int) -> float:
        """Get threshold modifier for a zone.
        
        Returns:
            1.0 = normal sensitivity, 0.8 = 20% more sensitive (lower threshold)
        """
        now = time.time()
        if region_id in self._zone_modifiers:
            modifier, recovery_time = self._zone_modifiers[region_id]
            if now >= recovery_time:
                del self._zone_modifiers[region_id]
                return 1.0
            return modifier
        return 1.0

    def set_zone_risk(self, region_id: int, risk_score: float) -> None:
        """Mark a zone as having elevated risk from an angry person.
        
        Threshold is reduced by up to 20% based on risk_score.
        """
        if risk_score <= 0:
            return
        
        modifier = max(0.8, 1.0 - risk_score * 0.2)  # 0.8 to 1.0
        recovery_time = time.time() + Config.EMOTION_RISK_COOLDOWN
        self._zone_modifiers[region_id] = (modifier, recovery_time)
        logger.info("[zone_emotion] Zone %d threshold modifier set to %.2f (recovery in %ds)",
                   region_id, modifier, Config.EMOTION_RISK_COOLDOWN)

    @staticmethod
    def _box_in_polygon(box: tuple, polygon: list) -> bool:
        """Simple bounding-box based overlap check with polygon."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return False
        
        # Use bottom-center point as the person's ground position
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2, y2  # bottom center
        
        poly_arr = np.array(polygon, dtype=np.float32)
        try:
            result = cv2.pointPolygonTest(poly_arr, (cx, cy), False)
            return result >= 0
        except Exception:
            return False
