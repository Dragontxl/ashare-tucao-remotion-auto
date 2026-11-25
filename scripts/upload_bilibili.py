# -*- coding: utf-8 -*-
"""B站上传入口（薄封装，实际实现在 bilibili_uploader.py）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bilibili_uploader import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
