import subprocess
import glob
import os

files = glob.glob('app/**/*.py', recursive=True)
results = []

for f in files:
    if f.endswith('__init__.py'): continue
    module = f.replace('.py', '').replace('\\', '.').replace('/', '.')
    
    # Run mypy on this specific file with disallow-untyped-defs
    cmd = f"venv_fresh/Scripts/python -m mypy {f} --disallow-untyped-defs --ignore-missing-imports"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    errors = p.stdout.count('error:')
    results.append((errors, module))

results.sort()
for err, mod in results:
    if err < 10:
        print(f"{mod}: {err} errors")
