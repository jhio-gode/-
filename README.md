# 重点运输车辆异常轨迹智能研判系统（TVRA）

这是一个本地运行的 Python 桌面软件原型，用于从卡口过车观测中筛选**可解释的人工核查线索**。它不会认定车辆违法、实际停车或实际装载货物，分值只用于排序。

## 交付内容

- `tvra/`：数据导入、规则引擎、本地数据库服务、Excel/Word 报告和 PySide2 桌面界面。
- `samples/demo.xlsx`：完全虚构的演示数据，可直接导入。
- `tests/`：Python 3.8 兼容的导入、规则、服务、报告和界面相关测试。
- `scripts/build_windows_bundle.py`：从官方 CPython NuGet 包和 PyPI 固定 wheel 构建 Windows 运行包。
- `docs/WINDOWS.md`：Windows 7 SP1 及以后系统的安装前提、诊断和已知限制。
- `docs/RULES.md`：当前规则、字段要求、阈值和解释边界。

## 从源码运行

建议使用 Python 3.8（与 Windows 交付包保持一致）：

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
TVRA_DATA_DIR=./local-data .venv/bin/python -m tvra --self-check
TVRA_DATA_DIR=./local-data .venv/bin/python -m tvra --demo --summary
```

没有参数直接运行 `python -m tvra` 会启动桌面界面。导入页支持 `.xlsx`、`.xlsm` 和 `.csv`；旧式 `.xls` 请先另存为 `.xlsx`。模板下载后按“填写说明”页补充字段。业务数据库写在用户数据目录，不写回原始导入文件。

命令行示例：

```sh
python -m tvra --data-dir ./local-data --import samples/demo.xlsx --summary --export ./rankings.xlsx
```

## Windows 交付

Windows 运行包自带 Python、Qt、Excel 和 Word 报告依赖，不要求用户安装 Python 或 Office。请按系统位数选择 x86 或 x64。Windows 7 需要 SP1 和微软官方 Universal C Runtime 更新；Windows 8.0、XP、Vista、Windows Server 和定制精简系统不属于当前验收目标。当前构建在 Linux 上完成，未声称通过各个 Windows 版本的实体机验收，详见 [docs/WINDOWS.md](docs/WINDOWS.md)。

打包前会通过 HTTPS 获取官方发行件并核对发布哈希；不要删除运行时目录、混用 x86/x64 DLL 或从非官方来源替换 UCRT。包内 `BUILD-MANIFEST.json` 记录每个依赖的来源和校验信息，`THIRD_PARTY_NOTICES.md` 记录第三方许可及可替换动态库说明。

## 数据和解释边界

最少需要每条观测的号牌号码和过车时间。车型、卡口、行政区域、地点标签、企业和高速进出语义会影响可评估的规则。相邻观测的时间间隔只生成“疑似停留”线索；同名卡口或行政区域不会自动证明车辆停留。导出的报告列出关联记录编号、时间、地点、规则版本和数据限制，复核人员应返回原始资料确认。

本项目源码本身未附加机构专有许可证；使用时请按你的单位软件管理和再分发要求处理。第三方运行库的许可见 `THIRD_PARTY_NOTICES.md`。
