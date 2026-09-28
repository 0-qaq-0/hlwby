"""让脚本在「控制台编码不是 UTF-8」的机器上也能打印中文。

## 为什么需要它

Python 往**管道 / 重定向**里写东西时用的是系统区域编码，不是 UTF-8：
英文 Windows 上是 cp1252，中文 Windows 上是 cp936。而这个项目的所有输出都是中文，
于是 `print("[build] 版本 …")` 在 cp1252 上直接抛：

    UnicodeEncodeError: 'charmap' codec can't encode characters in position 8-9

**这不是假设，是真实翻过的车**：release 工作流在 ubuntu 上构建成功、在
windows-latest 上失败，退出码 1，日志里只有一句「Process completed with exit code 1」——
因为报错发生在打印报错信息的时候。本地怎么试都好，因为本地是 cp936，中文编得进去。

往终端（不是管道）打印时反而没事：PEP 528 之后 Windows 控制台走 UTF-8。
所以这个 bug 只在 CI、重定向到文件、或者被别的程序捕获输出时出现 ——
恰好是最不容易当场发现的那几种情况。

## 做法

把 stdout/stderr 换成 UTF-8，并且 `errors="replace"`：万一还有编不出来的字符，
宁可显示成问号，也不要让一个「打印进度」的动作把整个任务搞崩。

`jev_meme/__init__.py` 会在 import 时自动调它（这个包是应用不是库，
用户不该为了看中文去记一个环境变量）；不 import 本包的独立脚本
（比如 `scripts/build_release.py`）自己显式调一次。
"""

from __future__ import annotations

import sys


def enable_utf8() -> bool:
    """把 stdout / stderr 切到 UTF-8。返回是否至少成功改了一个。

    幂等，可以重复调。`reconfigure` 在 3.7+ 有；被替换成非文本流的 stdout
    （某些测试环境、pythonw）会没有这个方法，跳过即可。
    """
    changed = False
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
            changed = True
        except (ValueError, OSError):
            # 流已经关了，或者是某种不支持重配置的包装 —— 不影响功能，别在这里抛。
            pass
    return changed


__all__ = ["enable_utf8"]
