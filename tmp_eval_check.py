import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts.evaluate_models import build_report
print(build_report())
