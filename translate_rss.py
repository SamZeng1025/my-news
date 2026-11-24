import os
import re
import time
import requests
import feedparser
from email.utils import parsedate_to_datetime
from feedgen.feed import FeedGenerator

# 10大顶级外媒源（优先采用带完整摘要的官方源）
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
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "as",
    "is", "are", "was", "were", "be", "been", "that", "this", "it", "from",
    "and", "or", "but", "not", "says", "say", "after", "over", "amid", "new",
    "into", "about", "up", "out", "will", "has", "have", "had", "its", "us"
}

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def has_real_summary(title, summary):
    """判断摘要是否为有效正文导语，过滤掉抄标题的复读机摘要"""
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

def google_translate(text):
    if not text:
        return ""
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text[:1500]
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return "".join([item[0] for item in data[0] if item[0]])
    except Exception as e:
        print(f"翻译失败: {e}")
    return text

os.makedirs("public", exist_ok=True)
all_items = []

# 1. 抓取并翻译10家媒体（每家取最新8条，兼顾覆盖面与速度）
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

    for entry in parsed.entries[:8]:
        raw_title = entry.get("title", "").strip()
        if not raw_title:
            continue
        if " - " in raw_title and key in ("reuters", "apnews", "cnn"):
            raw_title = raw_title.rsplit(" - ", 1)[0]

        raw_summary = clean_html(entry.get("summary", "") or entry.get("description", ""))
        valid_summary = has_real_summary(raw_title, raw_summary)

        zh_title = google_translate(raw_title)
        time.sleep(0.25)

        if valid_summary:
            zh_summary = google_translate(raw_summary)
            time.sleep(0.25)
        else:
            zh_summary = ""

        link = entry.get("link", url)
        published = entry.get("published", "")

        # 写入单家媒体独立源
        fe = fg.add_entry()
        fe.id(link)
        fe.title(zh_title)
        fe.link(href=link)
        desc_html = f"{zh_summary}<br><br>" if zh_summary else ""
        fe.description(f"{desc_html}<small>原文标题：{raw_title}</small>")
        if published:
            fe.published(published)

        all_items.append({
            "source": cn_name,
            "raw_title": raw_title,
            "zh_title": zh_title,
            "zh_summary": zh_summary,
            "has_summary": valid_summary,
            "link": link,
            "published": published,
            "timestamp": get_timestamp(published),
            "keywords": extract_keywords(raw_title),
            "related": []
        })

    fg.rss_file(f"public/{key}.xml")
    print(f"已生成: public/{key}.xml")

# 2. 按发布时间倒序排列并执行智能去重
all_items.sort(key=lambda x: x["timestamp"], reverse=True)
unique_items = []

for item in all_items:
    matched = False
    for u in unique_items:
        if is_duplicate(item["keywords"], u["keywords"]):
            if item["source"] != u["source"] and all(r["source"] != item["source"] for r in u["related"]):
                u["related"].append(item)
                # 如果主条目没有摘要，而合并进来的媒体有摘要，自动借用它的摘要
                if not u["has_summary"] and item["has_summary"]:
                    u["zh_summary"] = f"（据{item['source']}摘要）{item['zh_summary']}"
                    u["has_summary"] = True
            matched = True
            break
    if not matched:
        unique_items.append(item)

# 3. 生成最终的去重聚合总源 (all.xml)
fg_all = FeedGenerator()
fg_all.title("全球外媒热点 (10家去重版)")
fg_all.link(href="https://github.com")
fg_all.description("BBC/CNBC/FT/经济学人/纽时/WSJ/彭博/路透/美联社/CNN 实时中文去重聚合")

for item in unique_items[:40]:
    fe = fg_all.add_entry()
    fe.id(item["link"])

    if item["related"]:
        total_sources = len(item["related"]) + 1
        title_prefix = f"[{item['source']}等{total_sources}家] "
        related_html = "<br><br><b>其他媒体同步报道：</b><br>" + "<br>".join(
            [f"• [{r['source']}] <a href='{r['link']}'>{r['zh_title']}</a>" for r in item["related"]]
        )
    else:
        title_prefix = f"[{item['source']}] "
        related_html = ""

    desc_html = f"{item['zh_summary']}<br><br>" if item["zh_summary"] else ""
    fe.title(f"{title_prefix}{item['zh_title']}")
    fe.link(href=item["link"])
    fe.description(f"{desc_html}<small>原文标题：{item['raw_title']}</small>{related_html}")
    if item["published"]:
        fe.published(item["published"])

fg_all.rss_file("public/all.xml")
print(f"已生成聚合去重源: public/all.xml (原 {len(all_items)} 条 -> 去重后 {len(unique_items)} 条)")
