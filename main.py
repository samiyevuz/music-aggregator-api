import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
from dotenv import load_dotenv
import re
from fake_useragent import UserAgent
from cachetools import TTLCache, cached
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

app = FastAPI(title="Music Downloader API", description="URL orqali to'liq qo'shiq yuklash API")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": str(exc),
            "recommendation": "The third-party service might be temporarily unavailable. Please try again later or check the URL.",
            "request_url": str(request.url)
        }
    )

# --- Anti-ban & Rate-Limit Configs ---
# UserAgent generator
ua = UserAgent(fallback='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')

# Proxy Generator
def get_random_proxy():
    import random
    # Har bir so'rovda yangi IP olish uchun tasodifiy sessiya ID yaratamiz (8 xonali son)
    session_id = random.randint(10000000, 99999999)
    # ttl-15 orqali IP o'zini 15 daqiqa saqlab turadi, lekin har safar yangi session_id chaqirilganda yangi IP beriladi
    proxy = f"http://REeRXlovbZw8qA9:rB32ciO4SfzVl6Z_session-{session_id}_ttl-15@thehub.proxy-cheap.com:8080"
    return proxy

# Session with fast retry for requests
def get_session(use_proxy=True):
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    if use_proxy:
        proxy = get_random_proxy()
        session.proxies = {
            'http': proxy,
            'https': proxy
        }
        
    return session

# TTLCache: Kesh 1 soat (3600 soniya) yashaydi, max 1000 ta ob'yekt
url_cache = TTLCache(maxsize=1000, ttl=3600)
# audio_cache: Qisqa muddatli (5 daqiqa) — takroriy so'rovlar uchun tezkor javob
audio_cache = TTLCache(maxsize=500, ttl=300)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# RapidAPI Secret tekshiruvi bekor qilindi

class DownloadResponse(BaseModel):
    title: str
    artist: str
    download_url: str
    thumbnail: str
    duration: int

# --- Yandex Music reklama/xato kontentni aniqlash ---
YANDEX_JUNK_PATTERNS = [
    r'продвижение',
    r'как попасть',
    r'набрать прослушивания',
    r'подписчик',
    r'smm',
    r'монетизация',
    r'маркетинг',
    r'реклам',
    r'промо',
    r'раскрутк',
]
JUNK_RE = re.compile('|'.join(YANDEX_JUNK_PATTERNS), re.IGNORECASE)

def _is_junk_title(title: str) -> bool:
    """Yandex proxy orqali olingan reklama/promo sahifalarini aniqlash"""
    if not title:
        return True
    return bool(JUNK_RE.search(title))

