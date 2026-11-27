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
    "npr": ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    "guardian": ("卫报", "https://www.theguardian.com/world/rss"),
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

CACHE_TTL = 48 * 3600  # 缓存有效期：48小时
CACHE_FILE = "public/cache.json"
ENGINE_BLOCKED = {"google_gtx": False, "google_c5": False, "edge": False}
EDGE_TOKEN = None

def get_edge_token():
    global EDGE_TOKEN
    if EDGE_TOKEN:
        return EDGE_TOKEN
    try:
        r = requests.get("https://edge.microsoft.com/translate/auth", headers=HEADERS, timeout=10)
        if r.status_code == 200 and r.text:
            EDGE_TOKEN = r.text.strip()
            return EDGE_TOKEN
        ENGINE_BLOCKED["edge"] = True
    except Exception:
        ENGINE_BLOCKED["edge"] = True
    return None

def translate_text(text):
    """四重免费引擎自动兜底：Google gtx -> Google clients5 -> Microsoft Edge -> MyMemory"""
    if not text:
        return ""
    text = text[:1500]

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
        except Exception:
            ENGINE_BLOCKED["google_gtx"] = True

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
        except Exception:
            ENGINE_BLOCKED["google_c5"] = True

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
            except Exception:
                ENGINE_BLOCKED["edge"] = True

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
    except Exception:
        pass

    return text

def translate_pair(title, summary):
    if not summary:
        return translate_text(title), ""
    combined = translate_text(f"{title}\n###\n{summary}")
    if "###" in combined:
        parts = combined.split("###", 1)
        return parts[0].strip(), parts[1].strip()
    return translate_text(title), ""

def load_state():
    """优先读本地缓存(VPS)，其次读GitHub Pages云端缓存，并自动兼容旧版格式"""
    raw = None
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            pass

    if raw is None:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo:
            owner, name = repo.split("/", 1)
            try:
                r = requests.get(f"https://{owner}.github.io/{name}/cache.json", timeout=10)
                if r.status_code == 200:
                    raw = r.json()
            except Exception:
                pass

    now = time.time()
    state = {"translations": {}, "events": []}
    if not isinstance(raw, dict):
        return state

    # 兼容旧版纯字典格式
    if "translations" not in raw and "events" not in raw:
        for k, v in raw.items():
            if isinstance(v, dict) and "zh_title" in v:
                state["translations"][k] = {
                    "zh_title": v["zh_title"],
                    "zh_summary": v.get("zh_summary", ""),
                    "ts": now
                }
        return state

    # 清理超过 48 小时的过期译文与事件
    for k, v in raw.get("translations", {}).items():
        if now - v.get("ts", 0) <= CACHE_TTL:
            state["translations"][k] = v
    for ev in raw.get("events", []):
        if now - ev.get("first_seen", 0) <= CACHE_TTL:
            state["events"].append(ev)

    print(f"加载48h缓存成功: 译文 {len(state['translations'])} 条, 活跃事件 {len(state['events'])} 个")
    return state

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
    return list({w for w in words if len(w) > 2 and w not in STOP_WORDS})

def is_duplicate(kw1, kw2):
    s1, s2 = set(kw1), set(kw2)
    if not s1 or not s2:
        return False
    common = s1 & s2
    if len(common) >= 3:
        return True
    if len(common) >= 2 and (len(common) / min(len(s1), len(s2))) >= 0.5:
        return True
    return False

def get_timestamp(pub_str):
    if not pub_str:
        return time.time()
    try:
        return parsedate_to_datetime(pub_str).timestamp()
    except Exception:
        return time.time()

