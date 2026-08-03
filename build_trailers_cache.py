import urllib.request
import json
import re
import urllib.parse
import os
import praw
from dotenv import load_dotenv

load_dotenv()

# Mapa de tráileres verificados para títulos específicos
OVERRIDE_TRAILERS = {
    'LOS CREYENTES': 'svGU1Mq5irI',
    'THE BELIEVERS': 'svGU1Mq5irI',
    'SILO': '0I7Q1WtTf_c',
    'HOUSE': 'BLt3K0phvX0'
}

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

def get_tmdb_details(title):
    tmdb_token = os.getenv('TMDB_TOKEN', 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI4OTI0MDQwNjMzNjUzMDE5ZTc0ZDBiZGQxYmUzNGE2NiIsIm5iZiI6MTc1NDI2MjA1MS45MTI5OTk5LCJzdWIiOiI2ODhmZWEyM2Y3MjdlM2FkZDI2MWYyY2MiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.rcmhOYeo9EXahCYsFcPqDwX-A0DONDsZiS947b0Db4A')
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {tmdb_token}"
    }
    
    clean = re.sub(r'\s*\(\d{4}\)', '', title).strip()
    q = urllib.parse.quote(clean)
    
    url = f"https://api.themoviedb.org/3/search/multi?query={q}&language=es-MX"
    try:
        req = urllib.request.Request(url, headers=headers)
        res = json.loads(urllib.request.urlopen(req, timeout=4).read().decode())
        results = [r for r in res.get('results', []) if r.get('media_type') in ['movie', 'tv']]
        if results:
            results.sort(key=lambda x: x.get('popularity', 0), reverse=True)
            best = results[0]
            media_type = best.get('media_type')
            item_id = best.get('id')
            
            det_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?language=es-MX"
            det_req = urllib.request.Request(det_url, headers=headers)
            det = json.loads(urllib.request.urlopen(det_req, timeout=4).read().decode())
            
            # Si no hay sinopsis en es-MX, probar con es-ES o en-US
            overview = det.get('overview') or ''
            if not overview:
                try:
                    det_es_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?language=es-ES"
                    det_es_res = json.loads(urllib.request.urlopen(urllib.request.Request(det_es_url, headers=headers), timeout=3).read().decode())
                    overview = det_es_res.get('overview') or ''
                except Exception:
                    pass
            if not overview:
                try:
                    det_en_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?language=en-US"
                    det_en_res = json.loads(urllib.request.urlopen(urllib.request.Request(det_en_url, headers=headers), timeout=3).read().decode())
                    overview = det_en_res.get('overview') or ''
                except Exception:
                    pass

            type_label = "PELÍCULA" if media_type == "movie" else "SERIE"
            date_str = det.get('release_date') or det.get('first_air_date') or ''
            year = date_str[:4] if date_str else ''
            
            extra_info = ''
            if media_type == 'movie':
                runtime = det.get('runtime', 0)
                if runtime:
                    hours = runtime // 60
                    mins = runtime % 60
                    extra_info = f"{hours}h {mins}m" if hours else f"{mins}m"
            else:
                seasons = det.get('number_of_seasons', 0)
                if seasons:
                    extra_info = f"{seasons} Temporada{'s' if seasons > 1 else ''}"
            
            poster = f"https://image.tmdb.org/t/p/w500{det.get('poster_path')}" if det.get('poster_path') else ''
            backdrop = f"https://image.tmdb.org/t/p/w500{det.get('backdrop_path')}" if det.get('backdrop_path') else poster
            if not poster and backdrop:
                poster = backdrop

            yt_id = None
            try:
                v_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}/videos?language=es-MX"
                v_req = urllib.request.Request(v_url, headers=headers)
                v_res = json.loads(urllib.request.urlopen(v_req, timeout=3).read().decode())
                v_results = v_res.get('results', [])
                if not v_results:
                    v_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}/videos?language=es-ES"
                    v_req = urllib.request.Request(v_url, headers=headers)
                    v_res = json.loads(urllib.request.urlopen(v_req, timeout=3).read().decode())
                    v_results = v_res.get('results', [])
                for v in v_results:
                    if v.get('site') == 'YouTube' and v.get('key'):
                        yt_id = v.get('key')
                        break
            except Exception:
                pass
            
            return {
                'title': det.get('name') or det.get('title') or title,
                'media_type': media_type,
                'media_type_label': type_label,
                'year': year,
                'extra_info': extra_info,
                'poster_url': poster,
                'backdrop_url': backdrop,
                'overview': overview,
                'tmdb_yt_id': yt_id
            }
    except Exception as e:
        print(f"Error TMDB '{title}': {e}")
        
    return {
        'title': title,
        'media_type': 'movie',
        'media_type_label': 'PELÍCULA',
        'year': '',
        'extra_info': '',
        'poster_url': '',
        'backdrop_url': '',
        'overview': '',
        'tmdb_yt_id': None
    }

