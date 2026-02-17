import asyncio
import os
import logging
from dotenv import load_dotenv
from telegram import Bot
from telegram.request import HTTPXRequest

# Load env variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TelegramDebugger")

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    print(f"🔑 Token: {token[:10]}...")
    print(f"VX Proxy: {proxy}")

    try:
        # Configure Request
        request = None
        if proxy:
            request = HTTPXRequest(proxy_url=proxy)
        
        # Init Bot
        bot = Bot(token=token, request=request)
        
        # 1. Check Identity
        me = await bot.get_me()
        print(f"\n✅ Bot Connected Successfully!")
        print(f"🤖 Bot Name: {me.first_name}")
        print(f"📧 Username: @{me.username}")
        
        print("\n🔍 Checking for updates (Control+C to stop)...")
        print("👉 Please send a message to the bot or your group NOW.")
        
        # 2. Get Updates Loop
        offset = 0
        while True:
            try:
                updates = await bot.get_updates(offset=offset, timeout=10)
                for u in updates:
                    offset = u.update_id + 1
                    
                    if u.message:
                        chat = u.message.chat
                        print(f"\n📩 Message Received!")
                        print(f"   Shape: {chat.type}")
                        print(f"   Title: {chat.title}")
                        print(f"   ID: {chat.id}  <-- COPY THIS ID")
                        print(f"   Text: {u.message.text}")
                        
                    elif u.channel_post:
                        chat = u.channel_post.chat
                        print(f"\n📢 Channel Post Received!")
                        print(f"   Title: {chat.title}")
                        print(f"   ID: {chat.id}  <-- COPY THIS ID")
                        
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)
                
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"\n❌ Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
