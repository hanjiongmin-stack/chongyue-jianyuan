# 贡献指南

感谢你愿意帮助改进崇岳鉴渊！无论是指出一个错别字、补充一份学习资料，还是修复一个问题，都非常欢迎。

## 可以参与的方式

- **报告问题**：页面显示异常、功能不可用、资料内容有误，请通过 [Issue](https://github.com/hanjiongmin-stack/chongyue-jianyuan/issues/new/choose) 选择「问题反馈」提交。
- **提出建议**：希望新增的功能、学科或资料，请选择「功能建议」提交。
- **补充内容**：讲义勘误、习题补充、新的学习资源，可以直接提交 Pull Request，也可以先开 Issue 讨论。
- **改进代码**：修复问题、优化体验或性能。

提交涉及真题、论文等第三方资料的内容前，请确认可以公开分享。

## 开发环境

```bash
git clone https://github.com/hanjiongmin-stack/chongyue-jianyuan.git
cd chongyue-jianyuan
pip install -r requirements.txt
python unified_server.py        # http://127.0.0.1:8888
```

项目结构、前端约定和接口说明见 [开发文档](docs/development.md)。前端没有构建步骤，修改 HTML / CSS / JS 后刷新页面即可。

## 提交 Pull Request

1. Fork 本仓库，从 `main` 创建分支，例如 `fix/math-search` 或 `content/organic-ch05`。
2. 保持改动聚焦：一个 Pull Request 只解决一件事。
3. 代码风格与周围代码保持一致；页面样式优先复用 `static/assets/cyjy.css` 中的设计变量和组件，拼接 HTML 时用 `CY.esc()` 转义外部数据。
4. 在本地打开改动涉及的页面，确认浏览器控制台没有报错，并检查深色、浅色主题和手机宽度下的显示效果。
5. 提交信息使用 `类型: 说明` 的格式，与现有提交记录保持一致，例如：
   - `feat: 真题库支持按赛题筛选`
   - `fix: 修复化学讲义移动端目录无法关闭`
   - `docs: 补充部署指南中的环境变量说明`
6. 在 Pull Request 中说明改了什么、为什么改，以及如何验证；涉及界面变化时附上截图。

## 行为准则

请友善、耐心地交流，尊重不同水平的同学。讨论聚焦在问题本身，不进行人身攻击。
