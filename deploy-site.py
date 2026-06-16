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
        dirnames = sorted([d for d in os.listdir(COMICS_DIR) if not d.startswith('.')])
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
            comics.append({"title": title, "images": compressed, "total_kb": total_kb})
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

            articles.append({
                'title': title, 'date': formatted_date, 'excerpt': first_para,
                'body_html': body_html, 'safe_id': safe_id
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

    # --- 漫画区域 ---
    cards_html = ""
    for c in comics:
        first_img = c['images'][0]['file']
        imgs_json = json.dumps(c['images'], ensure_ascii=False).replace('"', '&quot;')
        title_escaped = c['title'].replace("'", "\\'").replace('"', '\\"')
        cards_html += f'      <div class="comic-card" onclick="openComic(\'{title_escaped}\', {imgs_json})">\n'
        cards_html += f'        <div class="comic-thumb" style="background-image:url(\'{first_img}\');background-size:cover;background-position:center"></div>\n'
        cards_html += f'        <div class="comic-info">\n          <div class="comic-title">{c["title"]}</div>\n'
        cards_html += f'          <div class="comic-meta"><span>普法漫画</span><span>{len(c["images"])}页</span></div>\n        </div>\n      </div>\n'

    old_comics = html.find('<section id="comics">')
    old_comics_end = html.find('</section>', old_comics) + len('</section>')
    new_comics = f'''<section id="comics">
  <div class="container">
    <div class="section-header">
      <div class="section-tag">LEGAL COMICS</div>
      <h2 class="section-title">普法漫画 · <span class="gold">让法律更易懂</span></h2>
      <div class="section-divider"></div>
      <p class="section-desc">通过生动有趣的漫画形式，为您解读复杂的涉税法律问题，让法律知识触手可及</p>
    </div>
    <div class="comics-grid">
{cards_html}    </div>
  </div>
</section>'''
    html = html[:old_comics] + new_comics + html[old_comics_end:]

    # --- 文章区域 ---
    article_cards = ""
    for a in articles:
        body_html = a['body_html'].replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#39;').replace('\n', '')
        title_escaped = a['title'].replace("'", "\\'").replace('"', '\\"')
        article_cards += f'''      <div class="article-card" onclick="openArticle('{title_escaped}', '{body_html}')">
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
      </div>
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

    # --- 弹窗组件 ---
    modal = '''
<div id="comicModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.95);z-index:10000;overflow-y:auto">
  <div style="position:fixed;top:16px;right:24px;z-index:10001">
    <button onclick="closeModal()" style="background:rgba(255,255,255,0.2);color:white;border:none;padding:12px 20px;border-radius:6px;cursor:pointer;font-size:16px;font-family:SimHei,sans-serif">✕ 关闭</button>
  </div>
  <div id="comicModalContent" style="max-width:1420px;margin:40px auto;padding:20px"></div>
</div>
<div id="articleModal" style="display:none;position:fixed;inset:0;background:white;z-index:10000;overflow-y:auto">
  <div style="position:fixed;top:16px;right:24px;z-index:10001">
    <button onclick="closeModal()" style="background:rgba(13,35,64,0.9);color:white;border:none;padding:12px 20px;border-radius:6px;cursor:pointer;font-size:16px;font-family:SimHei,sans-serif">✕ 关闭</button>
  </div>
  <div id="articleModalContent" style="max-width:800px;margin:60px auto;padding:40px 24px"></div>
</div>
<script>
function openComic(title,images){var cols=window.innerWidth<640?1:window.innerWidth<960?2:3;var h='<h2 style="color:#c9a84c;text-align:center;margin-bottom:30px;font-family:SimHei,sans-serif">'+title+"</h2><div style='display:grid;grid-template-columns:repeat("+cols+",1fr);gap:16px'>";images.forEach(function(i){h+='<img src="'+i.file+'" style="width:100%;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.5)" loading="lazy">'});h+="</div>";document.getElementById("comicModalContent").innerHTML=h;document.getElementById("comicModal").style.display="block";document.getElementById("articleModal").style.display="none";document.body.style.overflow="hidden"}
function openArticle(title,body){document.getElementById("articleModalContent").innerHTML='<h1 style="color:#0d2340;font-family:SimHei,sans-serif;font-size:24px;margin-bottom:8px">'+title+'</h1><div style="width:60px;height:3px;background:linear-gradient(90deg,#c9a84c,#e8c97a);margin-bottom:30px;border-radius:2px"></div>'+body;document.getElementById("articleModal").style.display="block";document.getElementById("comicModal").style.display="none";document.body.style.overflow="hidden"}
function closeModal(){document.getElementById("comicModal").style.display="none";document.getElementById("articleModal").style.display="none";document.body.style.overflow=""}
</script>
'''
    html = html.replace('</body>', modal + '\n</body>')

    with open(f"{DEPLOY_DIR}/index.html", 'w') as f:
        f.write(html)

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
        capture_output=True, text=True, timeout=120
    )

    if result.returncode == 0:
        print("✅ 部署成功！https://zhouyijunlawyer.com")
    else:
        print(f"❌ 部署失败:\n{result.stderr}")


if __name__ == "__main__":
    main()
