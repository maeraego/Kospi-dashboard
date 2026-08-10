' run_hidden.vbs - launch a .bat with no visible console window
'
' Why this exists:
'   The scheduled tasks run as an Interactive task, so cmd.exe pops up a
'   black console window on the desktop. If that window is closed (or gets
'   Ctrl+C), the batch dies with 0xC000013A STATUS_CONTROL_C_EXIT and the
'   update silently stops half way. That happened on 2026-08-02 and again
'   on 2026-08-10, both times right after the PC was turned on.
'
'   wscript.exe runs this with no console of its own, and Run(..., 0, True)
'   starts the batch fully hidden and waits for it, so the exit code still
'   reaches Task Scheduler.
'
' Usage (Task Scheduler action):
'   Program : wscript.exe
'   Argument: "C:\Users\user\minyong-agent\Github\run_hidden.vbs" auto_update.bat
'
' Keep this file ASCII only - same codepage reason as the .bat files.

Option Explicit
Dim sh, fso, here, target, rc

If WScript.Arguments.Count < 1 Then
  WScript.Quit 2
End If

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here   = fso.GetParentFolderName(WScript.ScriptFullName)
target = fso.BuildPath(here, WScript.Arguments(0))

If Not fso.FileExists(target) Then
  WScript.Quit 3
End If

sh.CurrentDirectory = here
' 0 = hidden window, True = wait so the exit code propagates
rc = sh.Run("""" & target & """", 0, True)
WScript.Quit rc
