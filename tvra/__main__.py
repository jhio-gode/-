from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="TVRA 重点运输车辆异常轨迹研判")
    parser.add_argument("--data-dir", help="自定义本地数据目录")
    parser.add_argument("--import", dest="inputs", nargs="+", help="导入 XLSX/CSV 并退出")
    parser.add_argument("--summary", action="store_true", help="输出本地数据统计并退出")
    parser.add_argument("--export", help="导出车辆排名 XLSX，需配合 --import 或 --summary")
    parser.add_argument("--demo", action="store_true", help="载入随包合成演示数据")
    parser.add_argument("--self-check", action="store_true", help="验证模块和 Qt 离屏界面后退出")
    args = parser.parse_args(argv)
    try:
        from .service import Service
        service = Service(args.data_dir)
        if args.demo:
            demo = Path(__file__).resolve().parent.parent / "samples" / "demo.xlsx"
            service.import_files([demo])
        if args.inputs:
            result = service.import_files(args.inputs)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not result["new_records"] and result["error_count"]:
                return 2
        if args.summary or args.inputs:
            summary = service.summary()
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            if args.export:
                from .reports import export_rankings
                export_rankings(service.list_vehicles(), service.list_events(), args.export, summary)
            return 0
        if args.export:
            parser.error("--export 需配合 --import 或 --summary")
        if args.self_check:
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide2.QtWidgets import QApplication
            from .gui import MainWindow
            application = QApplication.instance() or QApplication(sys.argv[:1])
            window = MainWindow(service)
            window.show()
            application.processEvents()
            window.close()
            print(json.dumps({"status": "ok", "summary": service.summary()}, ensure_ascii=False))
            return 0
        from .gui import run_desktop
        return run_desktop(service) or 0
    except Exception as exc:
        message = "TVRA 运行失败：{}".format(exc)
        if sys.stderr:
            print(message, file=sys.stderr)
        # pythonw has no console: show startup failures instead of silently exiting.
        if not sys.stderr:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, "TVRA", 0x10)
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
