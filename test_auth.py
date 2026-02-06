import sys
import os
import logging
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)

try:
    from web_ui.database import init_db, create_user, get_user, verify_password
    print("Imports successful")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def test_auth():
    print("Initializing DB...")
    try:
        init_db()
        print("DB Initialized.")
    except Exception as e:
        print(f"DB Init failed: {e}")
        return

    print("Creating User 'admin'...")
    try:
        if create_user("admin", "123456"):
            print("User created.")
        else:
            print("User already exists (or failed).")
    except Exception as e:
        print(f"User creation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print("Verifying User...")
    user = get_user("admin")
    if user:
        print(f"User found: {user[1]}")
        if verify_password("123456", user[2]):
            print("Password verification SUCCESS.")
        else:
            print("Password verification FAILED.")
    else:
        print("User NOT found.")

if __name__ == "__main__":
    test_auth()
