# 闲鱼选品审核工具

基于 Python + Playwright + Tkinter 的闲鱼商品爬虫与智能选品辅助工具。

## 功能
- 关键词搜索与多页采集
- 价格/机型/内存版本智能过滤
- 专业商家自动识别与屏蔽
- AI 辅助筛选（复制提示词）
- 内置 Web 界面

## 安装运行
\\\ash
pip install -r requirements.txt
playwright install
python main.py
\\\

## 打包为 exe
\\\ash
pyinstaller goofish.spec
\\\

## 注意
请勿将 data/browser_data/ 上传至公共仓库（含登录凭证）。
