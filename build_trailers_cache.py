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

def get_tmdb_metadata(title):
    tmdb_token = os.getenv('TMDB_TOKEN', 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI4OTI0MDQwNjMzNjUzMDE5ZTc0ZDBiZGQxYmUzNGE2NiIsIm5iZiI6MTc1NDI2MjA1MS45MTI5OTk5LCJzdWIiOiI2ODhmZWEyM2Y3MjdlM2FkZDI2MWYyY2MiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.rcmhOYeo9EXahCYsFcPqDwX-A0DONDsZiS947b0Db4A')
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {tmdb_token}"
    }
    
    clean = re.sub(r'\s*\(\d{4}\)', '', title).strip()
    
    for media_type in ['movie', 'tv']:
        q = urllib.parse.quote(clean)
        url = f"https://api.themoviedb.org/3/search/{media_type}?query={q}&language=es-ES"
        try:
            req = urllib.request.Request(url, headers=headers)
            res = json.loads(urllib.request.urlopen(req, timeout=4).read().decode())
            results = res.get('results', [])
            if results:
                item = results[0]
                item_id = item.get('id')
                details_url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?language=es-ES"
                det_req = urllib.request.Request(details_url, headers=headers)
                det = json.loads(urllib.request.urlopen(det_req, timeout=4).read().decode())
                
                type_label = "PELÍCULA" if media_type == "movie" else "SERIE"
                
                date_str = item.get('release_date') or item.get('first_air_date') or ''
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
                
                backdrop = f"https://image.tmdb.org/t/p/w500{item.get('backdrop_path')}" if item.get('backdrop_path') else (f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get('poster_path') else '')
                
                overview = det.get('overview') or item.get('overview') or ''
                
                return {
                    'media_type_label': type_label,
                    'year': year,
                    'extra_info': extra_info,
                    'backdrop_url': backdrop,
                    'overview': overview
                }
        except Exception:
            pass
            
    return {
        'media_type_label': 'PELÍCULA',
        'year': '',
        'extra_info': '',
        'backdrop_url': '',
        'overview': ''
    }

def get_trailer_id(title):
    slug = slugify_title(title)
    for media_path in ['pelicula', 'serie']:
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

    try:
        q = urllib.parse.quote(f'{title} trailer oficial espanol')
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
    seen = set()
    for item in items:
        if len(trailers) >= 20:
            break
        title = item['title'].strip()
        clean_norm = re.sub(r'[^a-zA-Z0-9]', '', title.lower())
        if clean_norm in seen:
            continue
        seen.add(clean_norm)

        yt_id = extract_yt_id(item.get('content', '')) or extract_yt_id(item.get('description', ''))
        if not yt_id:
            yt_id = get_trailer_id(title)
            
        if title and yt_id:
            meta = get_tmdb_metadata(title)
            media_img = meta.get('backdrop_url', '')
            if not media_img:
                m_img = re.search(r'https://preview\.redd\.it/[^\s"]+\.(?:jpg|png)', item.get('content', ''))
                if m_img:
                    media_img = m_img.group(0)

            subtitle_parts = [meta['media_type_label']]
            if meta['year']:
                subtitle_parts.append(meta['year'])
            if meta['extra_info']:
                subtitle_parts.append(meta['extra_info'])
            meta_subtitle = ' • '.join(subtitle_parts)

            overview_txt = meta.get('overview', '')
            if not overview_txt:
                # Limpiar texto del post de reddit si no hay sinopsis TMDB
                raw_desc = re.sub(r'<[^>]+>', '', item.get('description', ''))
                raw_desc = re.sub(r'https?://\S+', '', raw_desc).strip()
                if raw_desc and len(raw_desc) > 15:
                    overview_txt = raw_desc[:250] + '...'

            trailers.append({
                'title': title,
                'subtitle': meta_subtitle,
                'media_type': meta['media_type_label'],
                'year': meta['year'],
                'extra_info': meta['extra_info'],
                'backdrop_url': media_img,
                'overview': overview_txt,
                'youtube_id': yt_id,
                'trailer_url': f'https://www.youtube.com/watch?v={yt_id}'
            })
            print(f"[OK Overview] {title} | {meta_subtitle}")

    with open('trailers_cache.json', 'w', encoding='utf-8') as f:
        json.dump(trailers, f, ensure_ascii=False, indent=2)

    print(f"\nGuardado trailers_cache.json con {len(trailers)} tráileres y sinopsis.")

if __name__ == '__main__':
    build_cache()
