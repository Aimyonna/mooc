"""
MOOC 登录凭证生成器
==================
打开 icourse163.org，引导用户扫码登录，
成功后将浏览器 Cookie 持久化到 cookies.json。
"""
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from config import COOKIE_FILE, BASE_DIR, HEADLESS, get_logger

# ============================================================
# 日志
# ============================================================
logger = get_logger("cookie")


# ============================================================
# Cookie 保存
# ============================================================
def save_cookies(driver: webdriver.Chrome) -> None:
    cookies = driver.get_cookies()
    cookie_path = BASE_DIR / COOKIE_FILE
    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info("Cookie 已保存到 %s（%d 条）", COOKIE_FILE, len(cookies))


# ============================================================
# 登录主流程
# ============================================================
def generate_cookie() -> None:
    logger.info("=" * 50)
    logger.info("MOOC 登录凭证生成器启动")
    logger.info("=" * 50)

    options = webdriver.ChromeOptions()
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920,1080")
    if HEADLESS:
        logger.warning("无头模式下无法扫码登录，已忽略 HEADLESS 配置")
        # 不启用 headless：扫码登录必须有可见浏览器窗口

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)

    logger.info("Chrome 启动完成")
    print("\n>>> 请在浏览器中扫码登录，完成后回到此窗口按回车 <<<\n")

    driver.get("https://www.icourse163.org/")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    # ---- 第一步：点击主页"登录"按钮 ----
    try:
        main_login_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//div[contains(@class,'login')] | //*[contains(text(),'登录')]"
        )))
        main_login_btn.click()
        logger.info("已点击主页登录按钮")
    except Exception:
        logger.warning("主页登录按钮（主XPath）点击失败，尝试备用选择器")
        try:
            main_login_alt = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//div[contains(text(), '登录')]"
            )))
            main_login_alt.click()
            logger.info("已通过备用选择器点击登录按钮")
        except Exception:
            logger.error("无法找到登录按钮，网站 DOM 可能已更新")
            driver.quit()
            raise RuntimeError("登录按钮定位失败，请更新 XPath 后重试")

    # ---- 第二步：切换到二维码登录 ----
    # 等待登录弹窗渲染后点击二维码入口
    try:
        qr_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//img[contains(@alt,'二维码') or contains(@class,'qrcode')]"
        )))
        qr_btn.click()
        logger.info("已切换到二维码登录")
        # 等待二维码图片渲染
        wait.until(EC.presence_of_element_located((
            By.XPATH, "//img[contains(@class,'qrcode')] | //canvas[contains(@class,'qr')]"
        )))
    except Exception:
        logger.warning("二维码按钮（主XPath）失败，尝试备用选择器")
        alt_selectors = [
            "//img[contains(@alt, '二维码') or contains(@title, '二维码')]",
            "//div[contains(@class, 'qrcode')]//img",
            "//*[contains(text(), '扫码登录')]",
            "//*[contains(text(), '二维码登录')]",
        ]
        matched = False
        for sel in alt_selectors:
            try:
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                btn.click()
                logger.info("备用选择器命中: %s", sel)
                matched = True
                break
            except Exception:
                continue
        if not matched:
            logger.warning("所有二维码选择器均未命中，可能已默认展示二维码")

    # ---- 等待用户扫码（自动检测） ----
    logger.info("等待扫码登录（每 3 秒检测一次，最多等 5 分钟）…")
    print("\n>>> 请在浏览器中扫码登录，脚本会自动检测 <<<\n")

    deadline = __import__("time").time() + 300  # 5 分钟超时
    logged_in = False
    while __import__("time").time() < deadline:
        __import__("time").sleep(3)
        # 检测策略：cookie 中出现 NTESSTUDIO（网易通行证）
        try:
            cookies = driver.get_cookies()
            cookie_names = {c.get("name", "") for c in cookies}
            if "NTESSTUDYSI" in cookie_names or "STUDY_SESS" in cookie_names:
                logged_in = True
                break
        except Exception:
            pass

    if not logged_in:
        logger.warning("5 分钟未检测到登录，最后尝试保存当前 cookie")
    else:
        logger.info("检测到登录成功！")

    # ---- 保存 Cookie ----
    save_cookies(driver)
    driver.quit()
    logger.info("登录凭证生成完毕")


if __name__ == "__main__":
    generate_cookie()
