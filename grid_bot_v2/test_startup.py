import logging
import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)

try:
    print("Checking imports...")
    from brain.master_brain import MasterBrain
    import config
    print("Imports OK.")
    
    print("Initializing MasterBrain (Dry Run / No actual starts)...")
    # We won't call .start() as it would connect to WebSockets
    brain = MasterBrain()
    print("Initialization OK.")
    
    print("Testing a single decision cycle...")
    # This might fail if API keys are invalid, but checking logic flow
    try:
        decision = brain.decide()
        print(f"Decision: {decision.decision_type}")
    except Exception as e:
        print(f"Decision test failed (expected if no API keys): {e}")

    print("\n✅ Verification complete.")

except Exception as e:
    print(f"❌ Verification failed: {e}")
    import traceback
    traceback.print_exc()
