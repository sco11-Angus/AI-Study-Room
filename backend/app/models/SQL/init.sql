-- 创建业务数据库
CREATE DATABASE IF NOT EXISTS study_room
DEFAULT CHARACTER SET utf8mb4
DEFAULT COLLATE utf8mb4_unicode_ci;
USE study_room;

-- 表4-1 camera 摄像头
CREATE TABLE IF NOT EXISTS camera (
    id INT(11) PRIMARY KEY AUTO_INCREMENT COMMENT '摄像头ID',
    name VARCHAR(128) NOT NULL COMMENT '名称/安装位置',
    stream_url VARCHAR(256) NOT NULL COMMENT 'RTMP拉流地址',
    resolution VARCHAR(32) NOT NULL COMMENT '原始分辨率1920*1080，用于坐标映射',
    status TEXT NOT NULL COMMENT 'online/offline',
    created_at DATETIME NOT NULL COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='摄像头表';

-- 表4-3 app_user 自习用户
CREATE TABLE IF NOT EXISTS app_user (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '用户ID',
    nickname TEXT NOT NULL COMMENT '昵称',
    device_token TEXT NOT NULL COMMENT '弱提醒推送目标',
    created_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='自习用户表';

-- 表4-7 guard 安全员
CREATE TABLE IF NOT EXISTS guard (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '安全员ID',
    name TEXT NOT NULL COMMENT '姓名',
    dingtalk_id TEXT NOT NULL COMMENT '钉钉用户标识',
    role TEXT NOT NULL COMMENT 'primary/leader',
    priority INT NOT NULL COMMENT '升级顺序，越小越先通知'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='安全员表';

-- 表4-6 member 人员+人脸特征
CREATE TABLE IF NOT EXISTS member (
    member_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '会员ID',
    name TEXT NOT NULL COMMENT '姓名',
    feature TEXT NOT NULL COMMENT '128维人脸特征向量',
    created_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人员人脸会员表';

-- 表4-2 region 防区/座位（外键关联camera、app_user）
CREATE TABLE IF NOT EXISTS region (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '防区ID',
    camera_id INT NOT NULL COMMENT '所属摄像头，外键camera.id',
    user_id INT NULL COMMENT '所属用户，外键app_user.id',
    name VARCHAR(128) NOT NULL COMMENT '防区/座位名',
    type TEXT NOT NULL COMMENT 'danger_zone/seat',
    polygon TEXT NOT NULL COMMENT '顶点数组(原始分辨率像素)',
    x_distance INT NOT NULL COMMENT '安全距离阈值(像素)',
    y_stay_time INT NOT NULL COMMENT '允许危险停留时间(秒)',
    created_at DATETIME NOT NULL,
    -- 外键约束
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='防区座位表';
-- 文档指定索引 idx_region_camera
CREATE INDEX idx_region_camera ON region(camera_id);

-- 表4-4 seat_status 自习状态（外键app_user、region、guard）
CREATE TABLE IF NOT EXISTS seat_status (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL COMMENT '用户，外键app_user.id',
    region_id INT NOT NULL COMMENT '座位，外键region.id',
    guard_id INT NOT NULL COMMENT '管理员，外键guard.id',
    status TEXT NOT NULL COMMENT 'idle/studying/resting',
    updated_at DATETIME NOT NULL COMMENT '状态变更时间',
    -- 外键约束
    FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE CASCADE,
    FOREIGN KEY (guard_id) REFERENCES guard(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='座位自习状态表';

-- 表4-5 alarm_event 告警事件（外键region、camera）
CREATE TABLE IF NOT EXISTS alarm_event (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '告警ID',
    region_id INT NOT NULL COMMENT '触发防区/座位，外键region.id',
    camera_id INT NOT NULL COMMENT '触发摄像头(便于查询)，外键camera.id',
    type TEXT NOT NULL COMMENT 'intrusion/fire_smoke/occupy/fatigue/fight/face_recognition',
    snapshot_url TEXT NOT NULL COMMENT '抓拍图路径',
    clip_url TEXT NULL COMMENT '视频片段路径(任务书G)',
    face_match TEXT NOT NULL COMMENT '会员匹配结果：member:<id>/stranger',
    message TEXT NULL COMMENT '告警文字描述(任务书G4)',
    level INT NOT NULL COMMENT '0=弱提醒(私有)；1=普通；2+=升级、高优先(如打架)',
    status TEXT NOT NULL COMMENT 'pending/notified/confirmed/escalated',
    extra TEXT NOT NULL COMMENT '附加信息(如打架的vis_score/aud_score/fuse/涉事人员框)',
    created_at DATETIME NOT NULL COMMENT '触发时间',
    confirmed_at DATETIME NULL COMMENT '确认时间',
    -- 外键约束
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE CASCADE,
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='告警事件表';
-- 文档指定索引
CREATE INDEX idx_alarm_status ON alarm_event(status(20));;
CREATE INDEX idx_alarm_created ON alarm_event(created_at);
CREATE INDEX idx_alarm_region_type ON alarm_event(region_id, type);

-- 表4-8 notification_log 钉钉通知记录（外键alarm_event、guard）
CREATE TABLE IF NOT EXISTS notification_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    alarm_id INT NOT NULL COMMENT '关联告警，外键alarm_event.id',
    guard_id INT NOT NULL COMMENT '接收安全员，外键guard.id',
    stage TEXT NOT NULL COMMENT 'primary/escalated',
    sent_at DATETIME NOT NULL COMMENT '发送时间',
    ack_at DATETIME NOT NULL COMMENT '确认时间',
    -- 外键约束
    FOREIGN KEY (alarm_id) REFERENCES alarm_event(id) ON DELETE CASCADE,
    FOREIGN KEY (guard_id) REFERENCES guard(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钉钉通知记录表';