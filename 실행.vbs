Option Explicit
Dim files, shell, folder, pythonw, entry, command
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
entry = files.BuildPath(folder, "launch.pyw")
If Not files.FileExists(pythonw) Then
    MsgBox "Run install.bat once in this folder, then double-click this launcher.", 48, "Upbit - Setup required"
    WScript.Quit 1
End If
If Not files.FileExists(entry) Then
    MsgBox "launch.pyw is missing. Extract both launcher files into the program folder.", 16, "Upbit - Missing file"
    WScript.Quit 1
End If
shell.CurrentDirectory = folder
command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & entry & Chr(34)
shell.Run command, 0, False
