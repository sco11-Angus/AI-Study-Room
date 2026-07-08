"""插入测试数据，便于联调。"""
from datetime import datetime
from sqlalchemy.orm import Session
from .database import SessionLocal
from .entities import Camera, AppUser, Guard, Region, Member


def seed_data():
    """插入测试数据。"""
    db: Session = SessionLocal()
    
    try:
        existing_camera = db.query(Camera).first()
        if existing_camera:
            print("测试数据已存在，跳过插入")
            return
        
        camera = Camera(
            name="测试摄像头-自习室A区",
            stream_url="rtmp://49.233.71.82:9090/live/test",
            resolution="1920x1080",
            status="online",
            created_at=datetime.utcnow()
        )
        db.add(camera)
        db.flush()
        
        app_user = AppUser(
            nickname="测试学生",
            device_token="test_device_token_001",
            created_at=datetime.utcnow()
        )
        db.add(app_user)
        db.flush()
        
        guard = Guard(
            name="张安全",
            dingtalk_id="test_dingtalk_id_001",
            role="primary",
            priority=0
        )
        db.add(guard)
        db.flush()
        
        region1 = Region(
            camera_id=camera.id,
            user_id=None,
            name="危险区域-门口",
            type="danger_zone",
            polygon="[[100,100],[300,100],[300,400],[100,400]]",
            x_distance=50,
            y_stay_time=10,
            created_at=datetime.utcnow()
        )
        
        region2 = Region(
            camera_id=camera.id,
            user_id=app_user.id,
            name="座位-A01",
            type="seat",
            polygon="[[400,200],[600,200],[600,400],[400,400]]",
            x_distance=30,
            y_stay_time=300,
            created_at=datetime.utcnow()
        )
        
        region3 = Region(
            camera_id=camera.id,
            user_id=None,
            name="座位-A02",
            type="seat",
            polygon="[[650,200],[850,200],[850,400],[650,400]]",
            x_distance=30,
            y_stay_time=300,
            created_at=datetime.utcnow()
        )
        
        db.add_all([region1, region2, region3])
        
        member = Member(
            name="测试会员",
            feature="[]",
            created_at=datetime.utcnow()
        )
        db.add(member)
        
        db.commit()
        
        print("测试数据插入成功:")
        print(f"  - 摄像头: {camera.name} (id={camera.id})")
        print(f"  - 用户: {app_user.nickname} (id={app_user.id})")
        print(f"  - 安全员: {guard.name} (id={guard.id}, role={guard.role})")
        print(f"  - 防区: {region1.name}, {region2.name}, {region3.name}")
        print(f"  - 会员: {member.name} (id={member.member_id})")
        
    except Exception as e:
        db.rollback()
        print(f"插入测试数据失败: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()