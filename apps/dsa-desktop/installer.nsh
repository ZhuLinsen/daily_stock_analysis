!macro customInstallMode
  ; Keep the install-dir wizard, but force a per-user install so runtime files
  ; stay under a user-writable location next to the packaged executable.
  StrCpy $isForceCurrentInstall 1
!macroend

!macro customHeader
; Reject system-protected directories (Program Files, Windows, etc.)
; to prevent runtime write failures for .env, data/ and logs/.
; .onVerifyInstDir is called on each change in the directory field;
; Abort grays out "Next" so the user cannot proceed with a blocked path.
Function .onVerifyInstDir
  Push $R0
  Push $R1

  ; --- Block $PROGRAMFILES (C:\Program Files on x64 installer) ---
  StrLen $R0 $PROGRAMFILES
  StrCpy $R1 $INSTDIR $R0
  StrCmp $R1 $PROGRAMFILES _dsa_reject

  ; --- Block $PROGRAMFILES64 ---
  StrLen $R0 $PROGRAMFILES64
  StrCpy $R1 $INSTDIR $R0
  StrCmp $R1 $PROGRAMFILES64 _dsa_reject

  ; --- Block $PROGRAMFILES32 (C:\Program Files (x86)) ---
  StrLen $R0 $PROGRAMFILES32
  StrCpy $R1 $INSTDIR $R0
  StrCmp $R1 $PROGRAMFILES32 _dsa_reject

  ; --- Block $WINDIR (C:\Windows and subdirectories) ---
  StrLen $R0 $WINDIR
  StrCpy $R1 $INSTDIR $R0
  StrCmp $R1 $WINDIR _dsa_reject

  Pop $R1
  Pop $R0
  Return

_dsa_reject:
  Pop $R1
  Pop $R0
  Abort
FunctionEnd
!macroend
