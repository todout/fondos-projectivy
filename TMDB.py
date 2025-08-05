import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
import os
import shutil
from urllib.request import urlopen
import textwrap
from datetime import datetime, timedelta
import praw
import time
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Base URL for the API
url = "https://api.themoviedb.org/3/"

# Set your TMDB API Read Access Token key here
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {os.getenv('TMDB_TOKEN')}"
}

# Load font
truetype_path = 'Roboto-Light.ttf'
if not os.path.exists(truetype_path):
    truetype_url = 'https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Light.ttf'
    response = requests.get(truetype_url, timeout=10)
    if response.status_code == 200:
        with open(truetype_path, 'wb') as f:
            f.write(response.content)

# Configuración
date_str = datetime.now().strftime("%Y%m%d")
numberofmovies = 5
numberoftvshows = 5
current_year = datetime.now().year
background_dir = "tmdbbackgrounds"
excluded_genres = {"Animación", "Terror", "Sci-Fi & Fantasy"}

def normalize_title(title):
    return " ".join(title.replace("_", " ").replace(date_str, "").split()).strip()

# Eliminar imágenes anteriores
i = 0
if os.path.exists(background_dir):
    for file in os.listdir(background_dir):
        if file.endswith(".jpg"):
            os.remove(os.path.join(background_dir, file))
            i += 1
    print(f"Se eliminaron {i} imágenes previas")
os.makedirs(background_dir, exist_ok=True)

# Obtener lista de géneros en español
genre_map = {}

def load_genres():
    global genre_map
    genres = []
    for media_type in ["movie", "tv"]:
        response = requests.get(f"{url}genre/{media_type}/list?language=es-ES", headers=headers)
        if response.status_code == 200:
            genres += response.json().get("genres", [])
    genre_map = {g['id']: g['name'] for g in genres}
    # Corrección de traducciones
    if "Suspense" in genre_map.values():
        for key, val in genre_map.items():
            if val == "Suspense":
                genre_map[key] = "Suspenso"

# Funciones auxiliares
def resize_image(image, height):
    ratio = height / image.height
    width = int(image.width * ratio)
    return image.resize((width, height))

def clean_filename(filename):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)

def draw_multiline_text(draw, position, text, font, fill, spacing, shadow_color=None, shadow_offset=2):
    if shadow_color:
        draw.multiline_text((position[0] + shadow_offset, position[1] + shadow_offset), text, font=font, fill=shadow_color, spacing=spacing)
    draw.multiline_text(position, text, font=font, fill=fill, spacing=spacing)

def format_duration(minutes):
    if not isinstance(minutes, int):
        return ""
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m}m" if h else f"{m}m"

def get_logo_path(media_type, media_id):
    endpoint = f"{url}{media_type}/{media_id}/images"
    response = requests.get(endpoint, headers=headers).json()
    logos = response.get('logos', [])
    
    # Filtrar por idioma
    es_logos = [l for l in logos if l.get("iso_639_1") == "es"]
    en_logos = [l for l in logos if l.get("iso_639_1") == "en"]

    def avg_luminance(logo_path):
        try:
            logo_url = "https://image.tmdb.org/t/p/original" + logo_path
            logo_img = Image.open(BytesIO(requests.get(logo_url).content)).convert("RGBA")
            logo_img = logo_img.resize((100, 100))
            pixels = list(logo_img.getdata())
            return sum((0.299*r + 0.587*g + 0.114*b) for r, g, b, a in pixels if a > 0) / len(pixels)
        except:
            return 0

    def get_best_logo(candidates):
        sorted_logos = sorted(candidates, key=lambda l: l['width'] / l['height'], reverse=True)
        top_logos = sorted_logos[:2]
        if not top_logos:
            return None
        if len(top_logos) == 1:
            return top_logos[0]['file_path']
        lum1 = avg_luminance(top_logos[0]['file_path'])
        lum2 = avg_luminance(top_logos[1]['file_path'])
        return top_logos[0]['file_path'] if lum1 >= lum2 else top_logos[1]['file_path']

    # Preferir español, si no hay usar inglés
    if es_logos:
        return get_best_logo(es_logos)
    elif en_logos:
        return get_best_logo(en_logos)
    else:
        return None

