"""无CMD窗口启动入口"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import TPadServerGUI

if __name__ == "__main__":
    app = TPadServerGUI()
    app.run()