def get_trailer_id(title, media_type='movie'):
    clean_upper = title.upper().strip()
    if clean_upper in OVERRIDE_TRAILERS:
        return OVERRIDE_TRAILERS[clean_upper]

    type_str = "serie" if media_type == 'tv' else "pelicula"
    
    # 1. JustWatch AR
    slug = slugify_title(title)
    for media_path in [type_str, 'pelicula', 'serie']:
        jw_url = f'https://www.justwatch.com/ar/{media_path}/{slug}'
        try:
            req = urllib.request.Request(jw_url, headers={'User-Agent': 'Mozilla/5.0'})
            html = urllib.request.urlopen(req, timeout=4).read().decode('utf-8', errors='ignore')
            matches = re.findall(r'youtube\.com/watch\?v=([\w\-]+)|youtu\.be/([\w\-]+)', html)
            for m in matches:
                key = m[0] or m[1]
                if key and len(key) == 11:
                    return key
        except Exception:
            pass

    # 2. Búsqueda en YouTube especificando Español Latino
    try:
        q = urllib.parse.quote(f'{title} {type_str} trailer oficial espanol latino')
        yt_url = f'https://www.youtube.com/results?search_query={q}'
        req = urllib.request.Request(yt_url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=4).read().decode('utf-8', errors='ignore')
        pattern = r'"videoId":"([\w\-]{11})"'
        ids = re.findall(pattern, html)
        if ids:
            return ids[0]
    except Exception:
        pass

    return None

def fetch_reddit_posts_praw():
    try:
        client_id = os.getenv('REDDIT_CLIENT_ID')
        client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        username = os.getenv('REDDIT_USERNAME')
        password = os.getenv('REDDIT_PASSWORD', '').strip("'")

        if not (client_id and client_secret and username and password):
            return []

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent='python:fondos-projectivy:v1.0 (by /u/' + username + ')'
        )

        sub = reddit.subreddit('IMDB_esp')
        posts = list(sub.new(limit=40))
        items = []
        for p in posts:
            yt_id = extract_yt_id(p.selftext) or extract_yt_id(p.url)
            if not yt_id and hasattr(p, 'comments'):
                p.comments.replace_more(limit=0)
                for comment in p.comments:
                    c_id = extract_yt_id(comment.body)
                    if c_id:
                        yt_id = c_id
                        break
            items.append({
                'title': p.title.strip(),
                'yt_id': yt_id,
                'content': p.selftext or p.url,
                'description': p.selftext or ''
            })
        return items
    except Exception as e:
        print(f"PRAW fetch error: {e}")
        return []

