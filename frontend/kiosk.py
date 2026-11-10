import os
os.environ["SMART_LOCKER_UI_MODE"] = "KIOSK"
from frontend.app import main

if __name__ == "__main__":
    main()

