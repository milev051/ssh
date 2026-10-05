on run
    try
        set launcherPath to POSIX path of (path to resource "pokreni.sh")
        do shell script "/bin/zsh " & quoted form of launcherPath
    on error errorMessage
        display dialog "SSH UI nije pokrenut. " & errorMessage buttons {"U redu"} default button "U redu" with icon stop
    end try
end run