os.makedirs("public", exist_ok=True)
now = time.time()
state = load_state()
translations = state["translations"]
events = state["events"]
new_fetched_items = []

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
        ts = get_timestamp(published)

        cached_t = translations.get(link)
        if cached_t and re.search(r'[\u4e00-\u9fff]', cached_t.get("zh_title", "")):
            zh_title = cached_t["zh_title"]
            zh_summary = cached_t.get("zh_summary", "")
        else:
            zh_title, zh_summary = translate_pair(raw_title, raw_summary if valid_summary else "")
            if re.search(r'[\u4e00-\u9fff]', zh_title):
                translations[link] = {"zh_title": zh_title, "zh_summary": zh_summary, "ts": now}

        fe = fg.add_entry()
        fe.id(link)
        fe.title(zh_title)
        fe.link(href=link)
        desc_html = f"{zh_summary}<hr>" if zh_summary else ""
        source_html = f"<b>报道出处：</b><br>• [{cn_name}] <a href='{link}'>{zh_title}</a><br><small>原文：{raw_title}</small>"
        fe.description(f"{desc_html}{source_html}")
        if published:
            fe.published(published)

        new_fetched_items.append({
            "source": cn_name,
            "raw_title": raw_title,
            "zh_title": zh_title,
            "zh_summary": zh_summary,
            "has_summary": bool(zh_summary),
            "link": link,
            "published": published,
            "timestamp": ts,
            "keywords": extract_keywords(raw_title)
        })

    fg.rss_file(f"public/{key}.xml")

# 2. 按发布时间正序将新文章并入 48 小时事件库（锁定首个报道的 event_id 防重复弹出）
new_fetched_items.sort(key=lambda x: x["timestamp"])

for item in new_fetched_items:
    matched_event = None
    for ev in events:
        # 网址已存在或关键词命中，均归入同一历史事件
        if any(s["link"] == item["link"] for s in ev["sources"]) or is_duplicate(item["keywords"], ev["keywords"]):
            matched_event = ev
            break

    if matched_event:
        # 仅当该媒体尚未记录在此事件中时，追加到出处列表
        if all(s["source"] != item["source"] for s in matched_event["sources"]):
            matched_event["sources"].append({
                "source": item["source"],
                "raw_title": item["raw_title"],
                "zh_title": item["zh_title"],
                "link": item["link"]
            })
            if not matched_event["has_summary"] and item["has_summary"]:
                matched_event["zh_summary"] = f"（据{item['source']}摘要）{item['zh_summary']}"
                matched_event["has_summary"] = True
    else:
        events.append({
            "event_id": item["link"],  # 永久锁定此事件的唯一ID
            "first_seen": now,
            "published": item["published"],
            "timestamp": item["timestamp"],
            "keywords": item["keywords"],
            "zh_summary": item["zh_summary"],
            "has_summary": item["has_summary"],
            "sources": [{
                "source": item["source"],
                "raw_title": item["raw_title"],
                "zh_title": item["zh_title"],
                "link": item["link"]
            }]
        })

# 3. 保存更新后的 48 小时状态缓存
with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump({"translations": translations, "events": events}, f, ensure_ascii=False)

# 4. 生成最终去重聚合总源 (all.xml)
events.sort(key=lambda x: x["timestamp"], reverse=True)
fg_all = FeedGenerator()
fg_all.title("全球外媒热点 (10家去重版)")
fg_all.link(href="https://github.com")
fg_all.description("BBC/CNBC/FT/经济学人/纽时/WSJ/彭博/路透/美联社/CNN 48小时跨批次去重聚合")

for ev in events[:40]:
    fe = fg_all.add_entry()
    fe.id(ev["event_id"])  # 使用锁定的 event_id，NetNewsWire 原地更新不重复弹窗

    primary = ev["sources"][0]
    total_sources = len(ev["sources"])
    title_prefix = f"[{primary['source']}等{total_sources}家] " if total_sources > 1 else f"[{primary['source']}] "

    sources_list_html = f"<b>报道出处（共 {total_sources} 家，点击查阅原文）：</b><br>" + "<br><br>".join(
        [
            f"• <b>[{s['source']}]</b> <a href='{s['link']}'>{s['zh_title']}</a><br><small>原文：{s['raw_title']}</small>"
            for s in ev["sources"]
        ]
    )

    desc_html = f"{ev['zh_summary']}<hr>" if ev["zh_summary"] else ""
    fe.title(f"{title_prefix}{primary['zh_title']}")
    fe.link(href=primary["link"])
    fe.description(f"{desc_html}{sources_list_html}")
    if ev["published"]:
        fe.published(ev["published"])

fg_all.rss_file("public/all.xml")
print(f"已生成聚合去重源: public/all.xml (48h活跃事件共 {len(events)} 个)")
