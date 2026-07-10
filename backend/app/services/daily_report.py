"""AI监控日报服务 — 自动生成每日监控报告。"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import Config

logger = logging.getLogger(__name__)


TYPE_STATS_LABELS = {
    "intrusion": "入侵告警",
    "fire_smoke": "烟火告警",
    "occupy": "占座告警",
    "fatigue": "疲劳提醒",
    "fight": "打架告警",
    "face_recognition": "人脸识别"
}


class DailyReportService:
    """每日监控日报生成器。"""

    def __init__(self, report_dir: str = None):
        self.report_dir = report_dir or os.path.join(
            os.path.dirname(__file__), "..", "..", "reports"
        )
        os.makedirs(self.report_dir, exist_ok=True)

    def generate_report(self, date: Optional[datetime] = None) -> dict:
        """生成指定日期的监控日报。
        
        Args:
            date: 日期，默认为昨天
        
        Returns:
            report: 日报内容字典
        """
        if date is None:
            date = datetime.now(timezone.utc) - timedelta(days=1)
        
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        from ..models.database import SessionLocal
        from ..models.entities import AlarmEvent, Camera, Region
        
        session = SessionLocal()
        try:
            query = session.query(AlarmEvent).filter(
                AlarmEvent.created_at >= start_of_day,
                AlarmEvent.created_at <= end_of_day
            )
            
            total_alarms = query.count()
            
            type_stats = {}
            level_stats = {0: 0, 1: 0, 2: 0, 'other': 0}
            region_stats = {}
            camera_stats = {}
            confirmed_count = 0
            escalated_count = 0
            
            alarms = query.all()
            for alarm in alarms:
                type_stats[alarm.type] = type_stats.get(alarm.type, 0) + 1
                
                if alarm.level in level_stats:
                    level_stats[alarm.level] += 1
                else:
                    level_stats['other'] += 1
                
                region_stats[alarm.region_id] = region_stats.get(alarm.region_id, 0) + 1
                camera_stats[alarm.camera_id] = camera_stats.get(alarm.camera_id, 0) + 1
                
                if alarm.status == 'confirmed':
                    confirmed_count += 1
                elif alarm.status == 'escalated':
                    escalated_count += 1
            
            top_alarm_types = sorted(
                type_stats.items(), key=lambda x: x[1], reverse=True
            )[:3]
            
            top_regions = sorted(
                region_stats.items(), key=lambda x: x[1], reverse=True
            )[:3]
            top_regions_with_names = []
            for rid, count in top_regions:
                region = session.get(Region, rid)
                name = region.name if region else f"区域{rid}"
                top_regions_with_names.append({"id": rid, "name": name, "count": count})
            
            top_cameras = sorted(
                camera_stats.items(), key=lambda x: x[1], reverse=True
            )[:3]
            top_cameras_with_names = []
            for cid, count in top_cameras:
                camera = session.get(Camera, cid)
                name = camera.name if camera else f"摄像头{cid}"
                top_cameras_with_names.append({"id": cid, "name": name, "count": count})
            
            avg_response_time = self._calculate_avg_response_time(alarms)
            
            report = {
                "date": date.strftime("%Y-%m-%d"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "total_alarms": total_alarms,
                    "confirmed_count": confirmed_count,
                    "escalated_count": escalated_count,
                    "confirmation_rate": round(confirmed_count / total_alarms * 100, 1) if total_alarms > 0 else 0,
                    "avg_response_time_minutes": round(avg_response_time, 1)
                },
                "by_type": [
                    {
                        "type": t,
                        "label": TYPE_STATS_LABELS.get(t, t),
                        "count": c,
                        "percentage": round(c / total_alarms * 100, 1) if total_alarms > 0 else 0
                    }
                    for t, c in type_stats.items()
                ],
                "by_level": [
                    {"level": 0, "label": "弱提醒", "count": level_stats[0]},
                    {"level": 1, "label": "普通告警", "count": level_stats[1]},
                    {"level": 2, "label": "高优先/升级", "count": level_stats[2] + level_stats['other']}
                ],
                "top_regions": top_regions_with_names,
                "top_cameras": top_cameras_with_names,
                "top_alarm_types": [
                    {"type": t, "label": TYPE_STATS_LABELS.get(t, t), "count": c}
                    for t, c in top_alarm_types
                ],
                "recommendations": self._generate_recommendations(type_stats, region_stats),
                "alarm_details": [
                    {
                        "id": alarm.id,
                        "type": alarm.type,
                        "type_label": TYPE_STATS_LABELS.get(alarm.type, alarm.type),
                        "region_id": alarm.region_id,
                        "camera_id": alarm.camera_id,
                        "level": alarm.level,
                        "status": alarm.status,
                        "message": alarm.message or "",
                        "created_at": alarm.created_at.isoformat() if alarm.created_at else "",
                        "confirmed_at": alarm.confirmed_at.isoformat() if alarm.confirmed_at else ""
                    }
                    for alarm in alarms
                ]
            }
            
            self._save_report(report)
            return report
            
        finally:
            session.close()

    def _calculate_avg_response_time(self, alarms) -> float:
        """计算平均响应时间（分钟）。"""
        total_seconds = 0
        count = 0
        for alarm in alarms:
            if alarm.confirmed_at and alarm.created_at:
                diff = (alarm.confirmed_at - alarm.created_at).total_seconds()
                total_seconds += diff
                count += 1
        if count > 0:
            return total_seconds / 60 / count
        return 0

    def _generate_recommendations(self, type_stats, region_stats) -> list[str]:
        """生成改进建议。"""
        recommendations = []
        
        if type_stats.get("fight", 0) > 0:
            recommendations.append("检测到打架告警，建议加强该时段的监控巡逻")
        
        if type_stats.get("fire_smoke", 0) > 0:
            recommendations.append("检测到烟火告警，建议检查相关区域的消防设施")
        
        if type_stats.get("intrusion", 0) > type_stats.get("fatigue", 0) * 2:
            recommendations.append("入侵告警频率较高，建议检查防区设置是否合理")
        
        if type_stats.get("fatigue", 0) > 10:
            recommendations.append("疲劳提醒较多，建议提醒学生适当休息")
        
        top_region = max(region_stats.items(), key=lambda x: x[1], default=(None, 0))
        if top_region[1] > 5:
            recommendations.append(f"区域{top_region[0]}告警频繁，建议重点关注")
        
        if not recommendations:
            recommendations.append("今日监控运行正常，无异常情况")
        
        return recommendations

    def _save_report(self, report: dict) -> str:
        """保存日报到文件。"""
        filename = f"report_{report['date']}.json"
        path = os.path.join(self.report_dir, filename)
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info("[daily_report] 日报已保存: %s", path)
        return path

    def generate_markdown(self, date: Optional[datetime] = None) -> str:
        """生成Markdown格式的日报。"""
        report = self.generate_report(date)
        
        lines = []
        lines.append(f"# 📊 AI自习室监控日报")
        lines.append(f"**日期**: {report['date']}")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("## 📋 概览")
        lines.append(f"- **告警总数**: {report['summary']['total_alarms']}")
        lines.append(f"- **已确认**: {report['summary']['confirmed_count']}")
        lines.append(f"- **已升级**: {report['summary']['escalated_count']}")
        lines.append(f"- **确认率**: {report['summary']['confirmation_rate']}%")
        lines.append(f"- **平均响应时间**: {report['summary']['avg_response_time_minutes']} 分钟")
        lines.append("")
        lines.append("## 📈 告警类型分布")
        lines.append("| 类型 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for item in report['by_type']:
            lines.append(f"| {item['label']} | {item['count']} | {item['percentage']}% |")
        lines.append("")
        lines.append("## 🎯 告警等级分布")
        lines.append("| 等级 | 数量 |")
        lines.append("|------|------|")
        for item in report['by_level']:
            lines.append(f"| {item['label']} | {item['count']} |")
        lines.append("")
        lines.append("## 🏆 告警热点")
        lines.append("### 防区排行")
        lines.append("| 防区 | 告警数 |")
        lines.append("|------|--------|")
        for item in report['top_regions']:
            lines.append(f"| {item['name']} | {item['count']} |")
        lines.append("")
        lines.append("### 摄像头排行")
        lines.append("| 摄像头 | 告警数 |")
        lines.append("|--------|--------|")
        for item in report['top_cameras']:
            lines.append(f"| {item['name']} | {item['count']} |")
        lines.append("")
        lines.append("## 💡 改进建议")
        for rec in report['recommendations']:
            lines.append(f"- {rec}")
        lines.append("")
        lines.append("---")
        lines.append("*Generated by AI Study Room Monitoring System*")
        
        return "\n".join(lines)


_default_report_service: DailyReportService | None = None


def get_report_service() -> DailyReportService:
    """获取全局日报服务实例。"""
    global _default_report_service
    if _default_report_service is None:
        _default_report_service = DailyReportService()
    return _default_report_service