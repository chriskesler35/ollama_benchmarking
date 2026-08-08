' Create Desktop Shortcut for Benchmark Dashboard
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get Desktop path
strDesktop = objShell.SpecialFolders("Desktop")

' Create shortcut
Set objLink = objShell.CreateShortcut(strDesktop & "\Benchmark Dashboard.lnk")
objLink.TargetPath = "E:\projects\ollama-bench\start-dashboard.bat"
objLink.WorkingDirectory = "E:\projects\ollama-bench"
objLink.Description = "Start Benchmark Dashboard"
objLink.IconLocation = "cmd.exe,0"
objLink.Save

MsgBox "Desktop shortcut created!", vbInformation, "Success"