def process_image(image_url, title, overview, is_movie, genre_ids, year, rating, duration=None, seasons=None, media_type=None, media_id=None):
    if not overview.strip():
        print(f"{title} ignorado por falta de descripción")
        return

    genre_names = [genre_map.get(gid, str(gid)) for gid in genre_ids]
    if any(g in excluded_genres for g in genre_names):
        print(f"{title} ignorado por género excluido")
        return

    response = requests.get(image_url, timeout=10)
    if response.status_code != 200:
        print(f"Failed to download image for {title}")
        return

    image = Image.open(BytesIO(response.content))
    image = resize_image(image, 1500)
    bckg = Image.open("bckg.png")
    overlay = Image.open("overlay.png")
    bckg.paste(image, (1175, 0))
    bckg.paste(overlay, (1175, 0), overlay)

    draw = ImageDraw.Draw(bckg)
    font_title = ImageFont.truetype(truetype_path, size=190)
    font_info = ImageFont.truetype(truetype_path, size=60)
    font_overview = ImageFont.truetype(truetype_path, size=78)

    shadow_color = "black"
    main_color = "white"
    overview_color = (150, 150, 150)
    metadata_color = "white"

    title_position = (200, 420)
    overview_position = (210, 860)
    shadow_offset = 2
    info_position = (210, 720)

    wrapped_lines = textwrap.wrap(overview, width=70)
    truncated = len(wrapped_lines) > 7
    wrapped_lines = wrapped_lines[:7]
    if truncated:
        wrapped_lines[-1] = wrapped_lines[-1].rstrip('.') + "..."
    wrapped_overview = "\n".join(wrapped_lines)
    draw_multiline_text(draw, overview_position, wrapped_overview, font=font_overview, fill=metadata_color, spacing=16, shadow_color=shadow_color, shadow_offset=shadow_offset)

    if is_movie:
        additional_info = format_duration(duration)
    else:
        additional_info = f"{seasons} {'Temporada' if seasons == 1 else 'Temporadas'}"

    genre_text = ", ".join(genre_names)
    rating_text = "TMDB: " + str(rating)
    year_text = str(year)[:4]
    info_text = f"{genre_text}  •  {year_text}  •  {additional_info}  •  {rating_text}"

    draw.text((info_position[0] + shadow_offset, info_position[1] + shadow_offset), info_text, font=font_info, fill=shadow_color)
    draw.text(info_position, info_text, font=font_info, fill=overview_color)

    logo_path = get_logo_path(media_type, media_id)
    if logo_path:
        try:
            logo_url = "https://image.tmdb.org/t/p/original" + logo_path
            logo_img = Image.open(BytesIO(requests.get(logo_url).content)).convert("RGBA")
            top_margin = 150
            bottom_y = info_position[1] - 40
            max_logo_height = bottom_y - top_margin
            max_logo_width = 1600
            ratio = min(max_logo_height / logo_img.height, max_logo_width / logo_img.width)
            new_width = int(logo_img.width * ratio)
            new_height = int(logo_img.height * ratio)
            logo_img = logo_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            logo_x = info_position[0] + 10 + (max_logo_width - new_width) // 2
            logo_y = bottom_y - new_height - 20
            bckg.paste(logo_img, (logo_x, logo_y), logo_img)
        except Exception as e:
            print(f"Error cargando logo: {e}")
            draw.text((title_position[0] + shadow_offset, title_position[1] + shadow_offset), title, font=font_title, fill=shadow_color)
            draw.text(title_position, title, font=font_title, fill=main_color)
    else:
        draw.text((title_position[0] + shadow_offset, title_position[1] + shadow_offset), title, font=font_title, fill=shadow_color)
        draw.text(title_position, title, font=font_title, fill=main_color)

    filename = os.path.join(background_dir, f"{clean_filename(title)}.jpg")
    bckg.convert('RGB').save(filename)
    print(f"Image saved: {filename}")


# Obtener trending
def get_trending(media_type):
    endpoint = f"{url}trending/{media_type}/week?language=es-ES"
    return requests.get(endpoint, headers=headers).json().get("results", [])

def get_movie_details(movie_id):
    return requests.get(f"{url}movie/{movie_id}?language=es-ES", headers=headers).json()

def get_tv_details(tv_id):
    return requests.get(f"{url}tv/{tv_id}?language=es-ES", headers=headers).json()

# Cargar géneros
load_genres()

# Procesar películas
for movie in get_trending("movie"):
    year = movie.get('release_date', '')[:4]
    if str(current_year) != year:
        continue
    details = get_movie_details(movie['id'])
    process_image(
        f"https://image.tmdb.org/t/p/original{movie['backdrop_path']}",
        movie['title'],
        movie['overview'],
        is_movie=True,
        genre_ids=movie.get('genre_ids', []),
        year=year,
        rating=round(movie.get('vote_average', 0), 1),
        duration=details.get('runtime', 'N/A'),
        media_type="movie",
        media_id=movie['id']
    )

# Procesar series
for tv in get_trending("tv"):
    year = tv.get('first_air_date', '')[:4]
    if str(current_year) != year:
        continue
    details = get_tv_details(tv['id'])
    process_image(
        f"https://image.tmdb.org/t/p/original{tv['backdrop_path']}",
        tv['name'],
        tv['overview'],
        is_movie=False,
        genre_ids=tv.get('genre_ids', []),
        year=year,
        rating=round(tv.get('vote_average', 0), 1),
        seasons=details.get('number_of_seasons', 0),
        media_type="tv",
        media_id=tv['id']
    )

# Subir a Reddit
def was_already_posted(reddit, subreddit_name, title):
    for submission in reddit.subreddit(subreddit_name).new(limit=25):
        if submission.title.strip().lower() == title.strip().lower():
            return True
    return False

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent="tmdb uploader by u/" + os.getenv("REDDIT_USERNAME"),
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD")
)

subreddit_name = "IMDB_esp"
subreddit = reddit.subreddit(subreddit_name)

for submission in reddit.subreddit(subreddit_name).new(limit=100):
    try:
         submission.delete()
         print(f"Borrado: {submission.title}")
    except Exception as e:
         print(f"Error al borrar {submission.title}: {e}")

for file in os.listdir(background_dir):
    if file.endswith(".jpg"):
        filepath = os.path.join(background_dir, file)
        title = normalize_title(os.path.splitext(file)[0])
        if was_already_posted(reddit, subreddit_name, title):
            print(f"Ya fue publicado en Reddit: {title}")
            continue
        try:
            subreddit.submit_image(title, filepath)
            print(f"Subido a Reddit: {title}")
        except Exception as e:
            print(f"Error subiendo {title}: {e}")
