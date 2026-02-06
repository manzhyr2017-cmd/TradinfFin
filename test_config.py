import os
import sys
import unittest
from unittest.mock import patch

# Add project root to path
sys.path.append(os.getcwd())

from web_ui.server import load_config, BotConfig

class TestConfig(unittest.TestCase):
    def test_env_priority(self):
        """Test that Environment Variables override config file"""
        
        # 1. Set a fake env var that is different from bot_config.json
        test_key = "TEST_ENV_KEY_12345"
        os.environ["BYBIT_API_KEY"] = test_key
        
        # 2. Load config
        config = load_config()
        
        # 3. Assert
        print(f"Loaded Key: {config.api_key}")
        print(f"Expected Key: {test_key}")
        
        self.assertEqual(config.api_key, test_key, "Environment variable should take precedence over config file")
        
        # Clean up
        del os.environ["BYBIT_API_KEY"]

if __name__ == '__main__':
    unittest.main()
