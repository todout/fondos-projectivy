import urllib.request
import json
import re
import urllib.parse
import os

def slugify_title(title):
    if not title:
        return ''
    t = title.lower()
    t = re.sub(r'[áàäâ]', 'a', t)
    t = re.sub(r'[éèëê]', 'e', t)
    t = re.sub(r'[íìïî]', 'i', t)
    t = re.sub(r'[óòöô]', 'o', t)
    t = re.sub(r'[úùüû]', 'u', t)
    t = re.sub(r'[ñ]', 'n', t)
    t = re.sub(r'[^a-z0-9\s\-]', '', t)
    return re.sub(r'[\s\-]+', '-', t).strip('-')

def extract_yt_id(url):
    if not url:
        return None
    m = re.search(r'(?:youtu\.be/|v/|u/\w/|embed/|watch\?v=|\&v=)([\w\-]{11})', url)
    return m.group(1) if m else None

def get_trailer_id(title):
    # 1. JustWatch AR
    slug = slugify_title(title)
    for media_path in ['pelicula', 'serie']:
        jw_url = f'https://www.justwatch.com/ar/{media_path}/{slug}'
        try:
            req = urllib.request.Request(jw_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8', errors='ignore')
            matches = re.findall(r'youtube\.com/watch\?v=([\w\-]+)|youtu\.be/([\w\-]+)', html)
            for m in matches:
                key = m[0] or m[1]
                if key and len(key) == 11:
                    return key
        except Exception:
            pass

    # 2. YouTube Search API fallback scrape
    try:
        q = urllib.parse.quote(f'{title} trailer oficial espanol')
        yt_url = f'https://www.youtube.com/results?search_query={q}'
        req = urllib.request.Request(yt_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8', errors='ignore')
        pattern = r'"videoId":"([\w\-]{11})"'
        ids = re.findall(pattern, html)
        if ids:
            return ids[0]
    except Exception:
        pass

    return None

def build_cache():
    rss_url = 'https://api.rss2json.com/v1/api.json?rss_url=https://www.reddit.com/r/IMDB_esp/new.rss'
    req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = json.loads(urllib.request.urlopen(req).read().decode())
        items = data.get('items', [])
    except Exception as e:
        print(f"Error cargando RSS: {e}")
        items = []

    trailers = []
    for item in items:
        title = item['title'].strip()
        yt_id = extract_yt_id(item.get('content', '')) or extract_yt_id(item.get('description', ''))
        if not yt_id:
            yt_id = get_trailer_id(title)
        if title and yt_id:
            trailers.append({
                'title': title,
                'youtube_id': yt_id,
                'trailer_url': f'https://www.youtube.com/watch?v={yt_id}'
            })
            print(f"[OK] {title} -> {yt_id}")

    with open('trailers_cache.json', 'w', encoding='utf-8') as f:
        json.dump(trailers, f, ensure_ascii=False, indent=2)

    print(f"\nGuardado trailers_cache.json con {len(trailers)} tráileres exactos en español.")

if __name__ == '__main__':
    build_cache()