def _extract_yandex_title_from_html(html_content: bytes) -> str:
    """Yandex Music sahifasidan title ni chiqarib olish — ld+json, og:title va meta teglardan"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 0. ld+json - Eng aniq metadata
    import json
    ld_json = soup.find('script', type='application/ld+json')
    if ld_json and ld_json.string:
        try:
            data = json.loads(ld_json.string)
            if isinstance(data, list):
                data = data[0]
            if data.get('@type') == 'MusicRecording':
                title = data.get('name', '')
                artist_data = data.get('byArtist', {})
                # artist_data list yoki dict bo'lishi mumkin
                if isinstance(artist_data, list):
                    artists = " ".join([a.get('name', '') for a in artist_data])
                else:
                    artists = artist_data.get('name', '')
                if title and artists:
                    return f"{title} {artists}".strip()
                elif title:
                    return title.strip()
        except Exception as e:
            print(f"JSON-LD error: {e}")

    # 1. og:title
    og = soup.find('meta', property='og:title')
    if og and og.get('content'):
        return og['content'].strip()
    
    # 2. <title> tegi
    if soup.title and soup.title.text:
        return soup.title.text.strip()
        
    # 3. Regex fallback (for React SSR strings)
    try:
        html_str = html_content.decode('utf-8', 'ignore')
        import re
        m1 = re.search(r'\"property\":\"og:title\",\"content\":\"([^\"]+)\"', html_str)
        if m1:
            return m1.group(1).split('—')[0].strip()
    except Exception:
        pass
        
    return ""

@cached(cache=url_cache)
def scrape_title_from_url(url: str) -> str:
    try:
        is_yandex = 'yandex' in url.lower()
        # Proxy faqat Yandex uchun kerak (SmartCaptcha), Spotify/Apple to'g'ridan-to'g'ri ishlaydi
        session = get_session(use_proxy=is_yandex)
        headers = {
            'User-Agent': ua.random,
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        res = session.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        
        if is_yandex:
            title = _extract_yandex_title_from_html(res.content)
        elif 'spotify' in url.lower():
            try:
                # OEmbed orqali olish (HTML scraping bloklanishiga qarshi)
                oembed_url = f"https://open.spotify.com/oembed?url={url}"
                oembed_res = session.get(oembed_url, timeout=5)
                if oembed_res.status_code == 200:
                    title = oembed_res.json().get('title', '')
                else:
                    soup = BeautifulSoup(res.content, 'html.parser')
                    title = soup.title.text if soup.title else ""
            except Exception:
                soup = BeautifulSoup(res.content, 'html.parser')
                title = soup.title.text if soup.title else ""
        else:
            soup = BeautifulSoup(res.content, 'html.parser')
            title = soup.title.text if soup.title else ""
        
        if not title: return ""
        
        # Yandex uchun: agar reklama/junk kontent bo'lsa, keshdan o'chirib, proxyni yangilab qayta urinish
        if is_yandex and _is_junk_title(title):
            print(f"JUNK detected from Yandex: '{title}', retrying with new proxy...")
            url_cache.pop(url, None)
            
            session2 = get_session()
            headers['User-Agent'] = ua.random
            res2 = session2.get(url, headers=headers, timeout=10)
            res2.raise_for_status()
            title = _extract_yandex_title_from_html(res2.content)
            
            if not title or _is_junk_title(title):
                print(f"JUNK still detected after retry: '{title}'")
                title = _extract_from_url_path(url)
                if not title:
                    return ""
        
        # Remove common zero-width or formatting chars
        title = title.replace('\u200e', '').replace('\xa0', ' ')
        
        # 1. Yandex Music
        title = re.sub(r'—\s*Yandex Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'-\s*Yandex Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'Yandex Music ilovasida.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'Listen online on Yandex Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'Слушать онлайн на Яндекс.*', '', title, flags=re.IGNORECASE)
        
        # 2. Apple Music 
        title = re.sub(r'—\s*Apple\s*Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'-\s*Apple\s*Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'on Apple Music', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^Песня\s*«(.*?)»', r'\1', title)
        title = re.sub(r'^Song\s*«(.*?)»', r'\1', title)
        title = title.replace('«', '').replace('»', '')
        
        # 3. Spotify
        title = re.sub(r'\|\s*Spotify.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'song and lyrics by', '-', title, flags=re.IGNORECASE)
        
        return title.strip()
    except Exception as e:
        print(f"Scrape Error: {e}")
        return ""

def _extract_from_url_path(url: str) -> str:
    """URL yo'lidan track/album ID orqali Yandex Music API dan metadata olishga harakat"""
    # Yandex URL: music.yandex.uz/album/ALBUM_ID/track/TRACK_ID
    m = re.search(r'album/(\d+)/track/(\d+)', url)
    if not m:
        return ""
    album_id, track_id = m.group(1), m.group(2)
    try:
        api_url = f"https://music.yandex.ru/handlers/track.jsx?track={track_id}:{album_id}"
        headers = {'User-Agent': ua.random, 'Accept': 'application/json'}
        r = requests.get(api_url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            track = data.get('track', {})
            title = track.get('title', '')
            artists = ', '.join([a.get('name', '') for a in track.get('artists', [])])
            if title and artists:
                return f"{title} {artists}"
            elif title:
                return title
    except Exception as e:
        print(f"Yandex API fallback error: {e}")
    return ""

def search_and_get_audio_url(search_query: str, is_yandex: bool = False):
    # Keshda bor bo'lsa, darhol qaytarish (5 daqiqa ichida)
    if search_query in audio_cache:
        return audio_cache[search_query]
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'default_search': 'ytsearch',
        'extract_flat': False,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'no_check_formats': True,  # Format tekshirishni o'tkazib yuborish — tezroq
        'socket_timeout': 8,
        'proxy': get_random_proxy(),  # YouTube server IP ni bloklaydi — proxy shart
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # Spotify/Apple uchun: "official audio" ni qo'shamiz va 2 ta natijadan qidiramiz (timeout oldini olish uchun)
            search_query_refined = search_query if is_yandex else f"{search_query} official audio"
            info = ydl.extract_info(f"ytsearch3:{search_query_refined}", download=False)
            if 'entries' in info and len(info['entries']) > 0:
                for entry in info['entries']:
                    duration = entry.get("duration", 0)
                    if duration and duration < 30:
                        continue  # 30 soniyadan qisqa reklama bo'lishi mumkin
                    
                    result = {
                        "title": entry.get("title", "Unknown"),
                        "artist": entry.get("uploader", "Unknown"),
                        "download_url": entry.get("url", ""),
                        "thumbnail": entry.get("thumbnail", ""),
                        "duration": duration
                    }
                    # Keshga saqlash (5 daqiqa)
                    audio_cache[search_query] = result
                    return result
            return None
        except Exception as e:
            print(f"yt-dlp error: {e}")
            return None

@app.get("/download", response_model=DownloadResponse)
def download_music(url: str):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format. Please provide a valid Yandex, Spotify, or Apple Music link.")

    # 1. Havoladan qo'shiq nomini aniqlash
    scraped_name = scrape_title_from_url(url)
    
    if not scraped_name:
        raise HTTPException(status_code=404, detail="Could not extract song name from URL. The link might be invalid or unsupported.")
    
    is_yandex = 'yandex' in url.lower()
    
    # 2. YouTube'dan 100% to'liq audioni qidirish va olish (optimallashtirilgan qidiruv bilan)
    audio_data = search_and_get_audio_url(scraped_name, is_yandex=is_yandex)
    
    if not audio_data or not audio_data["download_url"]:
        raise HTTPException(status_code=404, detail=f"Could not extract full audio file. Search query: {scraped_name}")
        
    return DownloadResponse(**audio_data)

@app.get("/")
def root():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
