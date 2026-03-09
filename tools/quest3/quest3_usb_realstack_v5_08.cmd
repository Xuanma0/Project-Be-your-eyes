@echo off
setlocal
echo [quest3_usb_realstack_v5_08] compatibility wrapper: forwarding to quest3_usb_realstack_v5_08_2.cmd
call "%~dp0quest3_usb_realstack_v5_08_2.cmd" %*
exit /b %ERRORLEVEL%
