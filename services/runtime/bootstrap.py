import os
import runpy
import sys

sys.path.insert(0, "/opt/runtime")
module = "gateway.py" if os.environ["NEXUS_WORKLOAD_ROLE"] == "gateway" else "worker.py"
runpy.run_path("/opt/runtime/" + module, run_name="__main__")
