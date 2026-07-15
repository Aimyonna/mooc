"""
MOOC 课程发现 — 纯 Selenium（多频道并行）
==========================================
频道页 → 点「全部课程」→ 点「正在进行」筛选 → 翻页（下一页）逐页抓卡片。
卡片读 cCourse/cCollege/cTeacher；点 h3 开新 tab 进详情页读
url/courseId + cTeam/cCount/cBrief。零 API、零 JS 注入。

多管道 = 多频道并行：CHANNELS 里每个频道各开一个 driver 并行爬。

输出：courses.json（main.py 入库用）
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from config import (
    COOKIE_FILE, BASE_DIR, HEADLESS, chrome_service, get_logger,
)

logger = get_logger("discover")

# ============================================================
# 配置
# ============================================================
CHANNELS = [
    {"id": 2001, "name": "一流课程"},
]
# 分页安全上限（实际按"到末页"自动停）。
MAX_PAGES = 20


# ============================================================
# 1. WebDriver 工厂
# ============================================================
def create_driver() -> webdriver.Chrome:
    """创建 WebDriver，注入 cookie。"""
    options = webdriver.ChromeOptions()
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920,1080")
    if HEADLESS:
        options.add_argument("--headless=new")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(service=chrome_service(), options=options)
    driver.get("https://www.icourse163.org/")
    time.sleep(2)

    cookie_path = BASE_DIR / COOKIE_FILE
    if cookie_path.exists():
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        loaded = 0
        for c in cookies:
            c.pop("sameSite", None)
            c.pop("expiry", None)
            try:
                driver.add_cookie(c)
                loaded += 1
            except Exception:
                pass
        logger.info("Cookie 注入: %d/%d 条", loaded, len(cookies))
    return driver


# ============================================================
# 2. 工具
# ============================================================
def parse_course_id(url: str) -> str:
    """从 /course/{schoolSN}-{courseId} 解析 courseId（数字字符串，如 "17002"）。"""
    m = re.search(r"/course/[^/]+-(\d+)", url)
    return m.group(1) if m else ""


def click_text(driver: webdriver.Chrome, text: str) -> bool:
    """点击文本精确匹配的元素（XPath），找不到返回 False。"""
    return driver.execute_script(f"""
        var xp=document.evaluate('//*[normalize-space(text())="{text}"]',
            document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);
        var e=xp.singleNodeValue; if(!e) return false;
        e.scrollIntoView({{block:'center'}}); e.click(); return true;
    """)


def find_cards(driver: webdriver.Chrome) -> list:
    """当前页 #channel-course-list 里的课程卡。"""
    return driver.find_elements(
        By.CSS_SELECTOR, "#channel-course-list div.commonCourseCardItem")


def scrape_card(card_el) -> dict:
    """从卡片 DOM 读 cCourse/cCollege/cTeacher + status（status 仅用于日志校验筛选）。"""
    return card_el._parent.execute_script("""
        var card=arguments[0];
        var h3=card.querySelector('h3');
        var p = h3 ? h3.nextElementSibling : null;       // p = 院校
        var d = p ? p.nextElementSibling : null;          // div = 主讲教师
        var t = card.innerText;
        var sm = t.match(/(进行至第\\d+周|进行中|已结束|即将开课|\\d{4}-\\d\\d-\\d\\d\\s*开课)/);
        return {
            course:  h3 ? h3.innerText.trim() : '',
            college: p ? p.innerText.trim() : '',
            teacher: d ? d.innerText.trim() : '',
            status:  sm ? sm[0] : ''
        };
    """, card_el)


def first_card_name(driver: webdriver.Chrome) -> str:
    """当前页第一张卡的课程名（用于判断翻页是否生效）。"""
    cards = find_cards(driver)
    if not cards:
        return ""
    return scrape_card(cards[0])["course"]


# ============================================================
# 3. 详情页字段（在新 tab 里读）
# ============================================================
def _collect_teacher_page(driver: webdriver.Chrome) -> set[str]:
    """当前教师滑块页的全部教师姓名去重集合。"""
    names: set[str] = set()
    try:
        container = driver.find_element(By.CSS_SELECTOR, ".m-teachers_teacher-list")
        items = container.find_elements(By.CSS_SELECTOR, ".um-list-slider_con_item")
        for item in items:
            try:
                img = item.find_element(By.TAG_NAME, "img")
                name = img.get_attribute("alt").strip()
                if name and name != "图片":
                    names.add(name)
            except Exception:
                pass
    except Exception:
        pass
    return names


def _get_all_teachers(driver: webdriver.Chrome) -> str:
    """教师团队（含滑块翻页），返回中顿号拼接字符串。"""
    all_names: set[str] = set()
    all_names |= _collect_teacher_page(driver)

    # 滑块翻页按钮
    btn_xpath = "//div[contains(@class,'teacher')]//div[contains(@class,'slider')]//span"
    try:
        buttons = driver.find_elements(By.XPATH, btn_xpath)
        if buttons:
            driver.execute_script("arguments[0].click();", buttons[0])
            time.sleep(0.8)
            all_names |= _collect_teacher_page(driver)

            while True:
                buttons = driver.find_elements(By.XPATH, btn_xpath)
                if len(buttons) == 2:
                    driver.execute_script("arguments[0].click();", buttons[1])
                    time.sleep(0.8)
                    all_names |= _collect_teacher_page(driver)
                else:
                    break
    except Exception:
        pass

    return "，".join(all_names) if all_names else ""


