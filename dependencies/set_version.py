"""
Injects a version string into APP_VERSION = "..." in one or more Python
source files. Used by BUILD_EXECUTABLES.bat so the version only needs to
be typed once and both launcher files stay in sync — keeping this logic
in a real .py file instead of generating it inline from batch avoids the
batch/PowerShell quoting and escaping traps that used to break this step.

Usage: python set_version.py <version> <file1.py> [file2.py ...]
"""
import re
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: python set_version.py <version> <file1.py> [file2.py ...]")
        sys.exit(1)

    version = sys.argv[1]
    files = sys.argv[2:]
    pattern = re.compile(r'APP_VERSION = ".*?"')

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"[ERROR] Couldn't read {path}: {e}")
            sys.exit(1)

        if not pattern.search(content):
            print(f"[WARN] No APP_VERSION line found in {path} — left unchanged.")
            continue

        new_content = pattern.sub(f'APP_VERSION = "{version}"', content, count=1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f'[OK] {path} -> APP_VERSION = "{version}"')


if __name__ == "__main__":
    main()
