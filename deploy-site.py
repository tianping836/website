#!/usr/bin/env python3
"""网站自动部署脚本
读取 Obsidian 文章 + 漫画文件夹 → 生成 HTML → 部署到 Cloudflare Pages
"""

import os, subprocess, shutil, json, re, hashlib, sys, time

# ====== 路径配置 ======
# 自动适配: iCloud Desktop & Documents 开启/未开启 两种模式
_ICLOUD_DOCS = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Documents")
_LOCAL_DOCS = os.path.expanduser("~/Documents")

def _first_existing(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[-1]  # fallback to last

COMICS_DIR = _first_existing(
    os.path.join(_ICLOUD_DOCS, "律师宣传/漫画普法"),
    os.path.join(_LOCAL_DOCS, "律师宣传/漫画普法"),
)
ARTICLES_DIR = os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/法律/3.涉税输出")
SITE_TEMPLATE = os.path.expanduser("~/.myagents/projects/website/template/个人作品集.html")
TOKEN_FILE = os.path.expanduser("~/.myagents/projects/website/.cf_token")
CACHE_FILE = os.path.expanduser("~/.myagents/projects/website/.deploy-cache.json")
CACHE_IMG_DIR = os.path.expanduser("~/.myagents/projects/website/.deploy-cache")
DEPLOY_DIR = "/tmp/zhouyijun-deploy"
ACCT_ID = "0dcf6b6e6264958abe0e8d2c185db8d5"
PROJ_NAME = "zhouyijun-lawyer"
DOMAINS = ["zhouyijun.cn", "zhouyijunlawyer.cn", "zhouyijunlawyer.com"]

# ====== Markdown 转换 ======
def md_to_html(md_text):
    lines = md_text.split('\n')
    html_lines = []
    in_list = False

    for line in lines:
        # 处理 Markdown 图片 ![alt](src)
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', line.strip())
        if img_match:
            if in_list: html_lines.append('</ul>'); in_list = False
            alt, src = img_match.groups()
            html_lines.append(f'<img src="{src}" alt="{alt}" style="max-width:100%;border-radius:8px;margin:16px 0">')
            continue

        if line.startswith('### '):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h3 style="color:#0d2340;font-family:SimHei,sans-serif;margin:24px 0 12px">{line[4:]}</h3>')
        elif line.startswith('## '):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h2 style="color:#0d2340;font-family:SimHei,sans-serif;margin:28px 0 14px;border-left:4px solid #c9a84c;padding-left:12px">{line[3:]}</h2>')
        elif line.startswith('# '):
            if in_list: html_lines.append('</ul>'); in_list = False
        elif '**' in line:
            t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<p style="margin:10px 0;line-height:2;color:#4a5568">{t}</p>')
        elif line.strip().startswith('- '):
            if not in_list:
                html_lines.append('<ul style="color:#4a5568;line-height:2;padding-left:20px">')
                in_list = True
            html_lines.append(f'<li>{line.strip()[2:]}</li>')
        elif line.strip() == '':
            if in_list: html_lines.append('</ul>'); in_list = False
        else:
            if in_list: html_lines.append('</ul>'); in_list = False
            if line.strip():
                html_lines.append(f'<p style="margin:10px 0;line-height:2;color:#4a5568">{line}</p>')

    if in_list: html_lines.append('</ul>')
    return '\n'.join(html_lines)


def _folder_hash(dpath):
    """计算文件夹内容哈希（用于判断是否有变化）"""
    h = hashlib.md5()
    for fname in sorted(os.listdir(dpath)):
        if fname.startswith('.'): continue
        fpath = os.path.join(dpath, fname)
        h.update(fname.encode())
        h.update(str(os.path.getsize(fpath)).encode() if os.path.isfile(fpath) else b'd')
    return h.hexdigest()


def _compress_image(src, dst):
    """压缩单张图片"""
    subprocess.run(["sips", "--resampleWidth", "600", "-s", "format", "jpeg",
                   "-s", "formatOptions", "60", src, "--out", dst],
                   capture_output=True, timeout=30)
    return os.path.exists(dst)


# ====== 独立页面模板 ======

ARTICLE_PAGE_CSS = '''    :root {
      --primary: #0d2340; --primary-light: #1a3a5c; --primary-dark: #081828;
      --gold: #c9a84c; --gold-light: #e8c97a; --text-dark: #1a1a2e;
      --text-mid: #4a5568; --text-light: #718096; --bg-light: #f7f8fc;
      --bg-white: #ffffff; --border: #e2e8f0;
      --shadow: 0 4px 20px rgba(13,35,64,0.10);
      --shadow-lg: 0 8px 40px rgba(13,35,64,0.16);
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      font-family: 'SimSun', 'STSong', '宋体', 'Microsoft YaHei', '微软雅黑', serif;
      color: var(--text-dark); background: var(--bg-white); line-height: 1.9;
    }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #f1f1f1; }
    ::-webkit-scrollbar-thumb { background: var(--primary-light); border-radius: 3px; }

    #navbar {
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
      background: rgba(8,24,40,0.97); backdrop-filter: blur(10px);
      border-bottom: 1px solid rgba(201,168,76,0.3);
    }
    .nav-inner {
      max-width: 1280px; margin: 0 auto; padding: 0 24px;
      display: flex; align-items: center; justify-content: space-between; height: 68px;
    }
    .nav-logo { display: flex; align-items: center; gap: 12px; text-decoration: none; }
    .logo-icon {
      width: 42px; height: 42px; background: linear-gradient(135deg, var(--gold), var(--gold-light));
      border-radius: 6px; display: flex; align-items: center; justify-content: center;
      font-size: 20px; color: var(--primary-dark); font-weight: bold; font-family: 'SimSun', serif;
    }
    .logo-name {
      font-size: 18px; font-weight: bold; font-family: 'SimHei', '黑体', 'Microsoft YaHei', sans-serif;
      letter-spacing: 2px; color: white;
    }
    .logo-sub { font-size: 11px; color: var(--gold-light); letter-spacing: 3px; }
    .nav-home {
      color: var(--gold-light); text-decoration: none; font-size: 13px;
      font-family: 'SimHei', '黑体', sans-serif; padding: 6px 14px; border: 1px solid rgba(201,168,76,0.4);
      border-radius: 4px; transition: all 0.2s;
    }
    .nav-home:hover { background: rgba(201,168,76,0.12); }

    .container { max-width: 860px; margin: 0 auto; padding: 0 24px; }
    .breadcrumb { padding: 100px 0 20px; font-size: 13px; color: var(--text-light); }
    .breadcrumb a { color: var(--gold); text-decoration: none; }
    .breadcrumb a:hover { text-decoration: underline; }
    .breadcrumb span { margin: 0 8px; color: var(--border); }

    .article-header { margin-bottom: 40px; padding-bottom: 28px; border-bottom: 1px solid var(--border); }
    .article-header h1 {
      font-size: 28px; font-family: 'SimHei', '黑体', 'Microsoft YaHei', sans-serif;
      color: var(--primary); line-height: 1.4; margin-bottom: 16px; letter-spacing: 1px;
    }
    .article-meta { font-size: 13px; color: var(--text-light); display: flex; gap: 20px; flex-wrap: wrap; }
    .article-meta .tag {
      background: rgba(13,35,64,0.06); color: var(--primary); padding: 2px 10px;
      border-radius: 3px; font-family: 'SimHei', '黑体', sans-serif; font-size: 12px;
    }

    .article-body { font-size: 15px; color: var(--text-mid); line-height: 2; }
    .article-body h2 {
      color: var(--primary); font-family: 'SimHei', '黑体', sans-serif; font-size: 22px;
      margin: 36px 0 16px; padding-left: 14px; border-left: 4px solid var(--gold);
    }
    .article-body h3 {
      color: var(--primary); font-family: 'SimHei', '黑体', sans-serif; font-size: 17px;
      margin: 28px 0 12px;
    }
    .article-body p { margin: 12px 0; }
    .article-body ul, .article-body ol { padding-left: 24px; margin: 12px 0; }
    .article-body li { margin: 6px 0; }
    .article-body img {
      max-width: 100%; border-radius: 8px; margin: 20px 0; box-shadow: var(--shadow);
    }
    .article-body strong { color: var(--primary-dark); }
    .article-body blockquote {
      border-left: 3px solid var(--gold); padding: 12px 20px; margin: 20px 0;
      background: rgba(201,168,76,0.06); border-radius: 0 6px 6px 0; color: var(--text-mid); font-style: italic;
    }

    .article-footer {
      margin-top: 60px; padding-top: 28px; border-top: 1px solid var(--border);
      display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;
    }
    .back-link {
      color: var(--gold); text-decoration: none; font-size: 14px; font-family: 'SimHei', '黑体', sans-serif;
      display: inline-flex; align-items: center; gap: 6px; transition: gap 0.2s;
    }
    .back-link:hover { gap: 10px; }
    .share-hint { font-size: 13px; color: var(--text-light); }

    footer {
      background: var(--primary-dark); color: rgba(255,255,255,0.5); padding: 32px 0; margin-top: 80px;
      text-align: center; font-size: 12px; line-height: 1.8;
    }
    footer .gold { color: var(--gold-light); }
    .footer-disclaimer {
      max-width: 860px; margin: 0 auto 16px; padding: 10px 16px;
      background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
      border-radius: 4px; font-size: 11px; color: rgba(255,255,255,0.35); line-height: 1.7;
    }

    #backTop {
      position: fixed; bottom: 32px; right: 32px; width: 44px; height: 44px;
      background: var(--primary); border: 2px solid var(--gold); color: var(--gold-light);
      border-radius: 50%; display: flex; align-items: center; justify-content: center;
      cursor: pointer; font-size: 16px; transition: all 0.3s; opacity: 0; transform: translateY(20px);
      z-index: 999; box-shadow: 0 4px 16px rgba(13,35,64,0.3);
    }
    #backTop.visible { opacity: 1; transform: translateY(0); }
    #backTop:hover { background: var(--gold); color: var(--primary-dark); transform: translateY(-2px); }

    @media (max-width: 768px) {
      .article-header h1 { font-size: 22px; }
      .article-body { font-size: 14px; }
      .article-body h2 { font-size: 18px; }
      .article-body h3 { font-size: 15px; }
    }'''


def generate_article_page(article, canonical_url):
    """生成文章独立页面 HTML"""
    title = article['title']
    date = article['date']
    body_html = article['body_html']
    excerpt = article['excerpt']
    safe_id = article['safe_id']

    # 提取纯文本摘要(去除HTML标签)
    import re as _re
    plain_excerpt = _re.sub(r'<[^>]+>', '', excerpt)[:160]
    if len(excerpt) > 160:
        plain_excerpt += '...'

    page_title = f"{title} - 周义军律师 | 温州税务律师 · 浙江涉税争议解决专家 · 全国接案"
    page_desc = plain_excerpt or f"周义军律师专业文章：{title}。温州税务律师、浙江涉税争议解决专家，深耕涉税法律领域15年以上，全国接案。"

    # BreadcrumbList JSON-LD
    breadcrumb_ld = f'''<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "首页", "item": "https://zhouyijunlawyer.com/"}},
    {{"@type": "ListItem", "position": 2, "name": "专业文章", "item": "https://zhouyijunlawyer.com/#articles"}},
    {{"@type": "ListItem", "position": 3, "name": "{title}"}}
  ]
}}
</script>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<meta name="description" content="{page_desc}">
<meta name="keywords" content="周义军,温州税务律师,浙江税务律师,全国税务律师,涉税律师,{title}">
<meta name="author" content="周义军律师">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{page_title}">
<meta property="og:description" content="{page_desc}">
<meta property="og:url" content="{canonical_url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="周义军律师">
<meta property="og:locale" content="zh_CN">
<meta property="article:published_time" content="{date}">
<meta property="article:author" content="周义军律师">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{page_title}">
<meta name="twitter:description" content="{page_desc}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{title}",
  "description": "{page_desc}",
  "author": {{
    "@type": "Person",
    "name": "周义军",
    "jobTitle": "专职律师",
    "description": "温州税务律师、浙江省涉税争议解决专家，律师+税务师双证，15年以上涉税法律经验",
    "affiliation": {{
      "@type": "Organization",
      "name": "浙江六和（温州）律师事务所",
      "address": {{"@type": "PostalAddress", "addressLocality": "温州市", "addressRegion": "浙江省"}}
    }}
  }},
  "datePublished": "{date}",
  "publisher": {{
    "@type": "LegalService",
    "name": "周义军律师 - 温州税务律师",
    "url": "https://zhouyijunlawyer.com",
    "address": {{"@type": "PostalAddress", "addressLocality": "温州市", "addressRegion": "浙江省", "addressCountry": "CN"}}
  }},
  "mainEntityOfPage": {{"@type": "WebPage", "@id": "{canonical_url}"}},
  "about": [
    {{"@type": "Thing", "name": "税务法律"}},
    {{"@type": "Thing", "name": "涉税争议解决"}}
  ]
}}
</script>
{breadcrumb_ld}
<style>
{ARTICLE_PAGE_CSS}
</style>
</head>
<body>

<nav id="navbar">
  <div class="nav-inner">
    <a class="nav-logo" href="/">
      <div class="logo-icon">律</div>
      <div class="logo-text">
        <div class="logo-name">周义军律师</div>
        <div class="logo-sub">全国涉税争议解决专家</div>
      </div>
    </a>
    <a class="nav-home" href="/">← 返回首页</a>
  </div>
</nav>

<div class="container">
  <nav class="breadcrumb" aria-label="面包屑导航">
    <a href="/">首页</a><span>›</span><a href="/#articles">专业文章</a><span>›</span>{title}
  </nav>

  <article>
    <header class="article-header">
      <h1>{title}</h1>
      <div class="article-meta">
        <span>📅 {date}</span>
        <span class="tag">专业文章</span>
        <span>✍️ 周义军律师</span>
      </div>
    </header>

    <div class="article-body">
{body_html}
    </div>
  </article>

  <div class="article-footer">
    <a class="back-link" href="/#articles">← 返回专业文章列表</a>
    <div class="share-hint">📱 觉得有用？分享给需要的人</div>
  </div>
</div>

<footer>
  <div class="footer-disclaimer">
    ⚠️ 执业声明：本文仅供法律知识参考，不构成具体法律意见。如需法律帮助，请直接联系律师进行专业咨询。
  </div>
  <div style="max-width:860px;margin:0 auto;padding:0 24px;">
    © 2024 周义军律师 · 浙江六和（温州）律师事务所 · <span class="gold">全国涉税争议解决专家</span><br>
    📞 13857739079（微信同号）· 📍 温州市鹿城区府东路476号宏国大厦11楼
  </div>
</footer>

<div id="backTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">▲</div>

<script>
window.addEventListener('scroll',function(){{var b=document.getElementById('backTop');if(window.scrollY>400)b.classList.add('visible');else b.classList.remove('visible')}});
</script>
</body>
</html>'''


def generate_comic_page(comic, canonical_url):
    """生成漫画独立页面 HTML（SEO 友好，图片带 alt）"""
    title = comic['title']
    images = comic['images']

    page_title = f"{title} - 普法漫画 | 周义军律师 · 温州税务律师 · 全国接案"
    page_desc = f"周义军律师普法漫画：{title}。温州税务律师、浙江涉税争议解决专家，通过生动有趣的漫画形式，为您解读涉税法律问题，让法律知识触手可及。"

    # 生成图片列表（带 alt 和 loading=lazy，3列网格铺满屏幕）
    img_tags = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;width:100%;">\n'
    for i, img in enumerate(images):
        alt_text = f"{title} - 第{i+1}页"
        img_tags += f'        <img src="/{img["file"]}" alt="{alt_text}" loading="lazy" style="width:100%;border-radius:8px;box-shadow:var(--shadow)">\n'
    img_tags += '      </div>'

    breadcrumb_ld = f'''<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "首页", "item": "https://zhouyijunlawyer.com/"}},
    {{"@type": "ListItem", "position": 2, "name": "普法漫画", "item": "https://zhouyijunlawyer.com/#comics"}},
    {{"@type": "ListItem", "position": 3, "name": "{title}"}}
  ]
}}
</script>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<meta name="description" content="{page_desc}">
<meta name="keywords" content="周义军,温州税务律师,全国税务律师,普法漫画,税务律师,{title}">
<meta name="author" content="周义军律师">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{page_title}">
<meta property="og:description" content="{page_desc}">
<meta property="og:url" content="{canonical_url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="周义军律师">
<meta property="og:locale" content="zh_CN">
<meta property="og:image" content="https://zhouyijunlawyer.com/{images[0]['file']}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{page_title}">
<meta name="twitter:description" content="{page_desc}">
<meta name="twitter:image" content="https://zhouyijunlawyer.com/{images[0]['file']}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{title}",
  "description": "{page_desc}",
  "author": {{
    "@type": "Person",
    "name": "周义军",
    "jobTitle": "专职律师",
    "description": "温州税务律师、浙江省涉税争议解决专家，律师+税务师双证",
    "affiliation": {{
      "@type": "Organization",
      "name": "浙江六和（温州）律师事务所",
      "address": {{"@type": "PostalAddress", "addressLocality": "温州市", "addressRegion": "浙江省"}}
    }}
  }},
  "publisher": {{
    "@type": "LegalService",
    "name": "周义军律师 - 温州税务律师",
    "url": "https://zhouyijunlawyer.com",
    "address": {{"@type": "PostalAddress", "addressLocality": "温州市", "addressRegion": "浙江省", "addressCountry": "CN"}}
  }},
  "mainEntityOfPage": {{"@type": "WebPage", "@id": "{canonical_url}"}},
  "thumbnailUrl": "https://zhouyijunlawyer.com/{images[0]['file']}"
}}
</script>
{breadcrumb_ld}
<style>
{ARTICLE_PAGE_CSS}
    /* 漫画页容器加宽，让3列图片铺满屏幕 */
    .container {{ max-width: 1160px; }}
    @media (max-width: 1200px) {{ .container {{ max-width: 96vw; }} }}
    @media (max-width: 768px) {{
      .article-body > div:first-child {{ grid-template-columns: repeat(2, 1fr) !important; }}
    }}
    @media (max-width: 480px) {{
      .article-body > div:first-child {{ grid-template-columns: 1fr !important; }}
    }}
</style>
</head>
<body>

<nav id="navbar">
  <div class="nav-inner">
    <a class="nav-logo" href="/">
      <div class="logo-icon">律</div>
      <div class="logo-text">
        <div class="logo-name">周义军律师</div>
        <div class="logo-sub">全国涉税争议解决专家</div>
      </div>
    </a>
    <a class="nav-home" href="/">← 返回首页</a>
  </div>
</nav>

<div class="container">
  <nav class="breadcrumb" aria-label="面包屑导航">
    <a href="/">首页</a><span>›</span><a href="/#comics">普法漫画</a><span>›</span>{title}
  </nav>

  <article>
    <header class="article-header">
      <h1>{title}</h1>
      <div class="article-meta">
        <span>🎨 普法漫画</span>
        <span>📄 {len(images)} 页</span>
        <span>✍️ 周义军律师</span>
      </div>
    </header>

    <div class="article-body" style="max-width:1100px;margin:0 auto;">
{img_tags}    </div>
  </article>

  <div class="article-footer">
    <a class="back-link" href="/#comics">← 返回普法漫画列表</a>
    <div class="share-hint">📱 觉得有用？分享给需要的人</div>
  </div>
</div>

<footer>
  <div class="footer-disclaimer">
    ⚠️ 执业声明：本漫画仅供法律知识普及参考，不构成具体法律意见。如需法律帮助，请直接联系律师进行专业咨询。
  </div>
  <div style="max-width:860px;margin:0 auto;padding:0 24px;">
    © 2024 周义军律师 · 浙江六和（温州）律师事务所 · <span class="gold">全国涉税争议解决专家</span><br>
    📞 13857739079（微信同号）· 📍 温州市鹿城区府东路476号宏国大厦11楼
  </div>
</footer>

<div id="backTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">▲</div>

<script>
window.addEventListener('scroll',function(){{var b=document.getElementById('backTop');if(window.scrollY>400)b.classList.add('visible');else b.classList.remove('visible')}});
</script>
</body>
</html>'''


def _make_slug(text):
    """从中文标题生成URL安全的slug"""
    import re as _re
    # 保留中文、字母、数字，其他替换为连字符
    slug = _re.sub(r'[^\w一-鿿]+', '-', text).strip('-')
    return slug[:60] or 'article'


def main():
    # ====== 初始化 ======
    if os.path.exists(DEPLOY_DIR):
        shutil.rmtree(DEPLOY_DIR)
    os.makedirs(f"{DEPLOY_DIR}/comics", exist_ok=True)

    if not os.path.exists(TOKEN_FILE):
        print("❌ Token 文件不存在")
        sys.exit(1)
    token = open(TOKEN_FILE).read().strip()

    # =========================================
    # 第一部分：处理漫画（增量检测）
    # =========================================
    print("📘 === 漫画 ===")
    comics = []
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
    cache_comics = cache.get("comics", {})
    new_cache = {}
    os.makedirs(CACHE_IMG_DIR, exist_ok=True)

    if os.path.exists(COMICS_DIR):
        dirnames = sorted([d for d in os.listdir(COMICS_DIR) if not d.startswith('.')], reverse=True)
        unchanged = 0
        for dirname in dirnames:
            dpath = os.path.join(COMICS_DIR, dirname)
            if not os.path.isdir(dpath): continue
            imgs = sorted([f for f in os.listdir(dpath) if f.lower().endswith(('.jpg','.jpeg','.png'))])
            if not imgs: continue

            folder_hash = hashlib.md5(dirname.encode()).hexdigest()[:10]
            cache_comic_dir = os.path.join(CACHE_IMG_DIR, folder_hash)
            deploy_comic_dir = os.path.join(DEPLOY_DIR, "comics", folder_hash)
            content_hash = _folder_hash(dpath)
            cached_hash = cache_comics.get(folder_hash)

            title = re.sub(r'^\d{8}', '', dirname)

            if content_hash == cached_hash and os.path.exists(cache_comic_dir):
                # 没变化，直接从持久缓存复制
                unchanged += 1
                os.makedirs(deploy_comic_dir, exist_ok=True)
                compressed = []
                for i, img in enumerate(imgs):
                    fn = f"{i+1}.jpg"
                    cached_img = os.path.join(cache_comic_dir, fn)
                    deploy_img = os.path.join(deploy_comic_dir, fn)
                    if os.path.exists(cached_img):
                        shutil.copy2(cached_img, deploy_img)
                        compressed.append({"file": f"comics/{folder_hash}/{fn}",
                                           "size_kb": round(os.path.getsize(deploy_img)/1024)})
                if len(compressed) != len(imgs):
                    # 缓存不完整，回退压缩
                    compressed = []
                    for i, img in enumerate(imgs):
                        src = os.path.join(dpath, img)
                        dst = os.path.join(deploy_comic_dir, f"{i+1}.jpg")
                        if _compress_image(src, dst):
                            compressed.append({"file": f"comics/{folder_hash}/{i+1}.jpg",
                                               "size_kb": round(os.path.getsize(dst)/1024)})
                    # 更新持久缓存
                    shutil.rmtree(cache_comic_dir, ignore_errors=True)
                    os.makedirs(cache_comic_dir, exist_ok=True)
                    for i in range(1, len(compressed)+1):
                        shutil.copy2(os.path.join(deploy_comic_dir, f"{i}.jpg"),
                                    os.path.join(cache_comic_dir, f"{i}.jpg"))
            else:
                # 新内容或内容变化，重新压缩
                os.makedirs(deploy_comic_dir, exist_ok=True)
                shutil.rmtree(cache_comic_dir, ignore_errors=True)
                os.makedirs(cache_comic_dir, exist_ok=True)
                compressed = []
                for i, img in enumerate(imgs):
                    src = os.path.join(dpath, img)
                    deploy_dst = os.path.join(deploy_comic_dir, f"{i+1}.jpg")
                    cache_dst = os.path.join(cache_comic_dir, f"{i+1}.jpg")
                    if _compress_image(src, deploy_dst):
                        shutil.copy2(deploy_dst, cache_dst)
                        compressed.append({"file": f"comics/{folder_hash}/{i+1}.jpg",
                                           "size_kb": round(os.path.getsize(deploy_dst)/1024)})

                tag = "🆕 新增" if folder_hash not in cache_comics else "📝 更新"
                print(f"  {tag} {title[:45]}")

            total_kb = sum(x['size_kb'] for x in compressed)
            comics.append({"title": title, "images": compressed, "total_kb": total_kb, "folder_hash": folder_hash, "slug": _make_slug(title)})
            new_cache[folder_hash] = content_hash

        if unchanged > 0:
            print(f"  ⏭ 跳过 {unchanged} 套无变化")

    # 保存缓存
    cache["comics"] = new_cache
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

    # =========================================
    # 第二部分：处理文章
    # =========================================
    print("\n📝 === 文章 ===")
    articles = []
    if os.path.exists(ARTICLES_DIR):
        for f in sorted(os.listdir(ARTICLES_DIR), reverse=True):
            if not f.endswith('.md'): continue
            fpath = os.path.join(ARTICLES_DIR, f)
            with open(fpath, 'r') as fh:
                content = fh.read()

            match = re.match(r'^(\d{8})(.+)\.md$', f)
            if match:
                date_str = match.group(1)
                title = match.group(2)
                formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                title = f.replace('.md', '')
                formatted_date = ''

            first_para = ''
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    first_para = stripped[:150] + ('...' if len(stripped) > 150 else '')
                    break

            body_html = md_to_html(content)
            safe_id = hashlib.md5(title.encode()).hexdigest()[:8]
            slug = _make_slug(title)

            articles.append({
                'title': title, 'date': formatted_date, 'excerpt': first_para,
                'body_html': body_html, 'safe_id': safe_id, 'slug': slug
            })
            print(f"  [{formatted_date}] {title[:45]}")

    # =========================================
    # 第三部分：生成 HTML
    # =========================================
    with open(SITE_TEMPLATE, 'r') as f:
        html = f.read()

    # --- 复制文章中的本地图片到部署目录 ---
    for a in articles:
        # 查找 body_html 中的本地图片路径
        img_matches = re.findall(r'src=["\'](images/[^"\']+)["\']', a['body_html'])
        for img_rel in img_matches:
            src_path = os.path.join(ARTICLES_DIR, img_rel)
            dst_path = os.path.join(DEPLOY_DIR, img_rel)
            if os.path.exists(src_path):
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(src_path, dst_path)
                print(f"  📎 复制图片: {img_rel}")

    # --- 复制微信二维码到部署目录 ---
    qr_src = os.path.join(os.path.dirname(SITE_TEMPLATE), "images", "wechat-qr.png")
    qr_dst_dir = os.path.join(DEPLOY_DIR, "images")
    qr_dst = os.path.join(qr_dst_dir, "wechat-qr.png")
    if os.path.exists(qr_src):
        os.makedirs(qr_dst_dir, exist_ok=True)
        shutil.copy2(qr_src, qr_dst)
        print(f"  📱 复制微信二维码: images/wechat-qr.png")
    else:
        print(f"  ⚠️ 微信二维码未找到，请将二维码图片放到 template/images/wechat-qr.png")

    # --- 复制执业机构图标 ---
    icon_src = os.path.join(os.path.dirname(SITE_TEMPLATE), "images", "jigou-icon.png")
    icon_dst = os.path.join(qr_dst_dir, "jigou-icon.png")
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, icon_dst)

    # --- 漫画区域 ---
    cards_html = ""
    for c in comics:
        first_img = c['images'][0]['file']
        cards_html += f'      <a class="comic-card" href="/comics/{c["folder_hash"]}/" style="text-decoration:none;color:inherit">\n'
        cards_html += f'        <div class="comic-thumb" style="background-image:url(\'/{first_img}\');background-size:cover;background-position:center"></div>\n'
        cards_html += f'        <div class="comic-info">\n          <div class="comic-title">{c["title"]}</div>\n'
        cards_html += f'          <div class="comic-meta"><span>普法漫画</span><span>{len(c["images"])}页</span></div>\n        </div>\n      </a>\n'

    old_comics = html.find('<section id="comics">')
    old_comics_end = html.find('</section>', old_comics) + len('</section>')
    total_pages = (len(comics) + 9) // 10 if comics else 1
    new_comics = f'''<section id="comics">
  <div class="container">
    <div class="section-header">
      <div class="section-tag">LEGAL COMICS</div>
      <h2 class="section-title">普法漫画 · <span class="gold">让法律更易懂</span></h2>
      <div class="section-divider"></div>
      <p class="section-desc">通过生动有趣的漫画形式，为您解读复杂的涉税法律问题，让法律知识触手可及</p>
    </div>
    <div class="comics-top-bar">
      <div class="comics-count-info">共 <strong class="gold" id="comicsTotal">{len(comics)}</strong> 集 · 第 <strong id="comicsCurrentPage">1</strong>/<strong id="comicsTotalPages">{total_pages}</strong> 页</div>
    </div>
    <div class="comics-grid" id="comicsGrid">
{cards_html}    </div>
    <div class="comics-pagination" id="comicsPagination"></div>
  </div>
</section>
<script>
(function(){{
  var COMICS_PER_PAGE = 10;
  var grid = document.getElementById('comicsGrid');
  if (!grid) return;
  var cards = grid.querySelectorAll('.comic-card');
  if (cards.length <= COMICS_PER_PAGE) return;
  cards.forEach(function(card, i) {{
    if (i >= COMICS_PER_PAGE) card.classList.add('comic-hidden');
  }});
  var totalPages = Math.ceil(cards.length / COMICS_PER_PAGE);
  var pgEl = document.getElementById('comicsPagination');
  if (pgEl) pgEl.style.display = 'flex';
  function buildBtns() {{
    var pgEl = document.getElementById('comicsPagination');
    if (!pgEl) return;
    var html = '';
    var cp = window._comicsPage || 1;
    html += '<button class="comics-page-btn' + (cp===1?' disabled':'') + '" onclick="window._goPage(' + (cp-1) + ')">← 上一页</button>';
    for (var p=1; p<=totalPages; p++) {{
      if (totalPages<=7 || p===1 || p===totalPages || (p>=cp-1 && p<=cp+1)) {{
        html += '<button class="comics-page-btn' + (p===cp?' active':'') + '" onclick="window._goPage(' + p + ')">' + p + '</button>';
      }} else if (p===cp-2 || p===cp+2) {{
        html += '<span class="comics-page-ellipsis">…</span>';
      }}
    }}
    html += '<button class="comics-page-btn' + (cp===totalPages?' disabled':'') + '" onclick="window._goPage(' + (cp+1) + ')">下一页 →</button>';
    pgEl.innerHTML = html;
  }}
  window._goPage = function(page) {{
    if (page<1 || page>totalPages) return;
    window._comicsPage = page;
    var cards = document.querySelectorAll('#comicsGrid .comic-card');
    var start = (page-1)*COMICS_PER_PAGE;
    var end = start+COMICS_PER_PAGE;
    cards.forEach(function(card, i) {{ card.classList.toggle('comic-hidden', i<start || i>=end); }});
    document.getElementById('comicsCurrentPage').textContent = page;
    buildBtns();
  }};
  window._comicsPage = 1;
  buildBtns();
}})();
</script>'''
    html = html[:old_comics] + new_comics + html[old_comics_end:]

    # --- 文章区域 ---
    article_cards = ""
    for a in articles:
        article_cards += f'''      <a class="article-card" href="/articles/{a['slug']}/" style="text-decoration:none;color:inherit">
        <div class="article-date">
          <div class="article-day">{a['date'][8:10] if len(a['date'])==10 else ''}</div>
          <div class="article-month">{a['date'][:7] if a['date'] else ''}</div>
        </div>
        <div class="article-content">
          <div class="article-tags"><span class="article-tag">专业文章</span></div>
          <div class="article-title">{a['title']}</div>
          <div class="article-excerpt">{a['excerpt']}</div>
          <div class="article-read">阅读全文 →</div>
        </div>
      </a>
'''

    old_articles = html.find('<section id="articles">')
    old_articles_end = html.find('</section>', old_articles) + len('</section>')
    new_articles = f'''<section id="articles">
  <div class="container">
    <div class="section-header">
      <div class="section-tag">PROFESSIONAL ARTICLES</div>
      <h2 class="section-title">专业<span class="gold">文章</span></h2>
      <div class="section-divider"></div>
      <p class="section-desc">深耕涉税法律实务，分享专业见解与案例解读</p>
    </div>
    <div class="articles-list">
{article_cards}    </div>
  </div>
</section>'''
    html = html[:old_articles] + new_articles + html[old_articles_end:]

    with open(f"{DEPLOY_DIR}/index.html", 'w') as f:
        f.write(html)

    # =========================================
    # 第三点五部分：生成独立页面 + SEO 文件
    # =========================================

    # --- 文章独立页面 ---
    articles_dir = os.path.join(DEPLOY_DIR, "articles")
    os.makedirs(articles_dir, exist_ok=True)
    for a in articles:
        page_dir = os.path.join(articles_dir, a['slug'])
        os.makedirs(page_dir, exist_ok=True)
        page_url = f"https://zhouyijunlawyer.com/articles/{a['slug']}/"
        page_html = generate_article_page(a, page_url)
        with open(os.path.join(page_dir, "index.html"), 'w') as f:
            f.write(page_html)
        print(f"  📄 文章页: /articles/{a['slug']}/")

    # --- 漫画独立页面 ---
    comics_pages_dir = os.path.join(DEPLOY_DIR, "comics")
    os.makedirs(comics_pages_dir, exist_ok=True)
    for c in comics:
        page_dir = os.path.join(comics_pages_dir, c['folder_hash'])
        os.makedirs(page_dir, exist_ok=True)
        page_url = f"https://zhouyijunlawyer.com/comics/{c['folder_hash']}/"
        page_html = generate_comic_page(c, page_url)
        with open(os.path.join(page_dir, "index.html"), 'w') as f:
            f.write(page_html)
        print(f"  🎨 漫画页: /comics/{c['folder_hash']}/")

    # --- robots.txt ---
    robots_txt = f"""User-agent: *
Allow: /
Disallow: /images/

Sitemap: https://zhouyijunlawyer.com/sitemap.xml
"""
    with open(os.path.join(DEPLOY_DIR, "robots.txt"), 'w') as f:
        f.write(robots_txt)
    print("  🤖 robots.txt 已生成")

    # --- sitemap.xml ---
    now_iso = time.strftime("%Y-%m-%d")
    sitemap_urls = []
    # 首页
    sitemap_urls.append(f'''  <url>
    <loc>https://zhouyijunlawyer.com/</loc>
    <lastmod>{now_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>''')
    # 文章页
    for a in articles:
        sitemap_urls.append(f'''  <url>
    <loc>https://zhouyijunlawyer.com/articles/{a['slug']}/</loc>
    <lastmod>{a['date']}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>''')
    # 漫画页
    for c in comics:
        sitemap_urls.append(f'''  <url>
    <loc>https://zhouyijunlawyer.com/comics/{c['folder_hash']}/</loc>
    <lastmod>{now_iso}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>''')

    sitemap_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(sitemap_urls)}
