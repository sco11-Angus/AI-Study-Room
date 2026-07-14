-- 创建业务数据库
CREATE DATABASE IF NOT EXISTS study_room
DEFAULT CHARACTER SET utf8mb4
DEFAULT COLLATE utf8mb4_unicode_ci;
USE study_room;

-- 表4-1 camera 摄像头
CREATE TABLE IF NOT EXISTS camera (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '摄像头ID',
    name VARCHAR(128) NULL COMMENT '名称/安装位置',
    stream_url VARCHAR(256) NULL COMMENT 'RTMP拉流地址',
    resolution VARCHAR(32) NULL COMMENT '原始分辨率，如1920x1080，用于坐标映射',
    status TEXT NULL COMMENT 'online/offline',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='摄像头表';

-- 表4-3 app_user 自习用户
CREATE TABLE IF NOT EXISTS app_user (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '用户ID',
    nickname TEXT NULL COMMENT '昵称',
    device_token TEXT NULL COMMENT '弱提醒推送目标',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='自习用户表';

-- 表4-7 guard 安全员
CREATE TABLE IF NOT EXISTS guard (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '安全员ID',
    name VARCHAR(128) NULL COMMENT '姓名',
    dingtalk_id VARCHAR(128) NULL COMMENT '钉钉用户标识',
    role ENUM('primary', 'leader') NOT NULL DEFAULT 'primary' COMMENT 'primary/leader',
    priority INT NOT NULL DEFAULT 0 COMMENT '升级顺序，越小越先通知',
    INDEX idx_guard_role_priority (role, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='安全员表';

-- 表4-6 member 人员+人脸特征
CREATE TABLE IF NOT EXISTS member (
    member_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '会员ID',
    name TEXT NULL COMMENT '姓名',
    feature TEXT NULL COMMENT '128维人脸特征向量',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人员人脸会员表';

-- 表4-2 region 防区/座位
CREATE TABLE IF NOT EXISTS region (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '防区ID',
    camera_id INT NULL COMMENT '所属摄像头，外键camera.id',
    user_id INT NULL COMMENT '所属用户，外键app_user.id',
    name VARCHAR(128) NULL COMMENT '防区/座位名',
    type TEXT NULL COMMENT 'danger_zone/seat',
    polygon TEXT NULL COMMENT '顶点数组(原始分辨率像素)',
    x_distance INT NULL COMMENT '安全距离阈值(像素)',
    y_stay_time INT NULL COMMENT '允许危险停留时间(秒)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_region_camera (camera_id),
    INDEX idx_region_user (user_id),
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='防区座位表';

-- 表4-4 seat_status 自习状态
CREATE TABLE IF NOT EXISTS seat_status (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '状态ID',
    user_id INT NULL COMMENT '用户，外键app_user.id',
    region_id INT NULL COMMENT '座位，外键region.id',
    guard_id INT NULL COMMENT '安全员，外键guard.id',
    status TEXT NULL COMMENT 'idle/studying/resting',
    mode VARCHAR(16) NOT NULL DEFAULT 'demo' COMMENT 'demo/verified 自习会话模式',
    member_id INT NULL COMMENT 'verified 模式关联已录入人脸的成员',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '状态变更时间',
    INDEX idx_seat_region (region_id),
    INDEX idx_seat_user (user_id),
    FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE SET NULL,
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE CASCADE,
    FOREIGN KEY (guard_id) REFERENCES guard(id) ON DELETE SET NULL
    ,FOREIGN KEY (member_id) REFERENCES member(member_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='座位自习状态表';

-- 表4-4a seat_reservation 座位预约绑定
CREATE TABLE IF NOT EXISTS seat_reservation (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '预约绑定ID',
    region_id INT NOT NULL COMMENT '座位防区，唯一绑定一个预约成员',
    member_id INT NOT NULL COMMENT '预约成员，关联人脸会员表',
    enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用身份核验',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY idx_seat_reservation_region (region_id),
    INDEX idx_seat_reservation_member (member_id),
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE CASCADE,
    FOREIGN KEY (member_id) REFERENCES member(member_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='座位预约成员绑定表';

-- 表4-5 alarm_event 告警事件
CREATE TABLE IF NOT EXISTS alarm_event (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '告警ID',
    region_id INT NULL COMMENT '触发防区/座位，外键region.id',
    camera_id INT NULL COMMENT '触发摄像头(便于查询)，外键camera.id',
    type ENUM('intrusion', 'fire_smoke', 'occupy', 'fatigue', 'fight', 'quarrel', 'face_recognition', 'face_spoof', 'abnormal_sound') NOT NULL COMMENT '告警类型',
    snapshot_url VARCHAR(256) NULL COMMENT '抓拍图路径',
    clip_url VARCHAR(256) NULL COMMENT '视频片段路径(任务书G)',
    face_match VARCHAR(64) NULL COMMENT '会员匹配结果：member:<id>/stranger',
    message TEXT NULL COMMENT '告警文字描述(任务书G4)',
    level INT NOT NULL DEFAULT 1 COMMENT '0=弱提醒(私有)；1=普通；2+=升级、高优先',
    status ENUM('pending', 'notified', 'confirmed', 'escalated') NOT NULL DEFAULT 'pending' COMMENT '告警状态',
    extra TEXT NULL COMMENT '附加信息(如打架的vis_score/aud_score/fuse/涉事人员框)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '触发时间',
    confirmed_at DATETIME NULL COMMENT '确认时间',
    INDEX idx_alarm_status (status),
    INDEX idx_alarm_created (created_at),
    INDEX idx_alarm_region_type (region_id, type),
    INDEX idx_alarm_camera (camera_id),
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE SET NULL,
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='告警事件表';

-- 表4-8 notification_log 钉钉通知记录
CREATE TABLE IF NOT EXISTS notification_log (
    id INT PRIMARY KEY AUTO_INCREMENT COMMENT '通知ID',
    alarm_id INT NULL COMMENT '关联告警，外键alarm_event.id',
    guard_id INT NULL COMMENT '接收安全员，外键guard.id',
    stage ENUM('primary', 'escalated') NOT NULL COMMENT 'primary/escalated',
    sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
    ack_at DATETIME NULL COMMENT '确认时间',
    INDEX idx_notify_alarm (alarm_id),
    INDEX idx_notify_guard (guard_id),
    FOREIGN KEY (alarm_id) REFERENCES alarm_event(id) ON DELETE CASCADE,
    FOREIGN KEY (guard_id) REFERENCES guard(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钉钉通知记录表';

-- 初始化默认数据
INSERT IGNORE INTO camera (id, name, stream_url, resolution, status) VALUES
(1, '默认摄像头', '', '', 'offline'),
(5, '云服务器摄像头', 'rtmp://49.233.71.82:9090/live/test', '1280x720', 'online');

INSERT IGNORE INTO guard (id, name, role, priority) VALUES
(1, '默认安全员', 'primary', 0),
(2, '主管', 'leader', 1);
