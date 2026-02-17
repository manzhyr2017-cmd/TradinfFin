from web_ui.database import db, init_db
import json
import os

init_db()

config_file = "bot_config.json"
if os.path.exists(config_file):
    with open(config_file, 'r') as f:
        file_config = json.load(f)
        
        # Force update auto_trade in DB
        current_db_config = db.get_setting("bot_config", {})
        if not current_db_config:
            current_db_config = {}
            
        current_db_config.update(file_config)
        db.save_setting("bot_config", current_db_config)
        
        print("✅ Config updated in DB from bot_config.json")
        print(f"   Auto Trade: {current_db_config.get('auto_trade')}")
else:
    print("❌ bot_config.json not found")
