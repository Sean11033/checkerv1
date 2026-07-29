import os
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

ROOM_ID = os.environ.get("DOUYIN_ROOM_ID")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATE_FILE = "state.json"

def get_live_info():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        try:
            live_url = f"https://live.douyin.com/{ROOM_ID}"
            page.goto(live_url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            
            has_video = page.locator("video").count() > 0
            title = page.title()
            nickname = title.split("的")[0] if "的" in title else "主播"
            is_offline_text = page.locator("text='直播已結束'").count() > 0
            
            is_live = has_video and not is_offline_text
            
            return is_live, title, nickname, ""
            
        except Exception as e:
            error_msg = str(e)
            print(f"Playwright 解析失敗: {error_msg}")
            return False, "", "", error_msg
        finally:
            context.close()
            browser.close()

def send_discord_notify(title, nickname):
    live_url = f"https://live.douyin.com/{ROOM_ID}"
    payload = {
        "content": f"🔴 **{nickname}** 開播啦！\n**標題**：{title}\n**傳送門**：{live_url}"
    }
    requests.post(WEBHOOK_URL, json=payload)

def main():
    if not ROOM_ID or not WEBHOOK_URL:
        print("缺少必要的環境變數！")
        return

    # 初始化預設狀態
    state = {
        "is_live": False,
        "nickname": "",
        "last_title": "",
        "last_checked": "",
        "last_error": ""
    }

    # 讀取舊有狀態
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                state.update(json.load(f))
            except json.JSONDecodeError:
                pass

    was_live = state.get("is_live", False)
    
    # 執行檢查
    is_live, title, nickname, error_msg = get_live_info()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"目前狀態: {'直播中' if is_live else '未開播'} (上次狀態: {'直播中' if was_live else '未開播'})")

    # 狀態變更：從未開播轉為開播時才發送通知
    if is_live and not was_live:
        print("偵測到開播，發送 Discord 通知...")
        send_discord_notify(title, nickname)

    # 更新狀態字典
    state["is_live"] = is_live
    state["last_checked"] = current_time
    state["last_error"] = error_msg
    if is_live:
        state["nickname"] = nickname
        state["last_title"] = title

    # 將詳細狀態寫入 JSON
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
