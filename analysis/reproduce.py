"""Run the offline reproduction workflow from any working directory."""
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
steps=['prepare_data.py','reaggregate.py','replay_metrics.py','replay_execution.py','rebuild_reference.py','trace_paths.py','verify_results.py']
for step in steps:
 print(f'Running {step}',flush=True)
 subprocess.run([sys.executable,str(ROOT/'analysis'/step)],cwd=ROOT,check=True)
print('PASS: offline reproduction completed. See results/reproduced/verification.json.')
