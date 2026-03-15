try:
    import pybit
    import pandas as pd
    import numpy as np
    import lightgbm as lgb
    import sklearn
    import sqlalchemy
    import indicators
    import config
    import ml_regime_detector
    import smart_entry_analyzer
    print("✅ All modules imported successfully!")
except ImportError as e:
    print(f"❌ Import failed: {e}")
except Exception as e:
    print(f"❌ Error during import: {e}")
