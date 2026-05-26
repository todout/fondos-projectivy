import requests
from PIL import Image, ImageDraw, ImageFont
from PIL import Image as PILImage
import unicodedata
from io import BytesIO
import os
import json
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

# Configuración básica
date_str = datetime.now().strftime("%Y%m%d")
numberofmovies = int(os.getenv("TMDB_NUMBER_OF_MOVIES", "2"))
numberoftvshows = int(os.getenv("TMDB_NUMBER_OF_TV_SHOWS", "2"))
current_year = datetime.now().year
background_dir = "tmdbbackgrounds"

# Configuración de Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Descargar fuentes adicionales si faltan
font_bold_path = 'Roboto-Black.ttf'
if not os.path.exists(font_bold_path):
    try:
        print("Descargando fuente Roboto-Black.ttf...")
        r_f = requests.get('https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Black.ttf', timeout=10)
        if r_f.status_code == 200:
            with open(font_bold_path, 'wb') as f_b:
                f_b.write(r_f.content)
            print("Fuente Roboto-Black.ttf descargada con éxito.")
    except Exception as e:
        print(f"Error descargando Roboto-Black: {e}")

# Cargar Exclusiones Dinámicas
exclude_genres_env = os.getenv('TMDB_EXCLUDE_GENRES', 'Animación, Ciencia ficción, Terror, Sci-Fi & Fantasy')
excluded_genres = {g.strip() for g in exclude_genres_env.split(',') if g.strip()}

exclude_languages_env = os.getenv('TMDB_EXCLUDE_LANGUAGES', 'zh, ko')
excluded_languages = {l.strip().lower() for l in exclude_languages_env.split(',') if l.strip()}

exclude_movies_env = os.getenv('TMDB_EXCLUDE_MOVIES', '')
excluded_movies = {int(mid.strip()) for mid in exclude_movies_env.split(',') if mid.strip().isdigit()}

exclude_tv_env = os.getenv('TMDB_EXCLUDE_TV', '')
excluded_tv = {int(tid.strip()) for tid in exclude_tv_env.split(',') if tid.strip().isdigit()}

genre_map = {}
genre_name_to_id = {}

# Crear directorio de fondos
os.makedirs(background_dir, exist_ok=True)

# Normalizar título para filename y Reddit title
def normalize_title(title):
    return " ".join(title.replace("_", " ").replace(date_str, "").split()).strip()

# Helper centralizado para consultas TMDB
def tmdb_get(endpoint, params=None):
    try:
        r = requests.get(f"{tmdb_url}{endpoint}", headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"TMDB API error {r.status_code} para {endpoint}")
            return None
    except Exception as e:
        print(f"Error de conexión a TMDB API {endpoint}: {e}")
        return None

# Cargar géneros y crear mapeos bidireccionales
def load_genres():
    global genre_map, genre_name_to_id
    genres_es = []
    genres_en = []
    
    # Cargar en español
    data_es = tmdb_get("genre/movie/list", {"language": "es-ES"})
    if data_es:
        genres_es.extend(data_es.get('genres', []))
    data_es_tv = tmdb_get("genre/tv/list", {"language": "es-ES"})
    if data_es_tv:
        genres_es.extend(data_es_tv.get('genres', []))
        
    # Cargar en inglés
    data_en = tmdb_get("genre/movie/list", {"language": "en-US"})
    if data_en:
        genres_en.extend(data_en.get('genres', []))
    data_en_tv = tmdb_get("genre/tv/list", {"language": "en-US"})
    if data_en_tv:
        genres_en.extend(data_en_tv.get('genres', []))
        
    # Mapeo de ID -> Nombre en español
    genre_map = {g['id']: g['name'] for g in genres_es}
    
    # Ajuste de traducción específico
    for gid, name in list(genre_map.items()):
        if name == 'Suspense':
            genre_map[gid] = 'Suspenso'
            
    # Mapeo Nombre -> ID (tanto inglés como español)
    for g in genres_es:
        name = g['name']
        if name == 'Suspense':
            name = 'Suspenso'
        genre_name_to_id[name.lower().strip()] = g['id']
        
    for g in genres_en:
        genre_name_to_id[g['name'].lower().strip()] = g['id']
        
    # Variaciones comunes
    genre_name_to_id['suspense'] = genre_name_to_id.get('suspenso') or 9648

