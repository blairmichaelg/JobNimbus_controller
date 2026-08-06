"""Environment verification script for deep initialization."""
import subprocess
import sys
import os

output = []

# Python version
try:
    result = subprocess.run(
        [sys.executable, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output.append(
        f"Python: {result.stdout.strip() or result.stderr.strip()}"
    )
except Exception as e:
    output.append(f"Python check failed: {e}")

# Current directory
output.append(f"PWD: {os.getcwd()}")

# Git status
try:
    result = subprocess.run(
        ["git", "status"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output.append("Git Status:")
    output.append(result.stdout or result.stderr)
except Exception as e:
    output.append(f"Git status failed: {e}")

# Git branch
try:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output.append(
        f"Current branch: "
        f"{result.stdout.strip() or result.stderr.strip()}"
    )
except Exception as e:
    output.append(f"Git branch failed: {e}")

# Write to file in scripts/dev directory
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, "env_check_results.txt")
with open(output_path, "w") as f:
    f.write("\n".join(output))

print(f"Environment check complete. Results written to {output_path}")