import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
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

# Session with exponential backoff for requests
def get_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    proxy = get_random_proxy()
    if proxy:
        session.proxies = {
            'http': proxy,
            'https': proxy
        }
        
    return session

# TTLCache: Kesh 1 soat (3600 soniya) yashaydi, max 1000 ta ob'yekt
url_cache = TTLCache(maxsize=1000, ttl=3600)
audio_cache = TTLCache(maxsize=1000, ttl=3600)

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

@cached(cache=url_cache)
def scrape_title_from_url(url: str) -> str:
    try:
        session = get_session()
        headers = {
            'User-Agent': ua.random,
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        res = session.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        
        # Use res.content to let BeautifulSoup auto-detect encoding from meta tags
        soup = BeautifulSoup(res.content, 'html.parser')
        title = soup.title.text if soup.title else ""
        
        if not title: return ""
        
        # Remove common zero-width or formatting chars
        title = title.replace('\u200e', '').replace('\xa0', ' ')
        
        # 1. Yandex Music
        title = re.sub(r'—\s*Yandex Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'-\s*Yandex Music.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'Yandex Music ilovasida.*', '', title, flags=re.IGNORECASE)
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

@cached(cache=audio_cache)
def search_and_get_audio_url(search_query: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'default_search': 'ytsearch',
        'extract_flat': False,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'sleep_interval_requests': 1,
        'max_sleep_interval': 3,
    }
    
    proxy = get_random_proxy()
    if proxy:
        ydl_opts['proxy'] = proxy
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch1:{search_query} audio", download=False)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                return {
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader", "Unknown"),
                    "download_url": entry.get("url", ""),
                    "thumbnail": entry.get("thumbnail", ""),
                    "duration": entry.get("duration", 0)
                }
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
    
    # 2. YouTube'dan 100% to'liq audioni qidirish va olish
    audio_data = search_and_get_audio_url(scraped_name)
    
    if not audio_data or not audio_data["download_url"]:
        raise HTTPException(status_code=404, detail=f"Could not extract full audio file. Search query: {scraped_name}")
        
    return DownloadResponse(**audio_data)

@app.get("/")
def root():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
