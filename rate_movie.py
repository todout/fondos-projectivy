import os
import sys
import json
import requests
from dotenv import load_dotenv

# Robust input decoder to handle character encoding differences (e.g. CP850/Latin1 from Windows CMD over SSH)
def robust_input(prompt=""):
    if prompt:
        print(prompt, end="", flush=True)
    try:
        line_bytes = sys.stdin.buffer.readline()
        if not line_bytes:
            raise EOFError()
        while line_bytes and line_bytes[-1] in (10, 13):
            line_bytes = line_bytes[:-1]
        for enc in ['utf-8', 'cp850', 'latin1', 'cp1252']:
            try:
                return line_bytes.decode(enc)
            except UnicodeDecodeError:
                pass
        return line_bytes.decode('utf-8', errors='replace')
    except Exception as e:
        if isinstance(e, EOFError):
            raise e
        return input()

# Override standard input
input = robust_input

# Cargar variables de entorno
load_dotenv()

TMDB_TOKEN = os.getenv("TMDB_TOKEN")
if not TMDB_TOKEN:
    print("Error: No se encontró TMDB_TOKEN en el archivo .env")
    exit(1)

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {TMDB_TOKEN}"
}
tmdb_url = "https://api.themoviedb.org/3/"
preferences_path = "user_preferences.json"

def search_media(query):
    print(f"Buscando en TMDB: '{query}'...")
    # Usar search/multi para buscar películas y series a la vez
    params = {
        "query": query,
        "language": "es-ES"
    }
    r = requests.get(f"{tmdb_url}search/multi", headers=headers, params=params)
    if r.status_code != 200:
        print(f"Error en la búsqueda: HTTP {r.status_code}")
        return None
    
    results = [
        item for item in r.json().get("results", [])
        if item.get("media_type") in ["movie", "tv"]
    ]
    
    if not results:
        print("No se encontraron películas o series con ese nombre.")
        return None
    
    # Mostrar resultados y permitir seleccionar
    print("\nResultados encontrados:")
    for idx, item in enumerate(results[:5]):
        media_type = "Película" if item["media_type"] == "movie" else "Serie"
        title = item.get("title") or item.get("name")
        date_key = "release_date" if item["media_type"] == "movie" else "first_air_date"
        year = item.get(date_key, "")[:4]
        year_str = f" ({year})" if year else ""
        print(f"[{idx + 1}] {title}{year_str} - {media_type}")
        
    choice = 0
    if len(results) == 1:
        choice = 1
    else:
        while True:
            try:
                val = input(f"\nSelecciona una opción [1-{min(5, len(results))}]: ")
                choice = int(val)
                if 1 <= choice <= min(5, len(results)):
                    break
            except ValueError:
                pass
            print("Selección no válida.")
            
    selected = results[choice - 1]
    media_id = selected["id"]
    media_type = selected["media_type"]
    
    # Obtener detalles completos para los géneros y título oficial
    details_r = requests.get(f"{tmdb_url}{media_type}/{media_id}?language=es-ES", headers=headers)
    if details_r.status_code != 200:
        print(f"Error al obtener detalles: HTTP {details_r.status_code}")
        return None
        
    details = details_r.json()
    title = details.get("title") or details.get("name")
    date_key = "release_date" if media_type == "movie" else "first_air_date"
    year = details.get(date_key, "")[:4]
    genres = [g["name"] for g in details.get("genres", [])]
    
    return {
        "id": media_id,
        "title": title,
        "genres": genres,
        "year": year,
        "media_type": media_type
    }

