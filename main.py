"""
MOOC 课程入库 — 纯 DB 加载器
============================
读 discover.py 产出的 courses.json，批量写入 course_info 表。
不开浏览器。表主键为 courseid（varchar(50) 自然主键，重跑去重），url 保留 UNIQUE。
"""
import json

import pymysql

from config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_CHARSET,
    BASE_DIR, get_logger,
)

logger = get_logger("main")


def main() -> None:
    logger.info("=" * 50)
    logger.info("MOOC 课程入库启动（纯 DB 加载器）")
    logger.info("=" * 50)

    # ---- 读 courses.json ----
    json_path = BASE_DIR / "courses.json"
    if not json_path.exists():
        logger.error("courses.json 不存在，请先运行 discover.py")
        raise FileNotFoundError(str(json_path))
    with open(json_path, "r", encoding="utf-8") as f:
        courses = json.load(f)
    logger.info("待入库课程: %d 门", len(courses))

    # ---- 连接数据库 ----
    db = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset=DB_CHARSET,
    )
    cursor = db.cursor()
    logger.info("数据库连接成功: %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)

    # ---- 建表（匹配既有表结构：courseid varchar(50) 主键） ----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS course_info(
            courseid VARCHAR(50)  NOT NULL PRIMARY KEY,
            url      VARCHAR(255) UNIQUE,
            cCourse  VARCHAR(255),
            cCollege VARCHAR(255),
            cTeacher VARCHAR(255),
            cTeam    TEXT,
            cCount   INT UNSIGNED DEFAULT 0,
            cBrief   TEXT
        );
    """)
    db.commit()
    logger.info("表 course_info 就绪（主键 courseid）")

    # ---- 清空旧数据，保证表内只有本次爬取结果 ----
    cursor.execute("TRUNCATE TABLE course_info")
    db.commit()
    logger.info("已清空 course_info 旧数据")

    # ---- 批量入库 ----
    sql = """
        INSERT INTO course_info
            (courseid, url, cCourse, cCollege, cTeacher, cTeam, cCount, cBrief)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            url      = VALUES(url),
            cCourse  = VALUES(cCourse),
            cCollege = VALUES(cCollege),
            cTeacher = VALUES(cTeacher),
            cTeam    = VALUES(cTeam),
            cCount   = VALUES(cCount),
            cBrief   = VALUES(cBrief)
    """
    success = 0
    for i, c in enumerate(courses, 1):
        try:
            cursor.execute(sql, (
                c["courseId"], c["url"], c["cCourse"], c["cCollege"],
                c["cTeacher"], c["cTeam"], c["cCount"], c["cBrief"],
            ))
            success += 1
        except pymysql.MySQLError as e:
            logger.error("[%d/%d] 入库失败 courseid=%s: %s",
                         i, len(courses), c.get("courseId"), e)
    db.commit()

    cursor.execute("SELECT COUNT(*) FROM course_info")
    total = cursor.fetchone()[0]
    db.close()

    logger.info("=" * 50)
    logger.info("入库完成: 本次 %d / %d，表内共 %d 门", success, len(courses), total)
    logger.info("=" * 50)
    print(f"\n入库 {success}/{len(courses)} 门，course_info 表共 {total} 门")


if __name__ == "__main__":
    main()
