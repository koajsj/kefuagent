"""Offline test-data evaluation, never a live Provider runner."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

from support_agent.config import Settings
from support_agent.evaluation import markdown


def main():
    parser = argparse.ArgumentParser(description="三项离线文档召回评测，不调用模型")
    parser.add_argument("--compare", type=Path, help="比较同版本数据集报告")
    parser.add_argument("--output", type=Path, default=Path(".local/evaluations"))
    args = parser.parse_args()
    settings = Settings()
    if "TEST_DATABASE_URL" not in os.environ:
        url = make_url(settings.database_url.get_secret_value())
        if url.host != "127.0.0.1" or url.database != "support_agent_dev":
            raise SystemExit("Set TEST_DATABASE_URL to a separately migrated test database")
        os.environ["TEST_DATABASE_URL"] = url.set(database="support_agent_test").render_as_string(
            hide_password=False
        )
    if "test" not in make_url(os.environ["TEST_DATABASE_URL"]).database:
        raise SystemExit("Refusing a non-test database")
    args.output.mkdir(parents=True, exist_ok=True)
    report = args.output / f"quality-offline-{uuid4().hex}.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_quality.py::test_offline_retrieval_quality_set",
            "-q",
            "--tb=short",
        ],
        env=os.environ | {"P4_EVAL_REPORT": str(report.resolve())},
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    data = json.loads(report.read_text())
    previous = json.loads(args.compare.read_text()) if args.compare else None
    report.with_suffix(".md").write_text(markdown(data, previous))
    print("Offline mechanical report:", report.resolve())
    print("Real model and semantic answer quality: NOT_EVALUATED")


if __name__ == "__main__":
    main()
