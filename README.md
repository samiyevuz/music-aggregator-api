# Music Aggregator API

Bu loyiha Spotify, Apple Music va Yandex Music platformalarida asinxron qidiruv qilib, bitta endpoint orqali birlashtirib beruvchi (aggregator) FastAPI dasturidir. Loyiha RapidAPI xizmatiga ulanish va API sotish uchun maxsus tayyorlangan.

## Ishga tushirish qadamlari

### 1. Muhitni sozlash (Virtual Environment)
Loyihani ishga tushirish uchun Python o'rnatilgan bo'lishi kerak. Virtual muhit yaratish va kutubxonalarni o'rnatish:

```bash
# Virtual muhit yaratish
python -m venv venv

# Virtual muhitga kirish (Windows)
venv\Scripts\activate

# Yoki Mac/Linux uchun
source venv/bin/activate

# Kutubxonalarni o'rnatish
pip install -r requirements.txt
```

### 2. `.env` faylini sozlash
`.env.example` faylidan nusxa olib, `.env` faylini yarating. So'ngra API kalitlarini to'ldiring:
```bash
cp .env.example .env
```
Keyin `.env` ni ochib kerakli ma'lumotlarni kiriting.

### 3. Serverni ishga tushirish
Serverni uvicorn orqali yurgizish uchun quyidagi buyruqni bering:
```bash
python main.py
```
Yoki:
```bash
uvicorn main:app --reload
```

## API Dan Foydalanish
Ushbu API bevosita RapidAPI orqali ishlashga sozlangan. `X-RapidAPI-Proxy-Secret` tekshiruvi bor. 

Qidirish endpoint'i: 
`GET /search?query=YOUR_KEYWORD`

**Headers (Sarlavha):**
- `x-rapidapi-proxy-secret`: Sizning `.env` da ko'rsatgan Maxfiy so'zingiz.

### Swagger UI (Hujjat)
FastAPI avtomatik hujjat ham yaratadi, u brauzeringizda quyidagi manzilda ishlaydi:
`http://127.0.0.1:8000/docs`
*(Test qilib ko'rish uchun "Authorize" qismiga e'tibor bering)*
