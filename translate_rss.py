import os
import re
import json
import time
import requests
import feedparser
from email.utils import parsedate_to_datetime
from feedgen.feed import FeedGenerator

FEEDS = {
    "bbc": ("BBC", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    "cnbc": ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362"),
    "ft": ("金融时报", "https://www.ft.com/rss/home/international"),
    "economist": ("经济学人", "https://www.economist.com/international/rss.xml"),
    "nyt": ("纽约时报", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    "wsj": ("华尔街日报", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    "bloomberg": ("彭博社", "https://feeds.bloomberg.com/markets/news.rss"),
    "reuters": ("路透社", "https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
    "apnews": ("美联社", "https://news.google.com/rss/search?q=site:apnews.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
    "cnn": ("CNN", "https://news.google.com/rss/search?q=site:cnn.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
}

STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "as",
    "is", "are", "was", "were", "be", "been", "that", "this", "it", "from",
    "and", "or", "but", "not", "says", "say", "after", "over", "amid", "new",
    "into", "about", "up", "out", "will", "has", "have", "had", "its", "us"
}

# 全局状态：记录各引擎是否被限流 & 复用微软令牌
ENGINE_BLOCKED = {"google_gtx": False, "google_c5": False, "edge": False}
EDGE_TOKEN = None

def get_edge_token():
    """全局只获取一次微软 Edge 翻译令牌，避免重复鉴权被封"""
    global EDGE_TOKEN
    if EDGE_TOKEN:
        return EDGE_TOKEN
    try:
        r = requests.get("https://edge.microsoft.com/translate/auth", headers=HEADERS, timeout=10)
        if r.status_code == 200 and r.text:
            EDGE_TOKEN = r.text.strip()
            print("成功获取微软 Edge 翻译令牌")
            return EDGE_TOKEN
        else:
            print(f"获取微软令牌失败: HTTP {r.status_code}")
            ENGINE_BLOCKED["edge"] = True
    except Exception as e:
        print(f"获取微软令牌异常: {e}")
        ENGINE_BLOCKED["edge"] = True
    return None

def translate_text(text):
    """四重免费引擎自动兜底：Google gtx -> Google clients5 -> Microsoft Edge -> MyMemory"""
    if not text:
        return ""
    text = text[:1500]

    # 引擎 1: 谷歌主接口
    if not ENGINE_BLOCKED["google_gtx"]:
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
                headers=HEADERS,
                timeout=8
            )
            if r.status_code == 200:
                res = "".join([item[0] for item in r.json()[0] if item[0]])
                if res and re.search(r'[\u4e00-\u9fff]', res):
                    time.sleep(0.5)
                    return res
            else:
                print(f"引擎1(Google gtx) 限流: HTTP {r.status_code}")
                ENGINE_BLOCKED["google_gtx"] = True
        except Exception as e:
            print(f"引擎1异常: {e}")
            ENGINE_BLOCKED["google_gtx"] = True

    # 引擎 2: 谷歌客户端备用接口 (clients5)
    if not ENGINE_BLOCKED["google_c5"]:
        try:
            r = requests.get(
                "https://clients5.google.com/translate_a/t",
                params={"client": "dict-chrome-ex", "sl": "en", "tl": "zh-CN", "q": text},
                headers=HEADERS,
                timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                res = data[0] if isinstance(data, list) and isinstance(data[0], str) else ""
                if res and re.search(r'[\u4e00-\u9fff]', res):
                    time.sleep(0.5)
                    return res
            else:
                print(f"引擎2(Google c5) 限流: HTTP {r.status_code}")
                ENGINE_BLOCKED["google_c5"] = True
        except Exception as e:
            print(f"引擎2异常: {e}")
            ENGINE_BLOCKED["google_c5"] = True

    # 引擎 3: 微软 Edge 接口（复用单次令牌）
    if not ENGINE_BLOCKED["edge"]:
        token = get_edge_token()
        if token:
            try:
                r = requests.post(
                    "https://api-edge.cognitive.microsofttranslator.com/translate",
                    params={"from": "en", "to": "zh-Hans", "api-version": "3.0"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "User-Agent": HEADERS["User-Agent"]
                    },
                    json=[{"Text": text}],
                    timeout=10
                )
                if r.status_code == 200:
                    res = r.json()[0]["translations"][0]["text"]
                    if res and re.search(r'[\u4e00-\u9fff]', res):
                        time.sleep(0.4)
                        return res
                else:
                    print(f"引擎3(Microsoft Edge) 失败: HTTP {r.status_code}")
                    ENGINE_BLOCKED["edge"] = True
            except Exception as e:
                print(f"引擎3异常: {e}")
                ENGINE_BLOCKED["edge"] = True

    # 引擎 4: MyMemory 免费接口最终兜底
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:500], "langpair": "en|zh-CN"},
            headers=HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            res = r.json().get("responseData", {}).get("translatedText", "")
            if res and re.search(r'[\u4e00-\u9fff]', res) and "MYMEMORY WARNING" not in res:
                time.sleep(0.5)
                return res
    except Exception as e:
        print(f"引擎4(MyMemory) 异常: {e}")

    return text

def translate_pair(title, summary):
    """合并标题与摘要为单次请求，减少一半API调用次数"""
    if not summary:
        return translate_text(title), ""
    sep = "\n###\n"
    combined = translate_text(f"{title}{sep}{summary}")
    if "###" in combined:
        parts = combined.split("###", 1)
        return parts[0].strip(), parts[1].strip()
    # 如果分隔符意外丢失，退回单独翻译标题
    return translate_text(title), ""

def load_cache():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        cache_url = f"https://{owner}.github.io/{name}/cache.json"
        try:
            r = requests.get(cache_url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                print(f"成功加载历史翻译缓存: {len(data)} 条")
                return data
        except Exception:
            pass
    return {}

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def has_real_summary(title, summary):
    if not summary or len(summary) < 25:
        return False
    t_clean = re.sub(r'\W+', '', title.lower())
    s_clean = re.sub(r'\W+', '', summary.lower())
    if t_clean in s_clean and (len(s_clean) - len(t_clean)) < 35:
        return False
    return True

def extract_keywords(title):
    words = re.findall(r'[a-z0-9]+', title.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}

def is_duplicate(kw1, kw2):
    if not kw1 or not kw2:
        return False
    common = kw1 & kw2
    if len(common) >= 3:
        return True
    if len(common) >= 2 and (len(common) / min(len(kw1), len(kw2))) >= 0.5:
        return True
    return False

def get_timestamp(pub_str):
    if not pub_str:
        return 0
    try:
        return parsedate_to_datetime(pub_str).timestamp()
    except Exception:
        return 0

os.makedirs("public", exist_ok=True)
cache = load_cache()
new_cache = {}
all_items = []

# 1. 抓取并增量翻译10家媒体
for key, (cn_name, url) in FEEDS.items():
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"抓取失败 {key}: {e}")
        continue

    fg = FeedGenerator()
    fg.title(f"{cn_name} 实时热点")
    fg.link(href=url)
    fg.description(f"{cn_name} 自动中文翻译源")

    for entry in parsed.entries[:5]:
        raw_title = entry.get("title", "").strip()
        if not raw_title:
            continue
        if " - " in raw_title and key in ("reuters", "apnews", "cnn"):
            raw_title = raw_title.rsplit(" - ", 1)[0]

        raw_summary = clean_html(entry.get("summary", "") or entry.get("description", ""))
        valid_summary = has_real_summary(raw_title, raw_summary)
        link = entry.get("link", url)
        published = entry.get("published", "")

        cached_item = cache.get(link)
        if cached_item and re.search(r'[\u4e00-\u9fff]', cached_item.get("zh_title", "")):
            zh_title = cached_item["zh_title"]
            zh_summary = cached_item.get("zh_summary", "")
        else:
            zh_title, zh_summary = translate_pair(raw_title, raw_summary if valid_summary else "")

        if re.search(r'[\u4e00-\u9fff]', zh_title):
            new_cache[link] = {"zh_title": zh_title, "zh_summary": zh_summary}

        fe = fg.add_entry()
        fe.id(link)
        fe.title(zh_title)
        fe.link(href=link)
        desc_html = f"{zh_summary}<hr>" if zh_summary else ""
        source_html = f"<b>报道出处：</b><br>• [{cn_name}] <a href='{link}'>{zh_title}</a><br><small>原文：{raw_title}</small>"
        fe.description(f"{desc_html}{source_html}")
        if published:
            fe.published(published)

        all_items.append({
            "source": cn_name,
            "raw_title": raw_title,
            "zh_title": zh_title,
            "zh_summary": zh_summary,
            "has_summary": bool(zh_summary),
            "link": link,
            "published": published,
            "timestamp": get_timestamp(published),
            "keywords": extract_keywords(raw_title),
            "related": []
        })

    fg.rss_file(f"public/{key}.xml")
    print(f"已生成: public/{key}.xml")

# 保存翻译缓存
if len(new_cache) > 500:
    keys_to_keep = list(new_cache.keys())[-500:]
    new_cache = {k: new_cache[k] for k in keys_to_keep}
with open("public/cache.json", "w", encoding="utf-8") as f:
    json.dump(new_cache, f, ensure_ascii=False)

# 2. 按发布时间倒序排列并执行跨媒体去重
all_items.sort(key=lambda x: x["timestamp"], reverse=True)
unique_items = []

for item in all_items:
    matched = False
    for u in unique_items:
        if is_duplicate(item["keywords"], u["keywords"]):
            if item["source"] != u["source"] and all(r["source"] != item["source"] for r in u["related"]):
                u["related"].append(item)
                if not u["has_summary"] and item["has_summary"]:
                    u["zh_summary"] = f"（据{item['source']}摘要）{item['zh_summary']}"
                    u["has_summary"] = True
            matched = True
            break
    if not matched:
        unique_items.append(item)

# 3. 生成最终去重聚合总源 (all.xml)
fg_all = FeedGenerator()
fg_all.title("全球外媒热点 (10家去重版)")
fg_all.link(href="https://github.com")
fg_all.description("BBC/CNBC/FT/经济学人/纽时/WSJ/彭博/路透/美联社/CNN 实时中文去重聚合")

for item in unique_items[:40]:
    fe = fg_all.add_entry()
    fe.id(item["link"])

    all_sources = [item] + item["related"]
    total_sources = len(all_sources)

    title_prefix = f"[{item['source']}等{total_sources}家] " if total_sources > 1 else f"[{item['source']}] "

    sources_list_html = f"<b>报道出处（共 {total_sources} 家，点击查阅原文）：</b><br>" + "<br><br>".join(
        [
            f"• <b>[{s['source']}]</b> <a href='{s['link']}'>{s['zh_title']}</a><br><small>原文：{s['raw_title']}</small>"
            for s in all_sources
        ]
    )

    desc_html = f"{item['zh_summary']}<hr>" if item['zh_summary'] else ""
    fe.title(f"{title_prefix}{item['zh_title']}")
    fe.link(href=item["link"])
    fe.description(f"{desc_html}{sources_list_html}")
    if item["published"]:
        fe.published(item["published"])

fg_all.rss_file("public/all.xml")
print(f"已生成聚合去重源: public/all.xml (原 {len(all_items)} 条 -> 去重后 {len(unique_items)} 条)")
