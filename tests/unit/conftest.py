import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "roles", "mutex_common", "filter_plugins"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
