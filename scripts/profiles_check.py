"""判断类型检查：内置 + 用户自定义的每一套类型，逐条过一遍校验规则。

这是 `scripts/labels_check.py` 的推广版。labels_check 只认「八艺」这一套写死的
词表（它还在，因为八艺是唯一评测过的那套）；这个脚本认所有类型，包括用户在
页面上新建的 —— 自定义类型多了以后，命令行里得有一个「一次全查一遍」的入口。

校验规则本身在 `biaochi/profiles.py` 的 `validate()` 里，页面上的编辑器调的是
同一份实现。这个脚本不重复实现规则，只负责**批量跑 + 排版**。

用法：
    .venv\\Scripts\\python.exe scripts\\profiles_check.py
    .venv\\Scripts\\python.exe scripts\\profiles_check.py --strict   # warning 也算失败
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.profiles import (  # noqa: E402
    ProfileStore,
    errors_of,
    profile_stats,
    validate,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="判断类型一致性检查")
    parser.add_argument("--strict", action="store_true", help="把 warning 也算失败")
    parser.add_argument("--only", default=None, help="只查某一套类型")
    args = parser.parse_args()

    store = ProfileStore()
    profiles = store.list()
    if args.only:
        profiles = [profile for profile in profiles if profile.id == args.only]
        if not profiles:
            print(f"没有这个判断类型：{args.only}")
            sys.exit(2)

    print(f"判断类型 {len(profiles)} 套（内置 + 用户目录 {store.user_dir}）\n")

    total_errors = 0
    total_warnings = 0
    for profile in profiles:
        issues = validate(profile)
        errors = [issue for issue in issues if issue.level == "error"]
        warnings = [issue for issue in issues if issue.level == "warning"]
        total_errors += len(errors)
        total_warnings += len(warnings)

        tag = "内置" if profile.builtin else "用户"
        state = "已评测" if profile.evaluated else "未评测"
        stats = profile_stats(profile)
        head = (
            f"===== [{profile.id}] {profile.name}（{tag}·{state}）=====\n"
            f"  选项 {stats['label_count']} 个：{' '.join(profile.label_ids)}\n"
            f"  问法：{profile.criterion}\n"
            f"  锚点 {stats['description_chars']} 字"
            f"（{stats['description_min']}~{stats['description_max']}），"
            f"例句约 {stats['anchor_examples']} 条，页面示例 {stats['example_count']} 条"
        )
        print(head)
        for issue in errors:
            print(f"  错误  [{issue.field}] {issue.message}")
        for issue in warnings:
            print(f"  提示  [{issue.field}] {issue.message}")
        if not issues:
            print("  （无问题）")
        print()

    print("===== 结论 =====")
    if total_errors:
        print(f"  {total_errors} 个错误 —— 这些类型存不下来，先修掉。")
    else:
        print("  没有错误。")
    if total_warnings:
        print(f"  {total_warnings} 条提示（不影响使用，但多半能改得更准）。")
        if not args.strict:
            print("  想看它们是不是拦得住，加 --strict。")
    print(
        "\n注意：这些检查只覆盖「已知会翻车的写法」。"
        "\n锚点好不好，最终只能拿**干净测试集**量 —— 见 docs/EVAL.md。"
    )
    sys.exit(1 if total_errors or (args.strict and total_warnings) else 0)


if __name__ == "__main__":
    main()
