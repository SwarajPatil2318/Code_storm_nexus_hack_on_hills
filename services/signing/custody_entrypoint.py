import runpy
import sys

sys.path[:0] = ["/opt/nexus", "/opt/vendor"]
runpy.run_module("services.signing.custody", run_name="__main__")