def update_preferences(item, rating):
    # Cargar archivo existente
    if os.path.exists(preferences_path):
        try:
            with open(preferences_path, "r", encoding="utf-8") as f:
                preferences = json.load(f)
        except json.JSONDecodeError:
            preferences = {"likes": [], "dislikes": [], "neutral": []}
    else:
        preferences = {"likes": [], "dislikes": [], "neutral": []}
        
    # Inicializar claves si faltan
    for k in ["likes", "dislikes", "neutral"]:
        if k not in preferences:
            preferences[k] = []
            
    # Eliminar duplicados previos en todas las categorías
    item_id = item["id"]
    item_type = item.get("media_type", "movie")
    
    for category in ["likes", "dislikes", "neutral"]:
        # Se elimina buscando por ID y tipo de medio (por si hay una peli y serie con el mismo ID)
        preferences[category] = [
            x for x in preferences[category]
            if not (x.get("id") == item_id and x.get("media_type", "movie") == item_type)
        ]
        
    # Guardar en la nueva categoría elegida
    target_category = "neutral"
    rating_clean = rating.strip().lower()
    if rating_clean in ["like", "likes", "gusto", "gusta", "buena", "1"]:
        target_category = "likes"
    elif rating_clean in ["dislike", "dislikes", "disgusta", "mala", "0"]:
        target_category = "dislikes"
    elif rating_clean in ["neutral", "meh", "ni fu ni fa", "nifunifa", "regular", "2"]:
        target_category = "neutral"
        
    # Limpiar el item para guardar solo lo necesario
    saved_item = {
        "id": item["id"],
        "title": item["title"],
        "genres": item["genres"],
        "year": item["year"],
        "media_type": item_type
    }
    
    preferences[target_category].append(saved_item)
    
    # Escribir de vuelta
    with open(preferences_path, "w", encoding="utf-8") as f:
        json.dump(preferences, f, indent=2, ensure_ascii=False)
        
    cat_names = {
        "likes": "Gustados (LIKES)",
        "dislikes": "No gustados (DISLIKES)",
        "neutral": "Ni fu ni fa (NEUTRAL)"
    }
    print(f"\n¡Guardado con éxito! '{item['title']}' ({item['year']}) agregado a: {cat_names[target_category]}")

def main():
    query = ""
    rating = ""
    
    # Verificar si se pasaron argumentos
    if len(sys.argv) > 2:
        query = sys.argv[1]
        rating = sys.argv[2]
    elif len(sys.argv) == 2:
        query = sys.argv[1]
    
    # Si no hay argumentos, ir a modo interactivo
    if not query:
        query = input("Ingresa el título de la película o serie: ").strip()
    if not query:
        print("Búsqueda cancelada.")
        return
        
    item = search_media(query)
    if not item:
        return
        
    # Verificar si ya existe en las preferencias
    found_category = None
    if os.path.exists(preferences_path):
        try:
            with open(preferences_path, "r", encoding="utf-8") as f:
                preferences = json.load(f)
                
            item_id = item["id"]
            item_type = item.get("media_type", "movie")
            
            for category in ["likes", "dislikes", "neutral"]:
                for x in preferences.get(category, []):
                    if x.get("id") == item_id and x.get("media_type", "movie") == item_type:
                        found_category = category
                        break
                if found_category:
                    break
        except Exception:
            pass

    cat_names = {
        "likes": "Gustados (LIKES)",
        "dislikes": "No gustados (DISLIKES)",
        "neutral": "Ni fu ni fa (NEUTRAL)"
    }
    
    if found_category and not rating:
        print(f"\nℹ️ '{item['title']}' ({item['year']}) ya está en tu lista de: {cat_names[found_category]}")
        confirm = input("¿Quieres cambiar tu voto/categoría? [s/N]: ").strip().lower()
        if confirm not in ["s", "si", "y", "yes"]:
            print("Operación cancelada. No se realizaron cambios.")
            return

    if not rating:
        print("\n¿Qué te pareció?")
        print("[1] Me gustó (LIKE)")
        print("[2] Ni fu ni fa (NEUTRAL)")
        print("[3] No me gustó (DISLIKE)")
        while True:
            r_val = input("Elige una opción [1-3]: ").strip()
            if r_val == "1":
                rating = "like"
                break
            elif r_val == "2":
                rating = "neutral"
                break
            elif r_val == "3":
                rating = "dislike"
                break
            elif r_val.lower() in ["like", "dislike", "neutral", "nifunifa", "meh"]:
                rating = r_val.lower()
                break
            print("Opción no válida.")
            
    update_preferences(item, rating)

if __name__ == "__main__":
    main()
