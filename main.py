import os
import sys
import time
import subprocess


def run_script(script_rel_path: str) -> int:
	project_root = os.path.dirname(os.path.abspath(__file__))
	script_path = os.path.join(project_root, script_rel_path)
	print(f"\n=== Running {script_path} ===")
	try:
		result = subprocess.run([sys.executable, script_path], cwd=project_root)
		print(f"=== Finished {script_path} (code {result.returncode}) ===")
		return result.returncode
	except Exception as e:
		print(f"Error running {script_path}: {e}")
		return 1


def main():
	scripts = [
		os.path.join("script", "SetDataScrapper.py"),
		os.path.join("script", "CardDataScrapper.py"),
		os.path.join("script", "LimitlessScrapper.py"),
		os.path.join("script", "SyncPreperation.py"),
	]

	for idx, rel in enumerate(scripts, start=1):
		rc = run_script(rel)
		if idx < len(scripts):
			time.sleep(3)

	print("\nAll done.")


if __name__ == "__main__":
	main()
