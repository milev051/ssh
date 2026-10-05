' Dvoklik pokrece lokalni panel bez prozora terminala.
Option Explicit
Dim shell, files, folder, result, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /d /s /c """ & folder & "\launcher\windows.cmd"""
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    MsgBox "SSH UI nije pokrenut. " & Err.Description, vbCritical, "SSH UI"
ElseIf result <> 0 Then
    MsgBox "Potreban je Python 3 sa pyw.exe ili pythonw.exe. Instaliraj Python sa python.org pa ponovo pokreni SSH UI - Windows.vbs.", vbExclamation, "SSH UI"
End If
