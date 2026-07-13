-- ============================================================
-- 告警/通知表自动清理
-- 规则：当 alarm_event 或 notification_log 的行数「超过 500 条」时，
--       直接清空整张表（删到 0 条），防止表无限膨胀拖慢查询。
--
-- 实现：存储过程 sp_cleanup_events() 判断阈值并清理，
--       事件 ev_cleanup_events 每 10 分钟自动调用一次。
--
-- 依赖：MySQL event_scheduler 需为 ON。
--       检查： SHOW VARIABLES LIKE 'event_scheduler';
--       开启： SET GLOBAL event_scheduler = ON;   （重启失效）
--       永久： 在 my.ini [mysqld] 下加 event_scheduler=ON
--
-- 用法：在 study_room 库执行本文件一次即可长期生效。
--   mysql -uroot -p study_room < backend/app/models/SQL/cleanup_events.sql
-- ============================================================

USE study_room;

-- 幂等：可重复执行本文件
DROP EVENT IF EXISTS ev_cleanup_events;
DROP PROCEDURE IF EXISTS sp_cleanup_events;

DELIMITER $$

CREATE PROCEDURE sp_cleanup_events()
BEGIN
    -- 关闭外键检查，避免 alarm_event 与 notification_log 的外键顺序问题
    SET FOREIGN_KEY_CHECKS = 0;

    -- alarm_event 超过 500 条 → 清空（会级联清掉关联的 notification_log）
    IF (SELECT COUNT(*) FROM alarm_event) > 500 THEN
        DELETE FROM alarm_event;
    END IF;

    -- notification_log 超过 500 条 → 清空
    IF (SELECT COUNT(*) FROM notification_log) > 500 THEN
        DELETE FROM notification_log;
    END IF;

    SET FOREIGN_KEY_CHECKS = 1;
END$$

DELIMITER ;

-- 每 10 分钟检查一次；创建后立即先跑一次
CREATE EVENT ev_cleanup_events
    ON SCHEDULE EVERY 10 MINUTE
    STARTS CURRENT_TIMESTAMP
    ON COMPLETION PRESERVE
    ENABLE
    COMMENT '告警/通知表超过500条自动清空'
    DO
        CALL sp_cleanup_events();

-- 立即执行一次，应用当前数据
CALL sp_cleanup_events();
