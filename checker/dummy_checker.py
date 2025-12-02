# checker/dummy_checker.py
print("CI/CD pipeline working — but now we force a failure for demo")
# exit 1 means failure
import sys
sys.exit(1)

