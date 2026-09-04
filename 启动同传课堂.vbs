' Double-click launcher: no console window. Logic is in scripts\windows_launch.ps1
Option Explicit
Dim fso, root, ps1, cmd, sh
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = root & "\scripts\windows_launch.ps1"
If Not fso.FileExists(ps1) Then
    MsgBox "Missing scripts\windows_launch.ps1", vbExclamation, "Tongchuan"
    WScript.Quit 1
End If
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Run cmd, 0, False