def fetch_provider_top10(provider_name, provider_id):
    tmdb_token = os.getenv('TMDB_TOKEN')
    headers = {"accept": "application/json", "Authorization": f"Bearer {tmdb_token}"}
    items = []
    
    url = f"https://api.themoviedb.org/3/discover/movie?language=es-MX&sort_by=popularity.desc&with_watch_providers={provider_id}&watch_region=MX"
    try:
        req = urllib.request.Request(url, headers=headers)
        res = json.loads(urllib.request.urlopen(req, timeout=4).read().decode())
        results = res.get('results', [])[:10]
        for r in results:
            t = r.get('title')
            if t:
                items.append(t)
    except Exception as e:
        print(f"Error cargando top {provider_name}: {e}")
    return items

def process_item_list(raw_items, default_category=""):
    trailers = []
    seen = set()
    limit = 25 if "Recomendaciones" in default_category else 10
    
    for item in raw_items:
        if len(trailers) >= limit:
            break
            
        title = item.get('title') if isinstance(item, dict) else str(item)
        clean_norm = re.sub(r'[^a-zA-Z0-9]', '', title.lower())
        if clean_norm in seen:
            continue
        seen.add(clean_norm)

        meta = get_tmdb_details(title)
        display_title = meta.get('title') or title
        
        yt_id = OVERRIDE_TRAILERS.get(display_title.upper().strip()) or OVERRIDE_TRAILERS.get(title.upper().strip())
        if not yt_id and isinstance(item, dict):
            yt_id = item.get('yt_id')
        if not yt_id:
            yt_id = meta.get('tmdb_yt_id') or get_trailer_id(display_title, meta['media_type'])
            
        if display_title and yt_id:
            poster_img = meta.get('poster_url', '')
            backdrop_img = meta.get('backdrop_url', '')
            if not poster_img and isinstance(item, dict):
                m_img = re.search(r'https://preview\.redd\.it/[^\s"]+\.(?:jpg|png)', item.get('content', ''))
                if m_img:
                    poster_img = m_img.group(0)

            subtitle_parts = [meta['media_type_label']]
            if meta['year']:
                subtitle_parts.append(meta['year'])
            if meta['extra_info']:
                subtitle_parts.append(meta['extra_info'])
            meta_subtitle = ' • '.join(subtitle_parts)

            overview_txt = meta.get('overview', '')

            trailers.append({
                'title': display_title,
                'subtitle': meta_subtitle,
                'media_type': meta['media_type_label'],
                'year': meta['year'],
                'extra_info': meta['extra_info'],
                'poster_url': poster_img,
                'backdrop_url': backdrop_img or poster_img,
                'overview': overview_txt,
                'youtube_id': yt_id,
                'trailer_url': f'https://www.youtube.com/watch?v={yt_id}'
            })
            print(f"[{default_category}] {display_title} | {meta_subtitle} | YT: {yt_id}")

    return trailers

def build_cache():
    print("--- 1. Cargando Recomendaciones para vos (Reddit) ---")
    reddit_raw = fetch_reddit_posts_praw()
    rec_items = process_item_list(reddit_raw, "Recomendaciones para vos")
    
    providers = [
        ("Top 10 Netflix", 8),
        ("Top 10 Disney+", 337),
        ("Top 10 Prime Video", 119),
        ("Top 10 Apple TV+", 350)
    ]
    
    rows = [
        {
            "category": "Recomendaciones para vos",
            "items": rec_items
        }
    ]

    for p_name, p_id in providers:
        print(f"\n--- Cargando {p_name} ---")
        p_raw = fetch_provider_top10(p_name, p_id)
        p_items = process_item_list(p_raw, p_name)
        rows.append({
            "category": p_name,
            "items": p_items
        })

    full_cache = {
        "rows": rows,
        "flat_list": rec_items
    }

    with open('trailers_cache.json', 'w', encoding='utf-8') as f:
        json.dump(full_cache, f, ensure_ascii=False, indent=2)

    print("\n[OK] Guardado trailers_cache.json con posters verticales y trailers de Youtube corregidos.")

if __name__ == '__main__':
    build_cache()
