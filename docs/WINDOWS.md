# Windows 安装与兼容说明

本发行版提供 **x86（32 位）与 x64（64 位）两个包**。每个架构同时提供安装程序和免安装 ZIP；已经包含 Python、Qt、Excel 和 Word 报告所需依赖，无需另装 Python、Office，也无需联网使用。

| 系统 | 选用版本 | 前提与验证状态 |
| --- | --- | --- |
| Windows 7 SP1 | x86 或 x64，按系统位数选择 | 需安装 Universal C Runtime（KB2999226）及系统所需更新；兼容性设计目标，尚待实体机验收 |
| Windows 8.0 | x86 或 x64，按系统位数选择 | 兼容性设计目标，尚待实体机验收；需完整系统更新 |
| Windows 8.1 | x86 或 x64，按系统位数选择 | 兼容性设计目标，尚待实体机验收；需完整系统更新 |
| Windows 10 | x86 或 x64，按系统位数选择 | 兼容性设计目标，尚待实体机验收 |
| Windows 11 | 推荐 x64 | 兼容性设计目标，尚待实体机验收；不提供原生 ARM64 包 |

Windows Server 各版本、精简或定制系统尚未列为验收平台。Windows 7 无 SP1、Windows XP、Vista 不在支持目标内。“Windows 7 之后的全部版本”涉及系统补丁、架构及驱动差异，不能以一次构建替代各版本实际验收。

## 安装程序

1. 查看系统属性中的系统位数，选择对应的 `windows-x86-setup.exe` 或 `windows-x64-setup.exe`。
2. 双击安装，默认安装到当前用户的本地应用目录，无需管理员权限。
3. 从桌面或开始菜单打开程序。安装过程不导入业务数据。
4. 首次使用可从导入页面下载模板，并先导入随包 `samples` 目录的合成演示文件。

安装器尚未加机构代码签名，Windows 可能显示“未知发布者”。请先核对随交付提供的 SHA256 校验值，并遵守本单位软件安装要求。

## 免安装版本

完整解压 ZIP 到有写入权限的文件夹后，双击 `Start-TVRA.bat`。不要直接在压缩包预览中运行。`runtime` 文件夹不能删减。业务数据保存在当前用户的数据目录，程序文件与业务数据库分开保存；卸载保留业务数据。

## 诊断及 Windows 验收

双击 `Diagnose-TVRA.bat`，或在命令提示符运行：

```bat
runtime\python.exe -E -s -B scripts\windows_smoke.py --show
```

此检查使用临时目录验证 SQLite、模板导入、Excel 导出及 Qt 主窗口，结束后清理测试数据，不改动已有业务库。验收时还需人工执行：导入演示文件、筛选事件、查看车辆详情、修改规则并重算、导出 Excel 与 Word、关闭重开、重装及卸载后核对原业务数据。

本包由 Linux 环境组装，已校验官方依赖哈希、Windows PE 文件架构与必需文件；**不能据此声称已在上述 Windows 系统真实运行通过**。首批试用应先用合成样例完成各目标系统验收。

若 Windows 7 出现 `api-ms-win-crt-*.dll` 或 `ucrtbase.dll` 缺失，先从微软官方渠道补齐系统 Universal C Runtime 更新；不要从非官方 DLL 网站下载文件替换。Qt 平台插件错误应检查是否完整解压，诊断时保留完整报错。

## 源码与可复现打包

源码包含完整应用、测试、文档和构建脚本。Windows 兼容运行时固定为 Python 3.8.10、PySide2 5.15.2.1 / Qt 5.15.2；升级这些组件前必须重测最低系统版本。应用版本为 **3.0.0**。

```sh
python scripts/build_windows_bundle.py --arch both --output /path/to/artifacts
# 可选：本机已安装 NSIS 时，同时编译安装器
python scripts/build_windows_bundle.py --arch both --makensis C:\\Program Files\\NSIS\\makensis.exe
```

构建器从 Python Software Foundation 官方 NuGet 发布包获取 CPython，以 NuGet 官方目录发布的 SHA512 校验；从 PyPI 获取固定版本 wheel，以各发布条目的 SHA256 校验。所有下载保留 HTTPS 证书验证，不运行上传的 EXE/PYC，不携带上传的真实数据库或日志。发行目录 `BUILD-MANIFEST.json` 保留逐项来源、哈希和验证范围；NuGet 包内仓库签名被保留在构建缓存中，本 Linux 流程未独立执行 Windows Authenticode/CMS 信任链验证。

PySide2 与 Qt 以可替换的动态库形式分发，保留 wheel 中的许可证文件。构建器按明确白名单保留 QtCore、QtGui、QtWidgets、QtSvg 及所需平台、样式、图像和图标插件、PySide2/shiboken2 初始化及支持文件，不分发本程序未使用的 QtCharts、DataVisualization、WebEngine 等可选模块。每个 EXE/DLL/PYD 均静态核对架构与普通、延迟加载 DLL 依赖。两个上游 PySide wheel 中的私有 `ucrtbase.dll` 被一致移除，使用系统 UCRT；其中 x64 wheel 误带了 32 位副本，不能混入 64 位应用。用户可以替换兼容的 LGPL 组件并重新运行诊断，发行包不设置依赖替换限制。对应 LGPL 源码、构建说明及许可范围见 `THIRD_PARTY_NOTICES.md`。Qt/Python 的旧版兼容运行时应在受控的离线业务场景下维护和测试。
