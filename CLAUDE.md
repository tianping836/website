# 个人网站部署

> 军哥律师个人网站 (zhouyijunlawyer.com) 的自动部署项目。

## 核心文件

| 文件 | 用途 |
|------|------|
| `deploy-site.py` | 主部署脚本：读取漫画 + Obsidian 文章 → 生成 HTML → 部署到 Cloudflare Pages |
| `template/个人作品集.html` | 网站 HTML 模板 |
| `.cf_token` | Cloudflare API Token（gitignored） |
| `.deploy-cache.json` | 漫画增量检测缓存（gitignored） |
| `.deploy-cache/` | 压缩后的漫画图片缓存（gitignored） |

## 数据来源

- **漫画**: `~/Documents/律师宣传/漫画普法/`（自动适配 iCloud 路径）
- **文章**: Obsidian `法律/3.涉税输出/`
- **部署目标**: Cloudflare Pages `zhouyijun-lawyer`

## 运行方式

```bash
python3 deploy-site.py
```

或通过 MyAgents 定时任务自动执行。

## 注意事项

- 漫画采用增量检测：内容没变的文件夹跳过重新压缩，直接用缓存
- Token 文件 `.cf_token` 不提交到 Git
- 部署临时目录 `/tmp/zhouyijun-deploy/`
