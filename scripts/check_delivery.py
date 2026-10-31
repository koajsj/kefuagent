"""Check JavaScript, static Web assets, and installed-wheel contracts."""

import argparse
import re
import subprocess
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


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
    subprocess.run(
        ["node", "--no-warnings", "--experimental-vm-modules", "-e", linker, str(assets)],
        check=True,
    )


def check_repository():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], text=True
    ).split("\0")
    # Compare locally configured secret values without printing them or requiring configuration.
    secrets = []
    for key, value in dotenv_values(".env").items():
        if not value:
            continue
        if key.endswith("DATABASE_URL"):
            value = make_url(value).password or ""
        elif key not in {
            "CREDENTIAL_MASTER_KEY",
            "CREDENTIAL_KEYRING",
            "PUBLIC_RATE_KEY",
            "HTTP_RATE_KEY",
        }:
            continue
        if len(value) >= 16:
            secrets.append(value.encode())
    checked = 0
    for name in sorted(set(paths) - {""}):
        path = Path(name)
        if not path.exists():
            continue  # Git still lists unstaged deletions.
        if (
            any(part in {".local", ".venv", "secrets", "__pycache__"} for part in path.parts)
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.name == ".pgpass"
            or path.suffix
            in {
                ".pem",
                ".key",
                ".crt",
                ".p12",
                ".pfx",
                ".p8",
                ".dump",
                ".log",
                ".pyc",
                ".db",
                ".sqlite",
                ".sqlite3",
            }
        ):
            raise SystemExit(f"Sensitive/generated publication path: {path}")
        data = path.read_bytes()
        if any(secret in data for secret in secrets) or re.search(
            rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
            data,
        ):
            raise SystemExit(f"Possible secret in publication file: {path}")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^\s)]+)\)", data.decode()):
                url = urlsplit(target.strip("<>"))
                if not url.scheme and url.path:
                    resolved = path.parent / unquote(url.path)
                    if not resolved.exists():
                        raise SystemExit(f"Broken local Markdown link: {path}: {target}")
        checked += 1
    print(f"Publication scan passed: {checked} files, local links and known-secret patterns")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    assets = Path("src/support_agent/web")
    for path in sorted(assets.glob("*.js")):
        subprocess.run(["node", "--check", str(path)], check=True)
    check_assets(assets)
    check_repository()
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
    print(f"Delivery checks passed: packaged assets={len(list(assets.iterdir()))}")


if __name__ == "__main__":
    main()
