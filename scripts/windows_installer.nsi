; Compile using scripts/build_windows_bundle.py --makensis /path/to/makensis
Unicode True
!include "MUI2.nsh"
!include "WinVer.nsh"
!include "x64.nsh"

!ifndef ARCH
!error "Define ARCH=x86 or x64"
!endif
!ifndef BUNDLE_DIR
!error "Define BUNDLE_DIR"
!endif
!ifndef OUTPUT_FILE
!error "Define OUTPUT_FILE"
!endif

Name "重点运输车辆异常轨迹研判系统 (${ARCH})"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\TVRA-${ARCH}"
InstallDirRegKey HKCU "Software\TVRA-${ARCH}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
ShowInstDetails show
ShowUninstDetails show
BrandingText "TVRA 3.0.0"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\runtime\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-E -s -B $\"$INSTDIR\launcher.py$\""
!define MUI_FINISHPAGE_RUN_TEXT "启动车辆轨迹研判系统"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${IfNot} ${AtLeastWin7}
    MessageBox MB_ICONSTOP "此版本需要 Windows 7 SP1 或更高版本。"
    Abort
  ${EndIf}
  ${If} ${IsWin7}
  ${AndIfNot} ${AtLeastServicePack} 1
    MessageBox MB_ICONSTOP "Windows 7 需要先安装 Service Pack 1 和 Universal C Runtime 更新。"
    Abort
  ${EndIf}
!if "${ARCH}" == "x64"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "此安装包适用于 64 位 Windows。32 位系统请使用 x86 安装包。"
    Abort
  ${EndIf}
!endif
FunctionEnd

Section "安装主程序" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${BUNDLE_DIR}/*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\TVRA (${ARCH})"
  CreateShortcut "$SMPROGRAMS\TVRA (${ARCH})\车辆轨迹研判系统.lnk" "$INSTDIR\runtime\pythonw.exe" '-E -s -B "$INSTDIR\launcher.py"'
  CreateShortcut "$SMPROGRAMS\TVRA (${ARCH})\诊断检查.lnk" "$INSTDIR\Diagnose-TVRA.bat"
  CreateShortcut "$SMPROGRAMS\TVRA (${ARCH})\卸载.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\车辆轨迹研判系统 (${ARCH}).lnk" "$INSTDIR\runtime\pythonw.exe" '-E -s -B "$INSTDIR\launcher.py"'
  WriteRegStr HKCU "Software\TVRA-${ARCH}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "DisplayName" "车辆轨迹研判系统 (${ARCH})"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "DisplayVersion" "3.0.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\车辆轨迹研判系统 (${ARCH}).lnk"
  RMDir /r "$SMPROGRAMS\TVRA (${ARCH})"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\tvra"
  RMDir /r "$INSTDIR\samples"
  RMDir /r "$INSTDIR\docs"
  RMDir /r "$INSTDIR\tests"
  RMDir /r "$INSTDIR\scripts"
  Delete "$INSTDIR\launcher.py"
  Delete "$INSTDIR\Start-TVRA.bat"
  Delete "$INSTDIR\Diagnose-TVRA.bat"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\WINDOWS-README.md"
  Delete "$INSTDIR\BUILD-MANIFEST.json"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\pyproject.toml"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\TVRA-${ARCH}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TVRA-${ARCH}"
  ; Business data under the user's data directory is deliberately retained.
SectionEnd
