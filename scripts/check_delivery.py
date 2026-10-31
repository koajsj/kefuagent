"""Check bounded JavaScript, static Web assets, and installed-wheel contracts."""

import argparse
import ast
import re
import subprocess
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path


class Shell(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            self.assets.append(attrs["href"])


def run_bounded(label, command, timeout):
    try:
        subprocess.run(command, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{label} exceeded its {timeout}s time budget") from None


def check_assets(assets):
    for html, entry in (("index.html", "app.js"), ("public.html", "public.js")):
        shell = Shell()
        shell.feed((assets / html).read_text())
        if len(shell.ids) != len(set(shell.ids)):
            raise SystemExit(f"Duplicate HTML id in {html}")
        if f"/assets/{entry}" not in shell.assets:
            raise SystemExit(f"Missing entry script in {html}: {entry}")
        for url in shell.assets:
            target = (assets / url.removeprefix("/assets/")).resolve()
            if (
                not url.startswith("/assets/")
                or not target.is_relative_to(assets.resolve())
                or not target.is_file()
            ):
                raise SystemExit(f"Missing or invalid asset in {html}: {url}")
        selectors = re.findall(
            r'\b(?:document\s*\.\s*)?querySelector(?:All)?\(\s*["\']#([\w-]+)',
            (assets / entry).read_text(),
        )
        for selector in selectors:
            if selector not in shell.ids:
                raise SystemExit(f"Missing HTML id in {html}: {selector}")

    # Link without evaluating browser code: Node checks real module resolution and exports.
    linker = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(process.argv[1]);
async function check(entry) {
  const modules = new Map();
  function load(file) {
    if (!file.startsWith(root + path.sep)) throw new Error(`Module outside assets: ${file}`);
    if (!modules.has(file)) modules.set(file, new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), {identifier: file}));
    return modules.get(file);
  }
  await load(entry).link((specifier, source) => {
    if (!specifier.startsWith('./') && !specifier.startsWith('../')) throw new Error(`Non-local import: ${specifier}`);
    return load(path.resolve(path.dirname(source.identifier), specifier));
  });
}
(async () => {
  for (const file of fs.readdirSync(root).filter(name => name.endsWith('.js'))) await check(path.join(root, file));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    run_bounded(
        "JavaScript module-link check",
        ["node", "--no-warnings", "--experimental-vm-modules", "-e", linker, str(assets)],
        timeout=15,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    tests = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for path in Path("tests").glob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text()))
    )
    if tests > 28:
        raise SystemExit("Python test count exceeds P9 budget")
    run_bounded("JavaScript tests", ["node", "--test", "tests/web.test.mjs"], timeout=10)
    assets = Path("src/support_agent/web")
    check_assets(assets)
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
    main()
