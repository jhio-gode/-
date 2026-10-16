# Third-party notices

TVRA bundles the following third-party components. This file is included with
the portable archive and installer so the corresponding notices remain with
the executable distribution. The application source is delivered separately;
this file does not grant a licence to the TVRA application itself.

## Python

* **CPython 3.8.10**, Python Software Foundation License (PSF License).
  Source: <https://github.com/python/cpython/tree/v3.8.10>. The Windows
  runtime is the official `python`/`pythonx86` NuGet package from
  <https://www.nuget.org/packages/python/3.8.10> and
  <https://www.nuget.org/packages/pythonx86/3.8.10>. The builder verifies the
  SHA-512 digest published in the NuGet registration metadata and retains the
  package's repository signature file. The package's `LICENSE.txt` and
  `LICENSE` files are shipped in `runtime`.

## Qt for Python

* **PySide2 5.15.2.1** and **Shiboken2 5.15.2.1**, LGPLv3 (with the upstream
  GPL/FDL notices retained in their `*.dist-info` directories). Source and
  licensing: <https://code.qt.io/pyside/pyside-setup/>
  and <https://www.qt.io/licensing/>. The exact wheel URL and SHA-256 digest
  are recorded in each bundle's `BUILD-MANIFEST.json`.
* The bundle dynamically links Qt 5.15.2 libraries. Only the bindings used by
  the application (`QtCore`, `QtGui`, `QtWidgets`, `QtSvg`) and their required
  QtQml/QtNetwork link dependencies are retained. Optional modules such as
  QtCharts, QtDataVisualization, QtWebEngine and Qt3D are not included. Qt
  platform, image-format and style plugins are retained only from the build
  allowlist documented in `scripts/build_windows_bundle.py`.

Under the LGPL's replacement terms, a recipient may replace these compatible
LGPL components. Replace the complete matching files in
`runtime\\Lib\\site-packages\\PySide2` (and `shiboken2` if replacing the
binding), preserve the same architecture and Qt major/minor ABI, then run
`Diagnose-TVRA.bat`. Do not mix x86 and x64 DLLs or delete the `platforms`
plugin. The bundle is not signed by an institutional code-signing certificate.

## Python packages

The following packages are distributed under their upstream licenses; their
license files are retained in `runtime\\Lib\\site-packages\\*.dist-info`.
The pinned wheel URLs and SHA-256 digests are recorded in
`BUILD-MANIFEST.json`.

* **openpyxl 3.1.5** — MIT License — <https://github.com/ericgazoni/openpyxl>
* **python-docx 1.1.2** — MIT License — <https://github.com/python-openxml/python-docx>
* **lxml 5.3.2** — BSD-style license — <https://github.com/lxml/lxml>
* **typing_extensions 4.13.2** — PSF License — <https://github.com/python/typing_extensions>
* **et_xmlfile 2.0.0** — MIT License — <https://github.com/pyexcel/pyexcel-io>

## Corresponding source and build materials

For each component, the URLs above provide the corresponding source. This
project does not alter the source of these dependencies. The repository's
`scripts/build_windows_bundle.py` is the reproducible assembly script: it
requires HTTPS, verifies the publisher digest before extraction, records the
selected artifact URL and digest, and performs a static PE architecture and
DLL-import check. It does not disable TLS or package-signature checks.
