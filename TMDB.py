import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os
import textwrap
from datetime import datetime
import praw
from dotenv import load_dotenv

# Intentar importar traductor, si falla lo desactivamos
try:
    from googletrans import Translator
    translator = Translator()
except ImportError:
    translator = None

# Cargar variables de entorno desde .env
load_dotenv()

# Base URL de la API de TMDB
tmdb_url = "https://api.themoviedb.org/3/"
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_TOKEN')}"
}

# Configuración
date_str = datetime.now().strftime("%Y%m%d")
numberofmovies = 2
numberoftvshows = 2
current_year = datetime.now().year
background_dir = "tmdbbackgrounds"

# Exclusiones
genre_map = {}
excluded_genres = {"Animación", "Ciencia ficción", "Terror", "Sci-Fi & Fantasy"}
excluded_languages = {"zh", "ko"}  # idioma original a excluir: chino y coreano
excluded_movies = set()    # IDs de películas a excluir
excluded_tv = set()        # IDs de series a excluir

# Normalizar título para filename y Reddit title
def normalize_title(title):
    return " ".join(title.replace("_", " ").replace(date_str, "").split()).strip()

# Crear directorio de fondos
os.makedirs(background_dir, exist_ok=True)

# Cargar géneros en español
def load_genres():
    global genre_map
    genres = []
    for mtype in ['movie', 'tv']:
        r = requests.get(f"{tmdb_url}genre/{mtype}/list?language=es-ES", headers=headers)
        if r.status_code == 200:
            genres.extend(r.json().get('genres', []))
    genre_map = {g['id']: g['name'] for g in genres}
    # Ajuste de traducción de Suspense
    for gid, name in list(genre_map.items()):
        if name == 'Suspense':
            genre_map[gid] = 'Suspenso'

from PIL import Image as PILImage

def resize_image(img, height):
    ratio = height / img.height
    return img.resize((int(img.width * ratio), height))

def clean_filename(name):
    return ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)

def draw_multiline_text(draw, pos, text, font, fill, spacing, shadow_color=None, shadow_offset=2):
    if shadow_color:
        draw.multiline_text((pos[0]+shadow_offset, pos[1]+shadow_offset), text, font=font, fill=shadow_color, spacing=spacing)
    draw.multiline_text(pos, text, font=font, fill=fill, spacing=spacing)

def format_duration(minutes):
    if not isinstance(minutes, int):
        return ''
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"

def get_logo_path(mtype, mid):
    r = requests.get(f"{tmdb_url}{mtype}/{mid}/images", headers=headers)
    if r.status_code != 200:
        return None
    logos = r.json().get('logos', [])
    es = [l for l in logos if l.get('iso_639_1')=='es']
    en = [l for l in logos if l.get('iso_639_1')=='en']
    candidates = es or en
    if not candidates:
        return None
    sorted_by_ratio = sorted(candidates, key=lambda l: l['width']/l['height'], reverse=True)[:2]
    def luminance(path):
        try:
            data = requests.get('https://image.tmdb.org/t/p/original'+path).content
            img = PILImage.open(BytesIO(data)).convert('RGBA').resize((50,50))
            pix = [p for p in img.getdata() if p[3]>0]
            return sum(0.299*r+0.587*g+0.114*b for r,g,b,a in pix)/len(pix)
        except:
            return 0
    if len(sorted_by_ratio) == 1:
        return sorted_by_ratio[0]['file_path']
    best = sorted_by_ratio[0] if luminance(sorted_by_ratio[0]['file_path']) >= luminance(sorted_by_ratio[1]['file_path']) else sorted_by_ratio[1]
    return best['file_path']

# Procesar y componer imagen
def process_image(image_url, title, overview, is_movie, genre_ids, year, rating, duration=None, seasons=None, media_type=None, media_id=None):
    # Evitar regenerar si ya existe
    filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
    if os.path.exists(filename):
        print(f"Imagen ya existe: {filename}")
        return False
    # Descripción: intentar español o traducir inglés
    if not overview.strip():
        det = requests.get(f"{tmdb_url}{media_type}/{media_id}?language=es-ES", headers=headers)
        if det.status_code == 200:
            overview = det.json().get('overview','') or overview
    if not overview.strip():
        det = requests.get(f"{tmdb_url}{media_type}/{media_id}?language=en-US", headers=headers)
        if det.status_code == 200:
            overview_en = det.json().get('overview','')
            if overview_en and translator:
                overview = translator.translate(overview_en, dest='es').text
            else:
                overview = overview_en
    if not overview.strip():
        print(f"{title} ignorado por falta de descripción")
        return False
    # Filtrar géneros e IDs
    if any(genre_map.get(g,'') in excluded_genres for g in genre_ids):
        print(f"{title} ignorado por género excluido")
        return False
    if media_type=='movie' and media_id in excluded_movies:
        print(f"{title} ignorado (película excluida)")
        return False
    if media_type=='tv' and media_id in excluded_tv:
        print(f"{title} ignorado (serie excluida)")
        return False
    # Descargar imagen
    r = requests.get(image_url, timeout=10)
    if r.status_code != 200:
        print(f"Error al descargar imagen de {title}")
        return False
    img = Image.open(BytesIO(r.content))
    # Redimensionar y componer fondos
    img = resize_image(img, 1500)
    bg = Image.open('bckg.png')
    ov = Image.open('overlay.png')
    bg.paste(img, (1175,0))
    bg.paste(ov, (1175,0), ov)
    draw = ImageDraw.Draw(bg)
    font_t = ImageFont.truetype('Roboto-Light.ttf',190)
    font_i = ImageFont.truetype('Roboto-Light.ttf',60)
    font_o = ImageFont.truetype('Roboto-Light.ttf',78)
    # Texto overview
    lines = textwrap.wrap(overview,70)
    if len(lines)>7:
        lines = lines[:7]
        lines[-1] += '...'
    draw_multiline_text(draw,(210,860),'\n'.join(lines),font_o,(150,150,150),16,'black',2)
    # Texto info
    info_extra = format_duration(duration) if is_movie else f"{seasons} Temporada{'s' if seasons>1 else ''}"
    genre_names = [genre_map.get(g,'') for g in genre_ids]
    info = f"{', '.join(genre_names)}  •  {year}  •  {info_extra}  •  TMDB: {rating}"
    draw.text((212,722), info, (150,150,150), font_i)
    # Logo TMDB
    logo_path = get_logo_path(media_type, media_id)
    if logo_path:
        try:
            data = requests.get('https://image.tmdb.org/t/p/original'+logo_path).content
            logo_img = Image.open(BytesIO(data)).convert('RGBA')
            w,h = logo_img.size
            max_h = 720-40-150
            max_w = 1600
            ratio = min(max_h/h, max_w/w)
            logo_img = logo_img.resize((int(w*ratio),int(h*ratio)), Image.Resampling.LANCZOS)
            x = 210+10 + (max_w-logo_img.width)//2
            y = 720-40-20-logo_img.height
            bg.paste(logo_img, (x,y), logo_img)
        except:
            draw.text((202,418), title, fill='white', font=font_t, stroke_width=2, stroke_fill='black')
    else:
        draw.text((202,418), title, fill='white', font=font_t, stroke_width=2, stroke_fill='black')
    bg.convert('RGB').save(filename)
    print(f"Image saved: {filename}")
    return True