# Cargar gustos del usuario
def load_preferences():
    path = "user_preferences.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando user_preferences.json: {e}")
            
    # Fallback inicial en caso de error
    return {
        "likes": [{"title": t} for t in ["Contratiempo", "El ciudadano ilustre", "Un cuento chino", "El hombre de al lado", "Mi obra maestra", "Sin retorno", "El patrón, radiografía de un crimen", "Crímenes de familia", "El cuento de las comadrejas"]],
        "dislikes": [{"title": t} for t in ["El aura", "Tesis sobre un homicidio", "Plata quemada", "Al final del túnel", "Nieve negra", "Sin hijos"]],
        "neutral": []
    }

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

# Limpiar caracteres incompatibles con fuentes latinas para evitar cuadrados (tofu)
def sanitize_title_font(text):
    cleaned = []
    for c in text:
        o = ord(c)
        # Permitir caracteres de bloques básicos de Europa y América (Latin extended, puntuación común, etc.)
        if 32 <= o <= 500 or c.isspace() or c in ['–', '—', '’', '‘', '“', '”']:
            cleaned.append(c)
    result = "".join(cleaned).strip()
    if not result:
        return "Recomendación"
    return result

# Extraer el color dominante vibrante de la imagen para el título fallback
def extract_accent_color(img):
    try:
        small_img = img.resize((100, 100))
        paletted = small_img.convert('P', palette=PILImage.Palette.ADAPTIVE, colors=16)
        palette = paletted.getpalette()
        color_counts = paletted.getcolors()
        
        candidates = []
        for count, index in color_counts:
            r = palette[index*3]
            g = palette[index*3 + 1]
            b = palette[index*3 + 2]
            
            brightness = 0.299*r + 0.587*g + 0.114*b
            max_val = max(r, g, b)
            min_val = min(r, g, b)
            saturation = (max_val - min_val) / max_val if max_val > 0 else 0
            
            # Buscar colores vivos de brillo medio-alto (que resalten sobre el degradado oscuro)
            if 90 < brightness < 220 and saturation > 0.15:
                candidates.append((count * (1 + saturation), (r, g, b)))
                
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
            
        return (255, 105, 180) # Fallback fucsia agradable si no encuentra
    except Exception as e:
        print(f"Error extrayendo color de acento: {e}")
        return (255, 105, 180)

def get_logo_path(mtype, mid):
    r_json = tmdb_get(f"{mtype}/{mid}/images")
    if not r_json:
        return None
        
    logos = r_json.get('logos', [])
    es = [l for l in logos if l.get('iso_639_1') == 'es']
    en = [l for l in logos if l.get('iso_639_1') == 'en']
    candidates = es or en
    if not candidates:
        return None
        
    sorted_by_ratio = sorted(candidates, key=lambda l: l['width']/l['height'], reverse=True)[:2]
    
    def luminance(path):
        try:
            data = requests.get('https://image.tmdb.org/t/p/original' + path, timeout=10).content
            img = PILImage.open(BytesIO(data)).convert('RGBA').resize((50,50))
            pix = img.load()
            pixels = []
            for y in range(img.height):
                for x in range(img.width):
                    p = pix[x, y]
                    if p[3] > 0:
                        pixels.append(p)
            if not pixels:
                return 0
            return sum(0.299*r+0.587*g+0.114*b for r,g,b,a in pixels)/len(pixels)
        except:
            return 0
            
    if len(sorted_by_ratio) == 1:
        return sorted_by_ratio[0]['file_path']
        
    best = sorted_by_ratio[0] if luminance(sorted_by_ratio[0]['file_path']) >= luminance(sorted_by_ratio[1]['file_path']) else sorted_by_ratio[1]
    return best['file_path']

