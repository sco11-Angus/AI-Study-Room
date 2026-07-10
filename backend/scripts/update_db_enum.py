import pymysql

conn = pymysql.connect(
    host='127.0.0.1', port=3306,
    user='root', password='zx20060715',
    database='study_room', charset='utf8mb4'
)
cursor = conn.cursor()

enum_values = ["intrusion", "fire_smoke", "occupy", "fatigue", "fight", "face_recognition"]
quoted_values = ", ".join([f"'{v}'" for v in enum_values])
sql = f"ALTER TABLE alarm_event MODIFY COLUMN type ENUM({quoted_values}) NOT NULL"

try:
    cursor.execute(sql)
    conn.commit()
    print('Database updated successfully')
except Exception as e:
    print(f'Error: {e}')
    conn.rollback()
finally:
    cursor.close()
    conn.close()