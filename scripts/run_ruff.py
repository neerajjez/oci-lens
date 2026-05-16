import subprocess
import sys

def main():
    print("Installing ruff...")
    subprocess.run([sys.executable, "-m", "pip", "install", "ruff", "-q", "--disable-pip-version-check", "--break-system-packages"], check=True)
    print("Running ruff fix...")
    subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", "--unsafe-fixes", "src/", "tests/"], check=False)
    print("Done")

if __name__ == "__main__":
    main()
