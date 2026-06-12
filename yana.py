"""Entry point — run from project root: python yana.py [args]"""
import sys
import runpy
from pathlib import Path

orchestrator = Path(__file__).parent / "orchestrator"
sys.path.insert(0, str(orchestrator))

# Change working directory so relative paths inside main.py resolve correctly
import os
os.chdir(orchestrator)

runpy.run_path(str(orchestrator / "main.py"), run_name="__main__")
