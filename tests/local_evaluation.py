"""Current API acceptance entry point. Historical results remain in docs/local-evaluation.md."""
import argparse
import subprocess
import sys
from tests.attachment_evaluation import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true")
    args = parser.parse_args()
    run(args.ollama)
    if not args.ollama:
        subprocess.run([sys.executable, "-X", "utf8", "-m", "tests.attachment_contracts"], check=True)
