
import os
import re

typing_symbols = ["Optional", "List", "Dict", "Tuple", "Any", "Union"]

def check_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    missing = []
    for symbol in typing_symbols:
        # Check if symbol is used: e.g. Optional[str], List[Any]
        if re.search(fr'\b{symbol}\[', content):
            # Check if symbol is imported from typing
            if not re.search(fr'from typing import.*?\b{symbol}\b', content) and not re.search(fr'import typing', content):
                missing.append(symbol)
    
    if missing:
        print(f"File: {filepath} is missing typing imports: {missing}")
        return True
    return False

root_dir = "d:\\Projects\\Trading\\grid_bot_v2"
found_any = False
for root, dirs, files in os.walk(root_dir):
    if 'venv' in dirs:
        dirs.remove('venv')  # don't visit venv folders
    for file in files:
        if file.endswith(".py"):
            try:
                if check_file(os.path.join(root, file)):
                    found_any = True
            except Exception as e:
                print(f"Error checking {file}: {e}")

if not found_any:
    print("No missing typing imports found in grid_bot_v2.")
