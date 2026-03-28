import sys
import os

# Add relevant directories to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "brain"))
sys.path.append(os.path.join(os.getcwd(), "core"))
sys.path.append(os.path.join(os.getcwd(), "analysis"))
sys.path.append(os.path.join(os.getcwd(), "ml"))
sys.path.append(os.path.join(os.getcwd(), "strategies"))
sys.path.append(os.path.join(os.getcwd(), "bybit_specific"))

try:
    from brain.master_brain import MasterBrain
    print("✅ MasterBrain imported successfully!")
    
    # Attempt to initialize (dummy client if needed)
    # class MockClient: pass
    # brain = MasterBrain(MockClient())
    # print("✅ MasterBrain initialized successfully!")
    
except Exception as e:
    print(f"❌ MasterBrain import failed: {e}")
    import traceback
    traceback.print_exc()
