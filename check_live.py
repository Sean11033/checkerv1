import os
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

# 1. 取得多個 Room ID 並放入陣列
ROOM_IDs = []
if os.environ.get("DOUYIN_ROOM_ID"):
    ROOM_IDs.append(os.environ.get("DOUYIN_ROOM_ID"))
if os.environ.get("DOUYIN_ROOM_ID2"):
    ROOM_IDs.append(os.environ.get("DOUYIN_ROOM_ID2"))

webhook_env = os.environ.get("DISCORD_WEBHOOK_URL", "")
WEBHOOK_URLs = [url.strip() for url in webhook_env.split(",") if url.strip()]
STATE_FILE = "state.json"

def check_single_room(browser, room_id):
    """檢查單一直播間，為確保乾淨，每個房間開啟獨立的 context"""
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080}
    )
    page = context.new_page()
    
    api_result = {
        "intercepted": False,
        "is_live": False,
        "title": "",
        "nickname": ""
    }
    
    def handle_response(response):
        if "webcast/room/web/enter/" in response.url and response.status == 200:
            try:
                data = response.json()
                room_data = data.get("data", {}).get("data", [{}])[0]
                
                status = room_data.get("status")
                title = room_data.get("title", "")
                nickname = room_data.get("owner", {}).get("nickname", "未知主播")
                
                api_result["intercepted"] = True
                api_result["is_live"] = (status == 2)
                api_result["title"] = title
                api_result["nickname"] = nickname
                
                print(f"[{room_id} 網路攔截] 成功取得資料 - 狀態碼: {status}, 暱稱: {nickname}, 標題: {title}")
            except Exception as e:
                print(f"[{room_id} 網路攔截] JSON 解析錯誤: {e}")

    page.on("response", handle_response)
    
    try:
        live_url = f"https://live.douyin.com/{room_id}"
        page.goto(live_url, timeout=30000)
        page.wait_for_timeout(10000)
        
        if api_result["intercepted"]:
            return api_result["is_live"], api_result["title"], api_result["nickname"], ""
        else:
            error_msg = "未攔截到狀態 API，可能是遇到 WAF 攔截或網頁載入失敗"
            print(f"⚠️ [{room_id}] {error_msg}")
            return False, "", "", error_msg
            
    except Exception as e:
        error_msg = str(e)
        print(f"[{room_id}] Playwright 執行失敗: {error_msg}")
        return False, "", "", error_msg
    finally:
        context.close()

def send_discord_notify(room_id, title, nickname):
    live_url = f"https://live.douyin.com/{room_id}"
    display_title = title if title else "（未設定標題）"
    
    payload = {
        "content": f"🔴 **{nickname}** 開播啦！\n**標題**：{display_title}\n**傳送門**：{live_url}"
    }
    
    # 迴圈發送給所有設定的 Webhook
    for webhook in WEBHOOK_URLs:
        try:
            requests.post(webhook, json=payload, timeout=10)
            # 印出前 40 個字元作為 log 紀錄，避免完整 URL 洩漏
            print(f"[{room_id}] 已推播至 Webhook: {webhook[:40]}...") 
        except Exception as e:
            print(f"[{room_id}] ⚠️ 推播至 Webhook 失敗: {e}")

def main():
if not ROOM_IDs or not WEBHOOK_URLs: # 這裡改為 WEBHOOK_URLs
        print("缺少必要的環境變數！請確認 Github Secrets 設定。")
        return

    # 2. 讀取舊有狀態，並處理格式升級
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                loaded_state = json.load(f)
                # 偵測到舊版的單層級格式時，直接洗掉重置為空字典
                if "is_live" in loaded_state:
                    state = {}
                else:
                    state = loaded_state
            except json.JSONDecodeError:
                pass

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 3. 啟動共用的無頭瀏覽器，提升檢查效率
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        for room_id in ROOM_IDs:
            print(f"\n--- 開始檢查直播間: {room_id} ---")
            
            # 初始化該房間的狀態結構
            if room_id not in state:
                state[room_id] = {
                    "is_live": False,
                    "nickname": "",
                    "last_title": "",
                    "last_checked": "",
                    "last_error": ""
                }
                
            was_live = state[room_id].get("is_live", False)
            
            # 執行單間檢查
            is_live, title, nickname, error_msg = check_single_room(browser, room_id)
            
            print(f"[{room_id}] 目前狀態: {'直播中' if is_live else '未開播'} (上次狀態: {'直播中' if was_live else '未開播'})")

            # 狀態變更：從未開播轉為開播時才推播
            if is_live and not was_live:
                print(f"[{room_id}] 偵測到開播，發送 Discord 通知...")
                send_discord_notify(room_id, title, nickname)

            # 更新該房間的狀態字典
            state[room_id]["is_live"] = is_live
            state[room_id]["last_checked"] = current_time
            state[room_id]["last_error"] = error_msg
            if is_live:
                state[room_id]["nickname"] = nickname
                state[room_id]["last_title"] = title

        # 所有房間檢查完畢，關閉瀏覽器
        browser.close()

    # 4. 將多房間的詳細狀態寫入 JSON
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
