; Odin for Windows: electron-builder 26.0.12's templates/nsis/multiUser.nsh with one change, written over the
; template for the Windows build (packaging/nsis-templates.mjs) and pinned by app/test/windows-build.test.ts:
; the per-user folder is fixed (see setInstallModePerUser).
!include FileFunc.nsh
!include UAC.nsh

!define FOLDERID_UserProgramFiles {5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}
!define KF_FLAG_CREATE 0x00008000

# allow user to define own custom
!define /ifndef INSTALL_REGISTRY_KEY "Software\${APP_GUID}"
!define /ifndef UNINSTALL_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${UNINSTALL_APP_KEY}"

# current Install Mode ("all" or "CurrentUser")
Var installMode

!ifndef INSTALL_MODE_PER_ALL_USERS
  !ifndef ONE_CLICK
    Var hasPerUserInstallation
    Var hasPerMachineInstallation
  !endif
  Var PerUserInstallationFolder

  !macro setInstallModePerUser
    StrCpy $installMode CurrentUser
    SetShellVarContext current

    # Odin: always the user's Programs folder. The stock lookup read SHGetKnownFolderPath's answer as a fixed
    # ${NSIS_MAX_STRLEN}-character buffer, past its end (it crashed now and then), created the folder, and then
    # restored $0 to this same path anyway. A location recorded elsewhere is refused, not followed; the uninstaller
    # still follows the record, where it removes from.
    StrCpy $INSTDIR "$LocalAppData\Programs\${APP_FILENAME}"
    ReadRegStr $perUserInstallationFolder HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation
    !ifdef BUILD_UNINSTALLER
      ${if} $perUserInstallationFolder != ""
        StrCpy $INSTDIR $perUserInstallationFolder
      ${endif}
    !else
      ${if} $perUserInstallationFolder != ""
      ${andIf} $perUserInstallationFolder != $INSTDIR
        !insertmacro odinRefuse "Odin is recorded as installed in $perUserInstallationFolder, not in its own folder, $INSTDIR. Uninstall that copy from Settings, Apps, then run this again. Nothing was changed."
      ${endif}
    !endif

    # allow /D switch to override installation path https://github.com/electron-userland/electron-builder/issues/1551
    ${StdUtils.GetParameter} $R0 "D" ""
    ${If} $R0 != ""
      StrCpy $INSTDIR $R0
    ${endif}

  !macroend
!endif

!ifdef INSTALL_MODE_PER_ALL_USERS_REQUIRED
  Var perMachineInstallationFolder

  !macro setInstallModePerAllUsers
    StrCpy $installMode all
    SetShellVarContext all

    !ifdef BUILD_UNINSTALLER
      ${IfNot} ${UAC_IsAdmin}
        ShowWindow $HWNDPARENT ${SW_HIDE}
        !insertmacro UAC_RunElevated
        Quit
      ${endif}
    !endif

    # сheck registry for previous installation path
    ReadRegStr $perMachineInstallationFolder HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation
    ${if} $perMachineInstallationFolder != ""
      StrCpy $INSTDIR $perMachineInstallationFolder
    ${else}
      StrCpy $0 "$PROGRAMFILES"
      !ifdef APP_64
        ${if} ${RunningX64}
          StrCpy $0 "$PROGRAMFILES64"
        ${endif}
      !endif

      !ifdef MENU_FILENAME
        StrCpy $0 "$0\${MENU_FILENAME}"
      !endif

      StrCpy $INSTDIR "$0\${APP_FILENAME}"
    ${endif}

    # allow /D switch to override installation path https://github.com/electron-userland/electron-builder/issues/1551
    ${StdUtils.GetParameter} $R0 "D" ""
    ${If} $R0 != ""
      StrCpy $INSTDIR $R0
    ${endif}

  !macroend
!endif