</urlset>'''
    with open(os.path.join(DEPLOY_DIR, "sitemap.xml"), 'w') as f:
        f.write(sitemap_xml)
    print(f"  🗺 sitemap.xml 已生成 ({len(sitemap_urls)} 个URL)")

    # --- RSS Feed ---
    rss_items = []
    for a in articles:
        rss_items.append(f'''    <item>
      <title><![CDATA[{a['title']}]]></title>
      <link>https://zhouyijunlawyer.com/articles/{a['slug']}/</link>
      <description><![CDATA[{a['excerpt']}]]></description>
      <author>周义军律师</author>
      <pubDate>{a['date']}</pubDate>
      <guid isPermaLink="true">https://zhouyijunlawyer.com/articles/{a['slug']}/</guid>
    </item>''')
    for c in comics:
        rss_items.append(f'''    <item>
      <title><![CDATA[[普法漫画] {c['title']}]]></title>
      <link>https://zhouyijunlawyer.com/comics/{c['folder_hash']}/</link>
      <description><![CDATA[周义军律师普法漫画：{c['title']}。共{len(c['images'])}页，通过漫画形式解读涉税法律知识。]]></description>
      <author>周义军律师</author>
      <pubDate>{now_iso}</pubDate>
      <guid isPermaLink="true">https://zhouyijunlawyer.com/comics/{c['folder_hash']}/</guid>
    </item>''')

    rss_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>周义军律师 - 温州税务律师 · 浙江涉税争议解决专家 · 全国接案</title>
  <link>https://zhouyijunlawyer.com</link>
  <description>全国税务律师周义军，温州税务律师、浙江省涉税争议解决专家，专注税务稽查应对、税务行政诉讼、涉税刑事辩护。律师+税务师双证，15年以上经验，全国接案。</description>
  <language>zh-CN</language>
  <lastBuildDate>{now_iso}</lastBuildDate>
  <atom:link href="https://zhouyijunlawyer.com/rss.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(rss_items)}
</channel>
</rss>'''
    with open(os.path.join(DEPLOY_DIR, "rss.xml"), 'w') as f:
        f.write(rss_xml)
    print(f"  📡 rss.xml 已生成 ({len(rss_items)} 条)")

    # =========================================
    # 第四部分：部署
    # =========================================
    total_bytes = sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(DEPLOY_DIR) for f in fs)
    print(f"\n📦 部署包: {total_bytes/1024/1024:.1f}MB")
    print(f"  漫画: {len(comics)} 套 | 文章: {len(articles)} 篇")
    print(f"\n🚀 部署到 Cloudflare Pages...")

    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", ".", "--project-name", PROJ_NAME, "--branch", "main"],
        cwd=DEPLOY_DIR,
        env={**os.environ, "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": ACCT_ID},
        capture_output=True, text=True, timeout=300
    )

    if result.returncode == 0:
        print("✅ 部署成功！")
        for d in DOMAINS:
            print(f"   https://{d}")
    else:
        print(f"❌ 部署失败:\n{result.stderr}")


if __name__ == "__main__":
    main()