def scrape_detail(driver: webdriver.Chrome) -> dict:
    """在课程详情页读 cTeam / cCount / cBrief。"""
    cCount = driver.execute_script(
        "var m=document.body.innerText.match(/(\\d[\\d,]*)\\s*人参加/);"
        "return m?parseInt(m[1].replace(/,/g,''),10):0;"
    ) or 0

    cTeam = _get_all_teachers(driver)

    cBrief = driver.execute_script("""
        var m=document.querySelector('meta[name=description]'); if(!m) return '';
        var c=m.content; var i=c.indexOf('spContent=');
        if(i>=0) c=c.slice(i+10);
        return c.replace(/,中国大学MOOC\\(慕课\\)$/, '').trim();
    """) or ""

    return {"cTeam": cTeam, "cCount": int(cCount), "cBrief": cBrief}


# ============================================================
# 4. 单频道爬取
# ============================================================
def crawl_channel(channel: dict) -> list[dict]:
    """爬一个频道「全部课程 → 正在进行」的全部页。"""
    ch_id, ch_name = channel["id"], channel["name"]
    driver = create_driver()
    wait = WebDriverWait(driver, 15)
    records: list[dict] = []

    try:
        driver.get(f"https://www.icourse163.org/channel/{ch_id}.htm")
        time.sleep(8)
        logger.info("[%s] 打开频道页", ch_name)

        # 点「全部课程」+「正在进行」
        click_text(driver, "全部课程"); time.sleep(2)
        click_text(driver, "正在进行"); time.sleep(4)
        logger.info("[%s] 已筛选「正在进行」，首页卡片 %d 张",
                    ch_name, len(find_cards(driver)))

        for page in range(1, MAX_PAGES + 1):
            cards = find_cards(driver)
            if not cards:
                logger.warning("[%s] 第%d页无卡片", ch_name, page)
                break
            name_before = scrape_card(cards[0])["course"]
            logger.info("[%s] 第%d页: %d 张（首卡: %s）",
                        ch_name, page, len(cards), name_before)

            for idx in range(len(cards)):
                cards = find_cards(driver)          # 刷新，避免 stale
                if idx >= len(cards):
                    break
                card = cards[idx]
                f = scrape_card(card)

                # 点 h3 开新 tab 进详情
                try:
                    driver.execute_script(
                        "arguments[0].querySelector('h3').click();", card)
                    wait.until(lambda d: len(d.window_handles) > 1)
                    driver.switch_to.window(driver.window_handles[-1])
                    wait.until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[class*='course-title']")))
                except Exception as e:
                    logger.warning("[%s] 第%d页第%d张跳转失败: %s",
                                   ch_name, page, idx + 1, e)
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue

                detail_url = driver.current_url.split("?")[0]
                courseId = parse_course_id(detail_url)
                d = scrape_detail(driver)

                records.append({
                    "courseId": courseId,
                    "url": detail_url,
                    "cCourse": f["course"],
                    "cCollege": f["college"],
                    "cTeacher": f["teacher"],
                    "cTeam": d["cTeam"],
                    "cCount": d["cCount"],
                    "cBrief": d["cBrief"],
                })
                logger.info("[%s] %d/%d  %s | %s | %s | %d人",
                            ch_name, idx + 1, len(cards),
                            f["course"], f["status"], f["college"], d["cCount"])

                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                time.sleep(0.3)

            # 翻下一页
            if not click_text(driver, "下一页"):
                logger.info("[%s] 无「下一页」，结束（共%d页）", ch_name, page)
                break
            try:
                WebDriverWait(driver, 8).until(
                    lambda d: first_card_name(d) and first_card_name(d) != name_before)
            except TimeoutException:
                logger.info("[%s] 翻页未生效，到末页（共%d页）", ch_name, page)
                break
            time.sleep(1)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info("[%s] 完成: %d 门", ch_name, len(records))
    return records


# ============================================================
# 5. 主入口（多频道并行）
# ============================================================
def main() -> None:
    logger.info("=" * 50)
    logger.info("MOOC 课程发现（纯 Selenium + 多频道并行）")
    for ch in CHANNELS:
        logger.info("  - [id=%d] %s", ch["id"], ch["name"])
    logger.info("  分页上限: %d 页/频道（到末页自动停）", MAX_PAGES)
    logger.info("=" * 50)

    # 清空旧 courses.json
    json_path = BASE_DIR / "courses.json"
    json_path.write_text("[]", encoding="utf-8")

    all_courses: list[dict] = []
    seen: set[str] = set()

    with ThreadPoolExecutor(max_workers=len(CHANNELS)) as pool:
        futures = {pool.submit(crawl_channel, ch): ch for ch in CHANNELS}
        for fut in as_completed(futures):
            ch = futures[fut]
            try:
                for c in fut.result():
                    if c["courseId"] and c["courseId"] not in seen:
                        seen.add(c["courseId"])
                        all_courses.append(c)
            except Exception as e:
                logger.error("[%s] 频道爬取异常: %s", ch["name"], e)

    json_path = BASE_DIR / "courses.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_courses, f, ensure_ascii=False, indent=2)

    logger.info("=" * 50)
    logger.info("完成: %d 门课程 → courses.json", len(all_courses))
    logger.info("=" * 50)
    print(f"\n{len(all_courses)} 个课程已写入 courses.json")


if __name__ == "__main__":
    main()
