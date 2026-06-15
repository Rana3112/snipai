' SnipAI launcher — starts the app fully detached (no console window).
' Double-click to run. App keeps running until you Quit from the tray icon.
' After build.py produces SnipAI.exe in dist/, this script launches it.
Set sh = CreateObject("WScript.Shell")
projDir = "C:\Users\utkar\OneDrive\Desktop\new project"
sh.CurrentDirectory = projDir
' 0 = hidden window, False = don't wait (detached). App outlives this script.
Dim exePath
exePath = projDir & "\dist\SnipAI.exe"
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FileExists(exePath) Then
    sh.Run """" & exePath & """", 0, False
Else
    ' Fallback: run from Python (dev mode)
    sh.Run """" & projDir & "\.venv\Scripts\pythonw.exe"" -m snipai", 0, False
End If