# Procesar y componer imagen
def process_image(image_url, title, overview, is_movie, genre_ids, year, rating, duration=None, seasons=None, media_type=None, media_id=None, reason=None):
    filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
    if os.path.exists(filename):
        print(f"Imagen ya existe: {filename}")
        return False
        
    # Obtener descripción en español si falta
    if not overview.strip():
        det = tmdb_get(f"{media_type}/{media_id}", {"language": "es-ES"})
        if det:
            overview = det.get('overview', '') or overview
            
    # Intentar traducción de inglés si sigue vacía
    if not overview.strip():
        det = tmdb_get(f"{media_type}/{media_id}", {"language": "en-US"})
        if det:
            overview_en = det.get('overview', '')
            if overview_en and translator:
                try:
                    overview = translator.translate(overview_en, dest='es').text
                except Exception as e:
                    print(f"Error de traducción de Google: {e}")
                    overview = overview_en
            else:
                overview = overview_en
                
    if not overview.strip():
        print(f"{title} ignorado por falta de descripción")
        return False
        
    # Filtrar géneros
    if any(genre_map.get(g,'') in excluded_genres for g in genre_ids):
        print(f"{title} ignorado por género excluido")
        return False
        
    # Descargar imagen
    try:
        r = requests.get(image_url, timeout=15)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
    except Exception as e:
        print(f"Error al descargar imagen de {title}: {e}")
        return False
        
    # Redimensionar y componer fondos
    img = resize_image(img, 1500)
    bg = Image.open('bckg.png')
    ov = Image.open('overlay.png')
    bg.paste(img, (1175,0))
    bg.paste(ov, (1175,0), ov)
    
    draw = ImageDraw.Draw(bg)
    font_t = ImageFont.truetype('Roboto-Light.ttf', 190)
    font_i = ImageFont.truetype('Roboto-Light.ttf', 60)
    
    # Renderizado de la sinopsis (Siempre a 860, con tamaño 78 y espaciado original 16)
    font_o = ImageFont.truetype('Roboto-Light.ttf', 78)
    line_spacing = 16
    overview_pos = (210, 860)
    
    text_to_show = overview.strip()
    if reason:
        text_to_show += f"\n{reason.strip()}"
        
    paragraphs = text_to_show.split('\n')
    wrapped_lines = []
    for p in paragraphs:
        if not p.strip():
            continue
        wrapped_lines.extend(textwrap.wrap(p, 70))
        
    # Limitar a máximo 3 líneas para garantizar que entre perfectamente en el espacio original
    if len(wrapped_lines) > 3:
        wrapped_lines = wrapped_lines[:3]
        wrapped_lines[-1] += '...'
        
    overview_text = '\n'.join(wrapped_lines)
    draw_multiline_text(draw, overview_pos, overview_text, font_o, (150, 150, 150), line_spacing, 'black', 2)
    
    # Texto info (Solo mostrar TMDB rating si es mayor a 0.0)
    info_extra = format_duration(duration) if is_movie else f"{seasons} Temporada{'s' if seasons > 1 else ''}"
    genre_names = [genre_map.get(g, '') for g in genre_ids]
    genre_names = [gn for gn in genre_names if gn]
    
    info_parts = [", ".join(genre_names), year, info_extra]
    if rating and rating > 0.0:
        info_parts.append(f"TMDB: {rating}")
    info_parts = [p for p in info_parts if p.strip()]
    info = "  •  ".join(info_parts)
    
    draw.text((212, 722), info, (150, 150, 150), font_i)
    
    # Logo TMDB / Título Fallback estilizado con Roboto-Black
    logo_path = get_logo_path(media_type, media_id)
    logo_drawn = False
    
    if logo_path:
        try:
            data = requests.get('https://image.tmdb.org/t/p/original'+logo_path, timeout=10).content
            logo_img = Image.open(BytesIO(data)).convert('RGBA')
            w, h = logo_img.size
            max_h = 720-40-150
            max_w = 1600
            ratio = min(max_h/h, max_w/w)
            logo_img = logo_img.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)
            x = 210+10 + (max_w-logo_img.width)//2
            y = 720-40-20-logo_img.height
            bg.paste(logo_img, (x, y), logo_img)
            logo_drawn = True
        except Exception as e:
            print(f"Error cargando logo de {title}, usando texto: {e}")
            
    if not logo_drawn:
        # Sanitizar título para prevenir tofu
        title_clean = sanitize_title_font(title)
        # Extraer color de acento dinámico de la foto
        accent_color = extract_accent_color(img)
        
        try:
            if len(title_clean) > 15:
                # Dos líneas, fuente más compacta
                font_t_bold = ImageFont.truetype('Roboto-Black.ttf', 130)
                title_wrapped = textwrap.wrap(title_clean, width=14)
                if len(title_wrapped) > 2:
                    title_wrapped = title_wrapped[:2]
                    title_wrapped[-1] += '...'
                title_text = '\n'.join(title_wrapped)
                title_pos = (210, 340)
                line_spacing = 10
            else:
                # Una línea, tamaño grande
                font_t_bold = ImageFont.truetype('Roboto-Black.ttf', 170)
                title_text = title_clean
                title_pos = (210, 450)
                line_spacing = 0
                
            # Sombra negra
            shadow_offset = 4
            draw.multiline_text((title_pos[0]+shadow_offset, title_pos[1]+shadow_offset), title_text, fill='black', font=font_t_bold, spacing=line_spacing)
            # Título principal con el color extraído
            draw.multiline_text(title_pos, title_text, fill=accent_color, font=font_t_bold, spacing=line_spacing)
        except Exception as e:
            print(f"Error dibujando título estilizado: {e}")
            draw.text((202, 418), title_clean, fill='white', font=font_t, stroke_width=2, stroke_fill='black')
            
    bg.convert('RGB').save(filename)
    print(f"Image saved: {filename}")
    return True

