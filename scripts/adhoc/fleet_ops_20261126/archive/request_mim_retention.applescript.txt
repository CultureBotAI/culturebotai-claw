-- One bounded request to the existing MIM owner, never a goal resume or prompt answer.
-- Run only after the invoking operator has freshly verified the UUID/process and screen.
on run argv
    set requestPath to item 1 of argv
    set requestText to read POSIX file requestPath as «class utf8»
    tell application "Terminal"
        if tty of selected tab of window id 86 is not "/dev/ttys016" then error "MIM terminal identity changed"
        set screenText to contents of selected tab of window id 86
        if screenText does not contain "MediaIngredientMech" then error "MIM identity not visible"
        if screenText does not contain "Ask Codex to do anything" then error "MIM composer not empty"
        do script requestText in selected tab of window id 86
    end tell
end run
