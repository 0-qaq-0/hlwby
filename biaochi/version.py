"""版本号 —— release 包、`/api/health`、页面页脚都从这里读。

只在这一个地方改版本，别处引用 ``__version__``。
"""

from __future__ import annotations

#: 语义化版本。改动判断类型 / API / 页面这类用户可见的东西就进一位。
#:   * 3.x —— 只有「八艺」一套写死的词表（项目当时也叫八艺）
#:   * 4.0 —— 判断类型可自定义（profiles）、WebUI 重做、一键 release 包
__version__ = "4.1.0"

#: 数据格式版本：profile JSON / 导出文件的 ``schema`` 字段。
#: 加字段不一定要动它；改了字段含义才动，并且要写迁移。
SCHEMA_VERSION = 1

__all__ = ["__version__", "SCHEMA_VERSION"]
