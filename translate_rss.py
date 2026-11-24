import os
import time
import requests
import feedparser
from feedgen.feed import FeedGenerator
from deep_translator import GoogleTranslator

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

os.makedirs("public", exist_ok=True)
translator = GoogleTranslator(source='en', target='zh-CN')

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

        try:
            zh_title = translator.translate(raw_title)
            time.sleep(0.5)
        except Exception:
            zh_title = raw_title

        fe = fg.add_entry()
        fe.title(zh_title)
        fe.link(href=entry.get("link", url))
        if entry.get("published"):
            fe.published(entry.published)

    fg.rss_file(f"public/{key}.xml")
    print(f"已生成: public/{key}.xml")