# Procesar película/serie recomendada a partir de ID
def process_recommended_item(item_id, media_type, custom_overview=None):
    details = tmdb_get(f"{media_type}/{item_id}", {"language": "es-ES"})
    if not details:
        return False
        
    is_movie = (media_type == 'movie')
    title = details.get('title') if is_movie else details.get('name')
    overview = custom_overview if custom_overview else details.get('overview', '')
    genre_ids = [g['id'] for g in details.get('genres', [])]
    date_key = 'release_date' if is_movie else 'first_air_date'
    year = details.get(date_key, '')[:4]
    rating = round(details.get('vote_average', 0), 1)
    backdrop_path = details.get('backdrop_path')
    
    if not backdrop_path:
        print(f"No hay backdrop de fondo disponible para: {title}")
        return False
        
    image_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
    duration = details.get('runtime') if is_movie else None
    seasons = details.get('number_of_seasons') if not is_movie else None
    
    return process_image(
        image_url=image_url,
        title=title,
        overview=overview,
        is_movie=is_movie,
        genre_ids=genre_ids,
        year=year,
        rating=rating,
        duration=duration,
        seasons=seasons,
        media_type=media_type,
        media_id=item_id,
        reason=None
    )

# Obtener lista amplia de candidatos
def get_candidates(media_type, max_results=40):
    trending_results = []
    page = 1
    while len(trending_results) < max_results:
        data = tmdb_get(f"trending/{media_type}/week", {"language": "es-ES", "page": page})
        if not data or not data.get('results'):
            break
        for item in data.get('results', []):
            item['media_type'] = media_type
            trending_results.append(item)
        page += 1
        if page > 3:
            break
            
    classic_results = []
    if media_type == 'movie':
        # Descubrir clásicos populares aclamados (1990-2020)
        params = {
            "language": "es-ES",
            "sort_by": "popularity.desc",
            "vote_average.gte": 7.5,
            "vote_count.gte": 1000,
            "primary_release_date.gte": "1990-01-01",
            "primary_release_date.lte": "2020-12-31",
            "page": 1
        }
        data = tmdb_get("discover/movie", params=params)
        if data and data.get('results'):
            for item in data.get('results'):
                item['media_type'] = 'movie'
                classic_results.append(item)
                
    candidates = []
    seen_ids = set()
    
    # Priorizar tendencias
    for item in trending_results[:max_results]:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            candidates.append(item)
            
    # Añadir clásicos para Gemini
    for item in classic_results:
        if len(candidates) >= max_results + 15:
            break
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            candidates.append(item)
            
    return candidates

