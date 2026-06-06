-- WicrosoftMord.app — double-click to set up + open the review surface for any
-- project, with zero terminal commands. Compiled to an .app by build-app.sh.
on run
	set homePOSIX to (POSIX path of (path to home folder)) & "WicrosoftMord"
	set launchScript to homePOSIX & "/bin/wmord-launch.sh"

	try
		set projectAlias to choose folder with prompt "Pick the project you want to review with WicrosoftMord:"
	on error number -128
		return -- user cancelled the folder picker
	end try
	set projectPOSIX to POSIX path of projectAlias

	try
		do shell script "/bin/bash " & quoted form of launchScript & " " & quoted form of projectPOSIX
	on error errMsg
		display dialog "WicrosoftMord couldn't start:" & return & return & errMsg buttons {"OK"} default button "OK" with icon stop
		return
	end try

	set the clipboard to "/loop 45s /redline"
	display dialog "WicrosoftMord is open in your browser." & return & return & "To connect it to Claude: click the Claude Code chat in VS Code, paste (⌘V), and press Enter. The rolling review loop will start — your comments and direct edits flow to Claude automatically." buttons {"Got it"} default button "Got it" with title "WicrosoftMord"
end run
