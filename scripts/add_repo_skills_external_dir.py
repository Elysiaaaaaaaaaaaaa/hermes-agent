#!/usr/bin/env python3
"""
将本仓库的 skills/ 目录加入当前 Hermes 配置的 skills.external_dirs（做法一）。

用法（在仓库根目录、已激活 venv 时）:
  python scripts/add_repo_skills_external_dir.py
  python scripts/add_repo_skills_external_dir.py --dry-run
  HERMES_HOME=~/.hermes/profiles/coder python scripts/add_repo_skills_external_dir.py

说明:
  - 会读取并写回 config.yaml；PyYAML 重排/重写后，原文件中的注释可能丢失。
  - 托管安装 (HERMES_MANAGED / .managed) 下与 hermes CLI 一致，拒绝写入。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_skills_dir() -> Path:
    return _repo_root() / "skills"


def _load_yaml(path: Path) -> dict:
    import yaml

    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        return {}
    if not isinstance(data, dict):
        print(f"错误: {path} 根节点不是 YAML 映射，已中止。", file=sys.stderr)
        sys.exit(1)
    return data


def _managed_block() -> str | None:
    """若处于托管模式则返回说明字符串，否则 None。"""
    home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
    if os.getenv("HERMES_MANAGED", "").strip().lower() in ("true", "1", "yes"):
        return "当前为托管安装 (HERMES_MANAGED)，请用发行版/包管理器方式修改配置。"
    if (home / ".managed").exists():
        return f"检测到 {home}/.managed，托管模式下请勿用本脚本直接改 config。"
    return None


def main() -> int:
    sys.path.insert(0, str(_repo_root()))

    parser = argparse.ArgumentParser(
        description="在 config.yaml 的 skills.external_dirs 中加入本仓库的 skills/ 路径。"
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help=f"要加入的 skills 根目录（默认: {_default_skills_dir()})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的内容，不写文件。",
    )
    args = parser.parse_args()

    skills_dir: Path = (args.skills_dir or _default_skills_dir()).resolve()
    if not skills_dir.is_dir():
        print(f"错误: 目录不存在或不是目录: {skills_dir}", file=sys.stderr)
        return 1

    blocked = _managed_block()
    if blocked:
        print(f"错误: {blocked}", file=sys.stderr)
        return 1

    from hermes_constants import display_hermes_home, get_config_path
    from utils import atomic_yaml_write

    import yaml

    config_path = get_config_path()
    cfg = _load_yaml(config_path)

    skills_section = cfg.get("skills")
    if skills_section is None:
        skills_section = {}
        cfg["skills"] = skills_section
    elif not isinstance(skills_section, dict):
        print("错误: config.yaml 中 skills 不是映射，已中止。", file=sys.stderr)
        return 1

    raw_dirs = skills_section.get("external_dirs")
    if raw_dirs is None:
        external: list = []
    elif isinstance(raw_dirs, str):
        external = [raw_dirs]
    elif isinstance(raw_dirs, list):
        external = list(raw_dirs)
    else:
        print("错误: skills.external_dirs 类型无效（应为列表或字符串）。", file=sys.stderr)
        return 1

    # 规范化已有项，避免重复（按 resolve 后路径比较）
    normalized_new = str(skills_dir)
    resolved_targets: set[Path] = set()
    for entry in external:
        if not entry or not isinstance(entry, str):
            continue
        expanded = Path(os.path.expanduser(os.path.expandvars(entry.strip())))
        try:
            resolved_targets.add(expanded.resolve())
        except OSError:
            resolved_targets.add(expanded)

    try:
        if skills_dir.resolve() in resolved_targets:
            print(f"已存在，无需修改: {normalized_new}")
            print(f"配置文件: {config_path}")
            return 0
    except OSError:
        pass

    cleaned = [str(x) for x in external if isinstance(x, str) and x.strip()]
    cleaned.append(normalized_new)
    skills_section["external_dirs"] = cleaned

    print(f"Hermes 目录: {display_hermes_home()}")
    print(f"配置文件: {config_path}")
    print(f"将追加 external_dirs 项: {normalized_new}")

    if args.dry_run:
        print("\n--dry-run: 未写入。合并后的 skills 段预览:")
        print(yaml.safe_dump({"skills": skills_section}, allow_unicode=True, default_flow_style=False))
        return 0

    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_yaml_write(config_path, cfg, sort_keys=False)
    print("已保存。请重启 CLI / gateway 后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