# Llamada inteligente a Gemini
def ask_gemini_recommendations(likes, dislikes, neutral, candidates, count_m, count_t):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY no configurado. Usando modo de fallback tradicional.")
        return None
        
    def format_pref_list(arr):
        return "\n".join([f"- {x['title']} (Géneros: {', '.join(x.get('genres', []))})" for x in arr]) if arr else "Ninguno"
        
    likes_str = format_pref_list(likes)
    dislikes_str = format_pref_list(dislikes)
    neutral_str = format_pref_list(neutral)
    
    cand_lines = []
    for c in candidates:
        media_type = c.get('media_type', 'movie')
        title = c.get('title') or c.get('name')
        date_key = 'release_date' if media_type == 'movie' else 'first_air_date'
        year = c.get(date_key, '')[:4]
        genres = [genre_map.get(gid, '') for gid in c.get('genre_ids', [])]
        genres = [g for g in genres if g]
        overview = c.get('overview', '')
        if len(overview) > 200:
            overview = overview[:200] + "..."
        cand_lines.append(
            f"- [{media_type.upper()}] ID: {c['id']}, Título: '{title}', Año: {year}, Géneros: {', '.join(genres)}, Puntuación: {c.get('vote_average')}\n  Resumen: {overview}"
        )
    candidates_str = "\n".join(cand_lines)
    
    prompt = f"""Eres un recomendador experto de cine y televisión. Tu tarea es analizar la lista de candidatos y seleccionar las mejores recomendaciones para el usuario basándote en su historial.

Historial del usuario:
Películas y series que le gustaron (LIKES):
{likes_str}

Películas y series que NO le gustaron (DISLIKES):
{dislikes_str}

Películas y series neutrales ("ni fu ni fa"):
{neutral_str}

Candidatos disponibles (películas y series nuevas, en tendencia o clásicos populares):
{candidates_str}

Instrucciones de recomendación:
1. Analiza los gustos del usuario. Le suelen gustar thrillers ingeniosos, suspense policial con giros narrativos, comedias negras con personajes satíricos y diálogos agudos (cine argentino/español muy valorado). Le desagradan las películas lentas, dramas sombríos o thrillers mediocres/tediosos.
2. Selecciona las mejores {count_m} películas y las mejores {count_t} series de la lista de candidatos que más se adapten a sus gustos.
3. Prioriza las novedades de los últimos años (2024-2026), pero OCASIONALMENTE (aproximadamente 1 de cada 4 recomendaciones) incluye un clásico aclamado (anterior a 2020) de la lista de candidatos que se adapte perfectamente a sus gustos y que no esté en sus listas de calificados.
4. Evita a toda costa recomendar títulos similares a los que NO le gustaron (DISLIKES). Usa la lista NEUTRAL para entender qué cosas le parecen indiferentes y afinar el límite.
5. Devuelve los resultados en formato JSON con la siguiente estructura exacta:
{{
  "movies": [
    {{
      "id": <tmdb_id>, 
      "title": "<titulo>", 
      "combined_text": "<sinopsis_muy_breve_de_la_trama>\\n<razon_de_la_recomendacion_segun_sus_gustos>"
    }}
  ],
  "tv": [
    {{
      "id": <tmdb_id>, 
      "title": "<titulo>", 
      "combined_text": "<sinopsis_muy_breve_de_la_trama>\\n<razon_de_la_recomendacion_segun_sus_gustos>"
    }}
  ]
}}
Nota crítica sobre el campo "combined_text":
- Debe tener como MÁXIMO 200 caracteres en total.
- Debe contener dos párrafos muy concisos separados por un único salto de línea (\\n).
- El primer párrafo resume la trama de forma ultra-breve (ej: 'Un hombre es encarcelado de forma injusta y planea una fuga magistral.').
- El segundo párrafo explica por qué le gustará en base a sus LIKES (ej: 'Te gustará por su suspenso policial al estilo de El secreto de sus ojos.').
- Ambos párrafos combinados (incluyendo el salto de línea) deben ser tan cortos que quepan en un máximo de 3 líneas al ser dibujados a tamaño de letra grande en la pantalla (máximo 200 caracteres en total).

Devuelve ÚNICAMENTE el código JSON limpio. No uses bloques de código markdown (como ```json) ni explicaciones de texto adicionales.
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            resp_json = r.json()
            text_res = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Limpiar markdown por seguridad
            if text_res.startswith("```"):
                lines = text_res.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                text_res = "\n".join(lines).strip()
                
            return json.loads(text_res)
        else:
            print(f"Error llamando a Gemini API: HTTP {r.status_code} - {r.text}")
            return None
    except Exception as e:
        print(f"Excepción al llamar a Gemini API: {e}")
        return None

# Chequear duplicados en Reddit con resiliencia
def was_already_posted(subreddit, title, limit=1000):
    try:
        for sub in subreddit.new(limit=limit):
            if sub.title.strip().lower() == title.strip().lower():
                return True
    except Exception as e:
        print(f"Error al verificar duplicados en Reddit para '{title}': {e}")
        return False
    return False

# Main completo
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
    
    # Cargar gustos del usuario
    preferences = load_preferences()
    likes = preferences.get('likes', [])
    dislikes = preferences.get('dislikes', [])
    neutral = preferences.get('neutral', [])
    
    # Obtener candidatos
    print("Recuperando candidatos de TMDB...")
    movie_candidates = get_candidates('movie', max_results=20)
    tv_candidates = get_candidates('tv', max_results=20)
    
    all_candidates = movie_candidates + tv_candidates
    
    # Consultar Gemini
    print(f"Consultando recomendaciones a Gemini ({GEMINI_MODEL})...")
    recommendations = ask_gemini_recommendations(
        likes, dislikes, neutral, all_candidates,
        numberofmovies, numberoftvshows
    )
    
    success_movies = 0
    success_tv = 0
    
    if recommendations and ('movies' in recommendations or 'tv' in recommendations):
        print("Recomendaciones inteligentes de Gemini recibidas:")
        rec_movies = recommendations.get('movies', [])
        rec_tv = recommendations.get('tv', [])
        
        # Películas recomendadas por IA
        print(f"\n--- Procesando {len(rec_movies)} Películas Recomendadas ---")
        for rec in rec_movies:
            mid = rec.get('id')
            title = rec.get('title')
            combined_text = rec.get('combined_text', '')
            print(f"Película elegida: {title} (ID: {mid})")
            if combined_text:
                print(f"  Texto combinado:\n{combined_text}")
                
            if mid in excluded_movies:
                print(f"Ignorada (exclusión manual): {title}")
                continue
                
            ok = process_recommended_item(mid, 'movie', custom_overview=combined_text)
            if ok:
                success_movies += 1
                title_norm = normalize_title(title)
                if not was_already_posted(subreddit, title_norm):
                    filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                    try:
                        subreddit.submit_image(title_norm, filename)
                        print(f"Subido a Reddit: {title_norm}")
                    except Exception as e:
                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                        
        # Series recomendadas por IA
        print(f"\n--- Procesando {len(rec_tv)} Series Recomendadas ---")
        for rec in rec_tv:
            tid = rec.get('id')
            title = rec.get('title')
            combined_text = rec.get('combined_text', '')
            print(f"Serie elegida: {title} (ID: {tid})")
            if combined_text:
                print(f"  Texto combinado:\n{combined_text}")
                
            if tid in excluded_tv:
                print(f"Ignorada (exclusión manual): {title}")
                continue
                
            ok = process_recommended_item(tid, 'tv', custom_overview=combined_text)
            if ok:
                success_tv += 1
                title_norm = normalize_title(title)
                if not was_already_posted(subreddit, title_norm):
                    filename = os.path.join(background_dir, clean_filename(title) + '.jpg')
                    try:
                        subreddit.submit_image(title_norm, filename)
                        print(f"Subido a Reddit: {title_norm}")
                    except Exception as e:
                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
    else:
        print("Fallo en Gemini o sin recomendaciones. Iniciando modo de fallback tradicional...")
        min_rating = float(os.getenv('TMDB_MIN_RATING', '6.5'))
        
        # Fallback Películas
        count_m = 0
        for m in movie_candidates:
            if count_m >= numberofmovies:
                break
            mid = m.get('id')
            if mid in excluded_movies:
                continue
            if m.get('original_language') in excluded_languages:
                continue
            rating = m.get('vote_average', 0)
            if rating < min_rating:
                continue
                
            year = m.get('release_date', '')[:4]
            try:
                item_year = int(year)
                if item_year < current_year - 3:
                    continue
            except ValueError:
                continue
                
            details = tmdb_get(f"movie/{mid}", {"language": "es-ES"})
            if not details:
                continue
                
            ok = process_image(
                f"https://image.tmdb.org/t/p/original{m.get('backdrop_path')}",
                m.get('title', ''), m.get('overview', ''), True,
                m.get('genre_ids', []), year, round(rating, 1),
                duration=details.get('runtime'), media_type='movie', media_id=mid
            )
            if ok:
                success_movies += 1
                count_m += 1
                title_norm = normalize_title(m.get('title', ''))
                if not was_already_posted(subreddit, title_norm):
                    filename = os.path.join(background_dir, clean_filename(m.get('title', '')) + '.jpg')
                    try:
                        subreddit.submit_image(title_norm, filename)
                        print(f"Subido a Reddit (fallback): {title_norm}")
                    except Exception as e:
                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                        
        # Fallback Series
        count_t = 0
        for tv in tv_candidates:
            if count_t >= numberoftvshows:
                break
            tid = tv.get('id')
            if tid in excluded_tv:
                continue
            if tv.get('original_language') in excluded_languages:
                continue
            rating = tv.get('vote_average', 0)
            if rating < min_rating:
                continue
                
            year = tv.get('first_air_date', '')[:4]
            try:
                item_year = int(year)
                if item_year < current_year - 3:
                    continue
            except ValueError:
                continue
                
            details = tmdb_get(f"tv/{tid}", {"language": "es-ES"})
            if not details:
                continue
                
            ok = process_image(
                f"https://image.tmdb.org/t/p/original{tv.get('backdrop_path')}",
                tv.get('name', ''), tv.get('overview', ''), False,
                tv.get('genre_ids', []), year, round(rating, 1),
                seasons=details.get('number_of_seasons'), media_type='tv', media_id=tid
            )
            if ok:
                success_tv += 1
                count_t += 1
                title_norm = normalize_title(tv.get('name', ''))
                if not was_already_posted(subreddit, title_norm):
                    filename = os.path.join(background_dir, clean_filename(tv.get('name', '')) + '.jpg')
                    try:
                        subreddit.submit_image(title_norm, filename)
                        print(f"Subido a Reddit (fallback): {title_norm}")
                    except Exception as e:
                        print(f"Error subiendo '{title_norm}' a Reddit: {e}")
                        
    print(f"\nProceso finalizado. Películas generadas/subidas: {success_movies}, Series: {success_tv}")

if __name__ == '__main__':
    main()
