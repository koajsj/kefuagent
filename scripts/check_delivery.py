"""Small JS and installed-wheel contracts, no browser or build framework."""

import argparse
import ast
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    tests = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for path in Path("tests").glob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text()))
    )
    if tests > 54:
        raise SystemExit("Python test count exceeds P7 budget")
    subprocess.run(["node", "--test", "tests/web.test.mjs"], check=True, timeout=10)
    assets = Path("src/support_agent/web")
    for path in assets.glob("*.js"):
        subprocess.run(["node", "--check", str(path)], check=True, timeout=10)
    expected_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    with zipfile.ZipFile(args.wheel) as package:
        names = set(package.namelist())
        for path in assets.iterdir():
            if path.is_file() and "support_agent/web/" + path.name not in names:
                raise SystemExit("Missing packaged Web asset")
        metadata = package.read(
            f"support_agent_platform-{expected_version}.dist-info/METADATA"
        ).decode()
        assert "License-Expression: MIT" in metadata
        assert f"support_agent_platform-{expected_version}.dist-info/licenses/LICENSE" in names
    print(
        f"Delivery contracts passed: Python functions={tests}, packaged assets={len(list(assets.iterdir()))}"
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        sys.exit("Delivery check exceeded its time budget")
