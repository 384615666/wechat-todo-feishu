@echo off
rem wechat-cli wrapper — 查询/导出本机微信聊天记录
set "PYTHONPATH=%USERPROFILE%\.wechat-cli\tool;%USERPROFILE%\.wechat-cli\deps"
python "%USERPROFILE%\.wechat-cli\tool\entry.py" %*
