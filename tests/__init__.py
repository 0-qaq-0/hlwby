"""标尺的测试套件。

只用标准库 `unittest` 写，所以**不装任何东西**就能跑：

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

装了 pytest 的话 `pytest` 也能收（`unittest.TestCase` 是兼容的）。

分四块：

* ``test_labels.py``        —— 词表与页面示例的硬约束（含**泄漏**回归）
* ``test_engine_helpers.py`` —— 不碰 GPU 的纯函数：排列、降档、设备选择
* ``test_leak_check.py``    —— 泄漏检查器本身的行为（短句那个 bug 的回归）
* ``test_server_api.py``    —— HTTP 层的参数校验，用一个假引擎跑，不加载模型
"""