# Función paginada para trending

def get_trending_expanded(media_type, max_results=60):
    results = []
    page = 1
    while len(results) < max_results:
        r = requests.get(f"{tmdb_url}trending/{media_type}/week?language=es-ES&page={page}", headers=headers)
        if r.status_code != 200:
            break
        batch = r.json().get('results', [])
        if not batch:
            break
        results.extend(batch)
        page += 1
    return results

# Detalles de movie/tv
def get_movie_details(m_id):
    return requests.get(f"{tmdb_url}movie/{m_id}?language=es-ES", headers=headers).json()

def get_tv_details(t_id):
    return requests.get(f"{tmdb_url}tv/{t_id}?language=es-ES", headers=headers).json()

# Chequear duplicados en Reddit
def was_already_posted(subreddit, title, limit=1000):
    for sub in subreddit.new(limit=limit):
        if sub.title.strip().lower() == title.strip().lower():
            return True
    return False

# Main completo para trending

def main():
    load_genres()
    reddit = praw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent="tmdb uploader by u/" + os.getenv('REDDIT_USERNAME'),
        username=os.getenv('REDDIT_USERNAME'),
        password=os.getenv('REDDIT_PASSWORD')
    )
    subreddit = reddit.subreddit(os.getenv('REDDIT_SUBREDDIT','IMDB_esp'))

    # Películas trending
    processed = set()
    count_m = 0
    for m in get_trending_expanded('movie', max_results=60):
        if count_m >= numberofmovies:
            break
        mid = m.get('id')
        if mid in processed or mid in excluded_movies:
            continue
        processed.add(mid)
        if m.get('original_language') in excluded_languages:
            continue
        year = m.get('release_date','')[:4]
        if year != str(current_year):
            continue
        details = get_movie_details(mid)
        ok = process_image(
            f"https://image.tmdb.org/t/p/original{m.get('backdrop_path')}",
            m.get('title',''), m.get('overview',''), True,
            m.get('genre_ids',[]), year, round(m.get('vote_average',0),1),
            duration=details.get('runtime'), media_type='movie', media_id=mid
        )
        if ok:
            count_m += 1
            title_norm = normalize_title(m.get('title',''))
            if not was_already_posted(subreddit, title_norm):
                subreddit.submit_image(title_norm, os.path.join(background_dir, clean_filename(m.get('title',''))+'.jpg'))
                print(f"Subido: {title_norm}")
    if count_m < numberofmovies:
        print(f"Solo se generaron {count_m} de {numberofmovies} películas solicitadas")

    # Series trending
    processed_tv = set()
    count_t = 0
    for tv in get_trending_expanded('tv', max_results=60):
        if count_t >= numberoftvshows:
            break
        tid = tv.get('id')
        if tid in processed_tv or tid in excluded_tv:
            continue
        processed_tv.add(tid)
        if tv.get('original_language') in excluded_languages:
            continue
        year = tv.get('first_air_date','')[:4]
        if year != str(current_year):
            continue
        details = get_tv_details(tid)
        ok = process_image(
            f"https://image.tmdb.org/t/p/original{tv.get('backdrop_path')}",
            tv.get('name',''), tv.get('overview',''), False,
            tv.get('genre_ids',[]), year, round(tv.get('vote_average',0),1),
            seasons=details.get('number_of_seasons'), media_type='tv', media_id=tid
        )
        if ok:
            count_t += 1
            title_norm = normalize_title(tv.get('name',''))
            if not was_already_posted(subreddit, title_norm):
                subreddit.submit_image(title_norm, os.path.join(background_dir, clean_filename(tv.get('name',''))+'.jpg'))
                print(f"Subido: {title_norm}")
    if count_t < numberoftvshows:
        print(f"Solo se generaron {count_t} de {numberoftvshows} series solicitadas")

if __name__ == '__main__':
    main()
