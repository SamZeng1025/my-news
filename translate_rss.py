import os
import re
import time
import requests
import feedparser
from feedgen.feed import FeedGenerator

FEEDS = {
    "bloomberg": ("彭博社", "https://feeds.bloomberg.com/markets/news.rss"),
    "wsj": ("华尔街日报", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    "nyt": ("纽约时报", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    "cnn": ("CNN", "http://rss.cnn.com/rss/edition_world.rss"),
    "reuters": ("路透社", "https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
    "apnews": ("美联社", "https://news.google.com/rss/search?q=site:apnews.com+when:1d&hl=en-US&gl=US&ceid=US:en"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def clean_html(text):
    """清理摘要里的HTML标签，避免翻译错乱"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def google_translate(text):
    """直连谷歌免费翻译底层接口，比第三方库稳定得多"""
    if not text:
        return ""
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text[:1500]  # 限制长度防超限
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

    for entry in parsed.entries[:10]:
        raw_title = entry.get("title", "").strip()
        if not raw_title:
            continue
        if " - " in raw_title and key in ("reuters", "apnews"):
            raw_title = raw_title.rsplit(" - ", 1)[0]

        # 提取并清理摘要内容
        raw_summary = clean_html(entry.get("summary", "") or entry.get("description", ""))

        # 分别翻译标题和摘要
        zh_title = google_translate(raw_title)
        time.sleep(0.3)
        zh_summary = google_translate(raw_summary) if raw_summary else "（该媒体原源仅提供标题，点击原文链接查看详情）"
        time.sleep(0.3)

        fe = fg.add_entry()
        fe.id(entry.get("link", raw_title))
        fe.title(zh_title)
        fe.link(href=entry.get("link", url))
        # 同时保留中文摘要和英文原题，方便对照
        fe.description(f"{zh_summary}<br><br><small>原文标题：{raw_title}</small>")
        if entry.get("published"):
            fe.published(entry.published)

    fg.rss_file(f"public/{key}.xml")
    print(f"已生成: public/{key}.xml")
