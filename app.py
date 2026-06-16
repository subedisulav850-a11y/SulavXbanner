import io
import os
import re
import json
import time
import base64
import codecs
import random
import asyncio
import logging
import urllib.request
import urllib.error
import zipfile
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, Response, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor
import httpx
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ================= Logging =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ff_api")

# ================= Configuration =================
# Banner settings
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0
AVATAR_SHIFT_X = 0
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

# Fonts (optional)
FONT_MAIN = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"
PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

# Outfit settings
OUTFIT_BACKGROUND = "outfit.png"
ICON_SIZE = (95, 95)
CHARACTER_RENDER_SIZE = (700, 700)
FALLBACK_IDS = ["211000000", "214000000", "208000000", "203000000", "204000000", "205000000", "212000000"]
DEFAULT_AVATAR_ID = "710034057"
HEX_POSITIONS = {
    "mask": (990, 420), "shirt": (190, 90), "pants": (40, 420),
    "shoes": (840, 90), "emote": (40, 230), "armor": (990, 230),
    "weapon": (190, 560), "pet": (840, 560)
}

# API URLs
INFO_API_URL = "https://info.killersharmabot.online/player-info"
CDN_URL = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"
EAT_TARGET_URL = os.environ.get("TARGET_API_URL", "https://api-otrss.garena.com/support/callback/")

# JWT Configuration (original working method)
HEX_KEY = bytes.fromhex("32656534343831396539623435393838343531343130363762323831363231383734643064356437616639643866376530306331653534373135623764316533")
REGION_LANG = {"ME": "ar", "IND": "hi", "ID": "id", "VN": "vi", "TH": "th", "BD": "bn", "PK": "ur", "TW": "zh", "CIS": "ru", "SAC": "es", "BR": "pt"}
ALL_REGIONS = list(REGION_LANG.keys())
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

# Token caches
token_cache = {}
jwt_cache = {}

# ================= LEVELS Dictionary =================
LEVELS = {
    "1": 0, "2": 48, "3": 202, "4": 544, "5": 1012, "6": 1844, "7": 2792, "8": 3800,
    "9": 4870, "10": 6004, "11": 7192, "12": 8448, "13": 9776, "14": 11140, "15": 12566,
    "16": 14060, "17": 15610, "18": 17224, "19": 18902, "20": 20632, "21": 22424,
    "22": 24728, "23": 26192, "24": 28166, "25": 30200, "26": 32294, "27": 34448,
    "28": 37804, "29": 41174, "30": 44870, "31": 48852, "32": 53334, "33": 58566,
    "34": 64096, "35": 69994, "36": 76460, "37": 83108, "38": 91128, "39": 99322,
    "40": 108092, "41": 120144, "42": 133266, "43": 147472, "44": 162760, "45": 179126,
    "46": 196572, "47": 215368, "48": 235516, "49": 257010, "50": 279860, "51": 304056,
    "52": 348318, "53": 394982, "54": 444044, "55": 495508, "56": 549364, "57": 633756,
    "58": 721744, "59": 813336, "60": 908522, "61": 1041438, "62": 1180352, "63": 1325256,
    "64": 1476184, "65": 1634300, "66": 1840946, "67": 2056594, "68": 2281242, "69": 2514880,
    "70": 2757530, "71": 3059506, "72": 3372284, "73": 3699456, "74": 4041030, "75": 4397020,
    "76": 4829104, "77": 5282204, "78": 5756304, "79": 6251404, "80": 6767504, "81": 7381324,
    "82": 8043154, "83": 8752952, "84": 9510808, "85": 10316638, "86": 11277190, "87": 12360748,
    "88": 13360304, "89": 14482858, "90": 15659418, "91": 17026708, "92": 18453688, "93": 19941280,
    "94": 21488570, "95": 23095858, "96": 24763138, "97": 26490138, "98": 28277708, "99": 30124996,
    "100": 32032284,
}

# ================= Helper Functions (Banner/Outfit) =================
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b\uFEFF\uf8ff]', '', str(text))
    return ' '.join(text.split())

def load_unicode_font(size: int, font_file: str = FONT_MAIN):
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()

def is_cherokee(c: str) -> bool:
    return 0x13A0 <= ord(c) <= 0x13FF or 0xAB70 <= ord(c) <= 0xABBF

def draw_text_stroked(draw, x, y, text, f_main, f_alt, stroke=3):
    if not text:
        return
    cx = x
    for ch in text:
        font = f_alt if is_cherokee(ch) else f_main
        for dx in range(-stroke, stroke+1):
            for dy in range(-stroke, stroke+1):
                draw.text((cx+dx, y+dy), ch, font=font, fill="black")
        draw.text((cx, y), ch, font=font, fill="white")
        cx += font.getlength(ch)

async def fetch_image_bytes(item_id: str) -> Optional[bytes]:
    if not item_id or str(item_id).lower() in ("0", "none", "null"):
        return None
    url = f"{CDN_URL}/{item_id}.png"
    try:
        resp = await app.state.client.get(url)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Fetch error {item_id}: {e}")
    return None

def bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

def sync_fetch_url(url: str) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"Sync fetch error {url}: {e}")
        return None

def fetch_icon(icon_id, size=ICON_SIZE, is_character=False):
    try:
        if is_character:
            url = f"https://raw.githubusercontent.com/danggerr88-alt/danger-character-api/main/pngs/{icon_id}.png"
            data = sync_fetch_url(url)
            if data:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                w, h = img.size
                ratio = min(size[0] / w, size[1] / h)
                new_size = (int(w * ratio), int(h * ratio))
                return img.resize(new_size, Image.Resampling.LANCZOS)
        ids_to_try = [str(icon_id)] if icon_id and str(icon_id) != "0" else []
        for fid in FALLBACK_IDS:
            if fid not in ids_to_try:
                ids_to_try.append(fid)
        for i in ids_to_try:
            url = f"https://iconapi.wasmer.app/{i}"
            data = sync_fetch_url(url)
            if data:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                return img.resize(size, Image.Resampling.LANCZOS)
    except Exception as e:
        logger.warning(f"Icon fetch error: {e}")
    return None

async def fetch_real_player_data(uid: str) -> Dict[str, Any]:
    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(502, f"API error: {resp.status_code}")
    data = resp.json()
    profile = data.get("profileInfo", {})
    clan = data.get("clanBasicInfo", {})
    basic = data.get("basicInfo", {})
    prime_info = data.get("primeInfo", {})

    name = clean_text(profile.get("nickname") or basic.get("nickname") or "Unknown")
    level = str(profile.get("level") or basic.get("level") or 0)
    guild = clean_text(clan.get("clanName", ""))
    headPic = str(profile.get("headPic") or basic.get("headPic") or "")
    banner_id = str(profile.get("bannerId") or basic.get("bannerId") or "")

    # Robust prime level extraction
    prime_level = None
    if "primeLevel" in prime_info:
        prime_level = prime_info.get("primeLevel")
    elif "primeLevel" in profile:
        prime_level = profile.get("primeLevel")
    elif "primeLevel" in basic:
        prime_level = basic.get("primeLevel")
    elif "primeLevel" in data:
        prime_level = data.get("primeLevel")
    if prime_level is None:
        for obj in [prime_info, profile, basic, data]:
            if isinstance(obj, dict) and "level" in obj and "prime" in str(obj.get("level")):
                prime_level = obj.get("level")
                break
    if prime_level is None:
        prime_level = 0
    try:
        prime_level = max(0, min(8, int(prime_level)))
    except:
        prime_level = 0

    clothes = profile.get("clothes") or []
    weapon_skins = basic.get("weaponSkinShows") or []
    weapon = weapon_skins[0] if weapon_skins else None
    pet = data.get("petInfo", {}).get("skinId")
    character = profile.get("avatarId") or DEFAULT_AVATAR_ID

    return {
        "name": name, "level": level, "guild": guild,
        "headPic": headPic, "banner_id": banner_id, "prime_level": prime_level,
        "clothes": clothes, "weapon": weapon, "pet": pet, "character": character,
        "exp": basic.get("exp", 0)
    }

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    if len(words) <= 1:
        return [text]
    for i in range(1, len(words)):
        line1 = ' '.join(words[:i])
        line2 = ' '.join(words[i:])
        try:
            if font.getlength(line1) <= max_width and font.getlength(line2) <= max_width:
                return [line1, line2]
        except:
            pass
    return [text]

def generate_banner_image(avatar_bytes: Optional[bytes], banner_bytes: Optional[bytes], player: Dict[str, Any]) -> io.BytesIO:
    TARGET = 400
    avatar = bytes_to_image(avatar_bytes)
    try:
        zoom = int(TARGET * AVATAR_ZOOM)
        avatar = avatar.resize((zoom, zoom), Image.LANCZOS)
        left = (zoom - TARGET) // 2 - AVATAR_SHIFT_X
        top = (zoom - TARGET) // 2 - AVATAR_SHIFT_Y
        avatar = avatar.crop((left, top, left + TARGET, top + TARGET))
    except:
        avatar = Image.new("RGBA", (TARGET, TARGET), (100, 100, 100, 255))

    if player.get("prime_level") == 8 and app.state.prime8_frame:
        try:
            frame = app.state.prime8_frame.resize(avatar.size, Image.LANCZOS)
            avatar = Image.alpha_composite(avatar, frame)
        except:
            pass

    prime_img = app.state.prime_images.get(player.get("prime_level", 0))
    if prime_img:
        try:
            badge_size = 70
            badge = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
            x_pos = avatar.width - badge_size - 10
            y_pos = 10
            avatar.paste(badge, (x_pos, y_pos), badge)
        except:
            pass

    banner = bytes_to_image(banner_bytes)
    try:
        w, h = banner.size
        if w > 100 and h > 100:
            banner = banner.rotate(3, expand=True)
            w, h = banner.size
            l = w * BANNER_START_X
            t = h * BANNER_START_Y
            r = w * BANNER_END_X
            b = h * BANNER_END_Y
            banner = banner.crop((l, t, r, b))
        w, h = banner.size
        new_w = int(TARGET * (w / h) * 2) if h else 800
        banner = banner.resize((new_w, TARGET), Image.LANCZOS)
    except:
        banner = Image.new("RGBA", (800, TARGET), (100, 100, 100, 255))

    final_w = TARGET + banner.width
    combined = Image.new("RGBA", (final_w, TARGET), (0, 0, 0, 255))
    combined.paste(avatar, (0, 0))
    combined.paste(banner, (TARGET, 0))
    draw = ImageDraw.Draw(combined)

    name_x = TARGET + 65
    max_width = banner.width - 100
    if max_width < 100:
        max_width = 300

    font_name = load_unicode_font(110)
    font_name_che = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_che = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)

    y = 40
    for line in wrap_text(player.get("name", "Unknown"), font_name, max_width):
        draw_text_stroked(draw, name_x, y, line, font_name, font_name_che, 4)
        y += 85
    y += 60
    if player.get("guild"):
        draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_che, 3)

    lvl_text = f"Lvl.{player.get('level', '0')}"
    try:
        bbox = draw.textbbox((0, 0), lvl_text, font=font_level)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([final_w - w - 60, TARGET - h - 50, final_w, TARGET], fill="black")
        draw.text((final_w - w - 30, TARGET - h - 40), lvl_text, font=font_level, fill="white")
    except:
        pass

    img_io = io.BytesIO()
    combined.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

def generate_outfit_image(outfit_data: Dict[str, Any]) -> io.BytesIO:
    if not os.path.exists(OUTFIT_BACKGROUND):
        raise FileNotFoundError(f"Missing {OUTFIT_BACKGROUND}")
    canvas = Image.open(OUTFIT_BACKGROUND).convert("RGBA")
    slots = {
        "mask": outfit_data.get("mask"), "shirt": outfit_data.get("shirt"),
        "pants": outfit_data.get("pants"), "shoes": outfit_data.get("shoes"),
        "emote": outfit_data.get("emote"), "armor": outfit_data.get("armor"),
        "weapon": outfit_data.get("weapon"), "pet": outfit_data.get("pet"),
        "character": outfit_data.get("character", DEFAULT_AVATAR_ID)
    }
    for slot, item_id in slots.items():
        if not item_id:
            continue
        if slot == "character":
            img = fetch_icon(item_id, size=CHARACTER_RENDER_SIZE, is_character=True)
            if img:
                w, h = img.size
                cx = canvas.width // 2
                by = canvas.height - 20
                pos = (cx - w // 2, by - h)
        else:
            img = fetch_icon(item_id)
            if img:
                pos = HEX_POSITIONS.get(slot)
        if img and pos:
            canvas.paste(img, pos, img)
    img_io = io.BytesIO()
    canvas.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

# ================= JWT Functions (Original Working Method) =================
def get_access_token(uid: str, password: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    headers = {
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "100067.connect.garena.com",
        "User-Agent": "GarenaMSDK/4.0.39(SM-A325M;Android 13;en;HK;)"
    }
    body = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": HEX_KEY,
        "client_id": "100067"
    }
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=30, verify=False)
        if resp.status_code != 200:
            return None, None, None, f"HTTP {resp.status_code}"
        data = resp.json()
        if "open_id" not in data or "access_token" not in data:
            return None, None, None, "Invalid response"
        open_id = data["open_id"]
        access_token = data["access_token"]
        keystream = [0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,
                     0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,
                     0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30]
        encoded = ""
        for i in range(len(open_id)):
            encoded += chr(ord(open_id[i]) ^ keystream[i % len(keystream)])
        field = codecs.decode(''.join(c if 32 <= ord(c) <= 126 else f'\\u{ord(c):04x}' for c in encoded),
                              'unicode_escape').encode('latin1')
        return access_token, open_id, field, None
    except Exception as e:
        return None, None, None, str(e)[:50]

def major_login(access_token: str, open_id: str, region: str) -> Optional[Dict[str, str]]:
    lang = REGION_LANG.get(region.upper(), "en")
    payload_parts = [
        b'\x1a\x132025-08-30 05:19:21"\tfree fire(\x01:\x081.114.13B2Android OS 9 / API-28 (PI/rel.cjw.20220518.114133)J\x08HandheldR\nATM MobilsZ\x04WIFI`\xb6\nh\xee\x05r\x03300z\x1fARMv7 VFPv3 NEON VMH | 2400 | 2\x80\x01\xc9\x0f\x8a\x01\x0fAdreno (TM) 640\x92\x01\rOpenGL ES 3.2\x9a\x01+Google|dfa4ab4b-9dc4-454e-8065-e70c733fa53f\xa2\x01\x0e105.235.139.91\xaa\x01\x02',
        lang.encode("ascii"),
        b'\xb2\x01 1d8ec0240ede109973f3321b9354b44d\xba\x01\x014\xc2\x01\x08Handheld\xca\x01\x10Asus ASUS_I005DA\xea\x01@afcfbf13334be42036e4f742c80b956344bed760ac91b3aff9b607a610ab4390\xf0\x01\x01\xca\x02\nATM Mobils\xd2\x02\x04WIFI\xca\x03 7428b253defc164018c604a1ebbfebdf\xe0\x03\xa8\x81\x02\xe8\x03\xf6\xe5\x01\xf0\x03\xaf\x13\xf8\x03\x84\x07\x80\x04\xe7\xf0\x01\x88\x04\xa8\x81\x02\x90\x04\xe7\xf0\x01\x98\x04\xa8\x81\x02\xc8\x04\x01\xd2\x04=/data/app/com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg==/lib/arm\xe0\x04\x01\xea\x04_2087f61c19f57f2af4e7feff0b24d9d9|/data/app/com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg==/base.apk\xf0\x04\x03\xf8\x04\x01\x8a\x05\x0232\x9a\x05\n2019118692\xb2\x05\tOpenGLES2\xb8\x05\xff\x7f\xc0\x05\x04\xe0\x05\xf3F\xea\x05\x07android\xf2\x05pKqsHT5ZLWrYljNb5Vqh//yFRlaPHSO9NWSQsVvOmdhEEn7W+VHNUK+Q+fduA3ptNrGB0Ll0LRz3WW0jOwesLj6aiU7sZ40p8BfUE/FI/jzSTwRe2\xf8\x05\xfb\xe4\x06\x88\x06\x01\x90\x06\x01\x9a\x06\x014\xa2\x06\x014\xb2\x06"GQ@O\x00\x0e^\x00D\x06UA\x0ePM\r\x13hZ\x07T\x06\x0cm\\V\x0ejYV;\x0bU5'
    ]
    payload = b''.join(payload_parts)
    if region.upper() in ["ME", "TH"]:
        url = "https://loginbp.common.ggbluefox.com/MajorLogin"
    else:
        url = "https://loginbp.ggblueshark.com/MajorLogin"

    headers = {
        "Accept-Encoding": "gzip",
        "Authorization": "Bearer",
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "loginbp.ggblueshark.com" if region.upper() not in ["ME","TH"] else "loginbp.common.ggbluefox.com",
        "ReleaseVersion": "OB53",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_I005DA Build/PI)",
        "X-GA": "v1 1",
        "X-Unity-Version": "2018.4.11f1"
    }
    data = payload.replace(b'afcfbf13334be42036e4f742c80b956344bed760ac91b3aff9b607a610ab4390', access_token.encode())
    data = data.replace(b'1d8ec0240ede109973f3321b9354b44d', open_id.encode())
    encrypted = encrypt_api(data.hex())
    try:
        resp = requests.post(url, headers=headers, data=bytes.fromhex(encrypted), verify=False, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 10:
            jwt_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.?[a-zA-Z0-9\-_]+)', resp.text)
            if jwt_match:
                jwt_token = jwt_match.group(1)
                parts = jwt_token.split('.')
                if len(parts) >= 2:
                    payload_part = parts[1]
                    padding = 4 - len(payload_part) % 4
                    if padding != 4:
                        payload_part += '=' * padding
                    decoded = base64.urlsafe_b64decode(payload_part)
                    data = json.loads(decoded)
                    account_id = data.get('account_id') or data.get('external_id')
                    if account_id:
                        return {"jwt_token": jwt_token, "account_id": str(account_id)}
        return None
    except Exception:
        return None

def detect_region(uid: str, password: str) -> str:
    access_token, open_id, field, err = get_access_token(uid, password)
    if not access_token:
        return "BR"
    for region in ALL_REGIONS:
        result = major_login(access_token, open_id, region)
        if result and result.get("jwt_token"):
            return region
        time.sleep(0.3)
    return "BR"

def encrypt_api(plain_hex: str) -> str:
    plain = bytes.fromhex(plain_hex)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(plain, AES.block_size)).hex()

def generate_jwt_sync(uid: str, password: str, region: str = None) -> Dict[str, Any]:
    result = {
        "uid": uid,
        "timestamp": datetime.now().isoformat(),
        "success": False,
        "access_token": None,
        "open_id": None,
        "jwt_token": None,
        "account_id": None,
        "region_used": None,
        "error": None
    }
    if not region or region.upper() == "AUTO":
        region = detect_region(uid, password)
    result["region_used"] = region
    access_token, open_id, field, err = get_access_token(uid, password)
    if not access_token:
        result["error"] = f"Access token failed: {err}"
        return result
    result["access_token"] = access_token
    result["open_id"] = open_id
    login_result = major_login(access_token, open_id, region)
    if not login_result:
        result["error"] = "Major login failed"
        return result
    result["jwt_token"] = login_result["jwt_token"]
    result["account_id"] = login_result["account_id"]
    result["success"] = True
    return result

# ================= Level Helper =================
def get_exp_for_level(level: int) -> int:
    return LEVELS.get(str(level), 0)

def calculate_level_progress(current_exp: int, current_level: int) -> Optional[Dict]:
    if current_level >= 100:
        return {
            "current_level": 100,
            "current_exp": current_exp,
            "exp_for_current_level": LEVELS["100"],
            "exp_for_next_level": LEVELS["100"],
            "exp_needed": 0,
            "exp_needed_for_100": 0,
            "progress_percentage": 100
        }
    exp_for_current = get_exp_for_level(current_level)
    exp_for_next = get_exp_for_level(current_level + 1)
    exp_for_100 = get_exp_for_level(100)
    if exp_for_next == 0 or exp_for_current == 0:
        return None
    exp_needed = exp_for_next - current_exp
    exp_needed_for_100 = exp_for_100 - current_exp
    exp_in_current_level = current_exp - exp_for_current
    exp_range_for_level = exp_for_next - exp_for_current
    if exp_range_for_level > 0:
        progress_percentage = min(100, max(0, (exp_in_current_level / exp_range_for_level) * 100))
    else:
        progress_percentage = 0
    return {
        "current_level": current_level,
        "current_exp": current_exp,
        "exp_for_current_level": exp_for_current,
        "exp_for_next_level": exp_for_next,
        "exp_needed": exp_needed,
        "exp_needed_for_100": exp_needed_for_100,
        "progress_percentage": round(progress_percentage, 1)
    }

# ================= FastAPI App =================
app = FastAPI(title="FF Ultimate API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    app.state.prime_images = {}
    for lvl, path in PRIME_FILES.items():
        if os.path.exists(path):
            try:
                app.state.prime_images[lvl] = Image.open(path).convert("RGBA")
                logger.info(f"Loaded {path}")
            except Exception as e:
                logger.warning(f"Failed {path}: {e}")
    app.state.prime8_frame = None
    if os.path.exists(PRIME8_FRAME_FILE):
        try:
            app.state.prime8_frame = Image.open(PRIME8_FRAME_FILE).convert("RGBA")
            logger.info(f"Loaded {PRIME8_FRAME_FILE}")
        except Exception as e:
            logger.warning(f"Failed {PRIME8_FRAME_FILE}: {e}")
    app.state.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    app.state.thread_pool = ThreadPoolExecutor(max_workers=4)
    app.state.outfit_available = os.path.exists(OUTFIT_BACKGROUND)
    if not app.state.outfit_available:
        logger.warning(f"Outfit background missing: {OUTFIT_BACKGROUND}")
    yield
    await app.state.client.aclose()
    app.state.thread_pool.shutdown()
    logger.info("Shutdown complete")

app.router.lifespan_context = lifespan

# ================= Root =================
@app.get("/")
async def root():
    return {
        "endpoints": {
            "/": "This help",
            "/health": "Health check",
            "/player-info": "Raw player data",
            "/banner": "Generate banner",
            "/random-banner": "Random prime level banner",
            "/batch-banners": "ZIP of banners",
            "/outfit": "Real outfit",
            "/outfit?...": "Custom outfit overrides",
            "/prime-levels": "List prime levels",
            "/eat-access": "EAT token → access token",
            "/access-jwt": "Access token → JWT",
            "/token": "UID/password → JWT",
            "/token/batch": "Batch JWT",
            "/level": "Level progress info",
            "/bancheck": "Ban status check",
            "/region": "Get region by UID"
        },
        "docs": "/docs"
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/player-info")
async def player_info(uid: str = Query(...)):
    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(502, "External API error")
    return JSONResponse(content=resp.json())

@app.get("/banner")
async def banner(
    uid: str = Query(...),
    bannerid: Optional[str] = None,
    avatarid: Optional[str] = None,
    primelevel: Optional[int] = Query(None, ge=0, le=8),
    guildname: Optional[str] = None,
    playername: Optional[str] = None,
    level: Optional[str] = None
):
    real = await fetch_real_player_data(uid)
    final = {
        "name": clean_text(playername) if playername is not None else real["name"],
        "level": level if level is not None else real["level"],
        "guild": clean_text(guildname) if guildname is not None else real["guild"],
        "headPic": avatarid if avatarid is not None else real["headPic"],
        "banner_id": bannerid if bannerid is not None else real["banner_id"],
        "prime_level": primelevel if primelevel is not None else real["prime_level"]
    }
    ava, ban = await asyncio.gather(fetch_image_bytes(final["headPic"]), fetch_image_bytes(final["banner_id"]))
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, final)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/random-banner")
async def random_banner(uid: str = Query(...)):
    real = await fetch_real_player_data(uid)
    final = {
        "name": real["name"],
        "level": real["level"],
        "guild": real["guild"],
        "headPic": real["headPic"],
        "banner_id": real["banner_id"],
        "prime_level": random.randint(0, 8)
    }
    ava, ban = await asyncio.gather(fetch_image_bytes(final["headPic"]), fetch_image_bytes(final["banner_id"]))
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, final)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/batch-banners")
async def batch_banners(uids: str = Query(...)):
    uid_list = [u.strip() for u in uids.split(",") if u.strip()]
    if not uid_list:
        raise HTTPException(400, "No UIDs")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for uid in uid_list:
            try:
                real = await fetch_real_player_data(uid)
                ava, ban = await asyncio.gather(fetch_image_bytes(real["headPic"]), fetch_image_bytes(real["banner_id"]))
                loop = asyncio.get_event_loop()
                img = await loop.run_in_executor(app.state.thread_pool, generate_banner_image, ava, ban, real)
                zf.writestr(f"banner_{uid}.png", img.getvalue())
            except Exception as e:
                logger.warning(f"Failed {uid}: {e}")
    zip_buf.seek(0)
    return Response(content=zip_buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=banners.zip"})

@app.get("/outfit")
async def outfit(
    uid: str = Query(...),
    head: Optional[str] = None,
    mask: Optional[str] = None,
    top: Optional[str] = None,
    pants: Optional[str] = None,
    shoes: Optional[str] = None,
    faceprint: Optional[str] = None,
    paint: Optional[str] = None,
    weapon: Optional[str] = None,
    pet: Optional[str] = None
):
    if not app.state.outfit_available:
        raise HTTPException(503, f"Missing background file: {OUTFIT_BACKGROUND}")
    real = await fetch_real_player_data(uid)
    clothes = real.get("clothes", [])
    data = {
        "character": head or real.get("character"),
        "mask": mask or (clothes[0] if len(clothes) > 0 else None),
        "shirt": top or (clothes[1] if len(clothes) > 1 else None),
        "pants": pants or (clothes[2] if len(clothes) > 2 else None),
        "shoes": shoes or (clothes[3] if len(clothes) > 3 else None),
        "emote": faceprint or (clothes[4] if len(clothes) > 4 else None),
        "armor": paint or (clothes[5] if len(clothes) > 5 else None),
        "weapon": weapon or real.get("weapon"),
        "pet": pet or real.get("pet")
    }
    loop = asyncio.get_event_loop()
    img = await loop.run_in_executor(app.state.thread_pool, generate_outfit_image, data)
    return Response(content=img.getvalue(), media_type="image/png")

@app.get("/prime-levels")
async def prime_levels():
    return {"levels": [{"level": i, "badge": f"prime{i}.png", "frame": "prime8frame.png" if i == 8 else None} for i in range(9)]}

@app.get("/eat-access")
async def eat_access(eat: str = Query(...)):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        response = await client.get(EAT_TARGET_URL, params={'access_token': eat})
        while response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get('Location')
            if not location:
                break
            if not location.startswith(('http://', 'https://')):
                base = urlparse(EAT_TARGET_URL)
                location = base._replace(path=location).geturl()
            response = await client.get(location)
        final_url = str(response.url)
        parsed = urlparse(final_url)
        query_params = parse_qs(parsed.query)
        access_token = query_params.get('access_token', [None])[0]
        if not access_token:
            raise HTTPException(500, "Access token not found")
        response_text = f"""OWNER:RIZER
TELEGRAM:@sulav_codex_ff
TELEGRAM CHANNEL:@sulav_don2
THANKS FOR USING!
access token= {access_token}"""
        return Response(content=response_text, media_type="text/plain")

@app.get("/access-jwt")
async def access_jwt_endpoint(access_token: str = Query(...), open_id: Optional[str] = Query(None)):
    cache_key = f"accjwt:{access_token}:{open_id}"
    if cache_key in jwt_cache and jwt_cache[cache_key]["expires"] > time.time():
        return JSONResponse(content=jwt_cache[cache_key]["data"])
    if not open_id:
        try:
            insp_resp = requests.get(f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}", timeout=10)
            if insp_resp.status_code == 200:
                open_id = insp_resp.json().get("open_id")
        except:
            pass
    if not open_id:
        raise HTTPException(400, "Could not determine open_id. Provide open_id parameter.")
    for region in ALL_REGIONS:
        result = major_login(access_token, open_id, region)
        if result and result.get("jwt_token"):
            jwt_token = result["jwt_token"]
            try:
                parts = jwt_token.split('.')
                payload_part = parts[1]
                padding = 4 - len(payload_part) % 4
                if padding != 4:
                    payload_part += '=' * padding
                decoded = base64.urlsafe_b64decode(payload_part)
                payload = json.loads(decoded)
            except:
                payload = {}
            resp_data = {
                "success": True,
                "jwt": jwt_token,
                "account_id": result.get("account_id"),
                "open_id": open_id,
                "access_token": access_token,
                "region_used": region,
                "decoded_payload": payload
            }
            jwt_cache[cache_key] = {"data": resp_data, "expires": time.time() + 300}
            return JSONResponse(content=resp_data)
    raise HTTPException(401, "Could not generate JWT. Invalid access token or open_id.")

@app.get("/token")
async def token_endpoint(uid: str = Query(...), password: str = Query(...), region: Optional[str] = Query("AUTO")):
    cache_key = f"uidpwd:{uid}:{password}:{region}"
    if cache_key in token_cache and token_cache[cache_key]["expires"] > time.time():
        return JSONResponse(content=token_cache[cache_key]["data"])
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(app.state.thread_pool, generate_jwt_sync, uid, password, region)
    if result.get("success"):
        token_cache[cache_key] = {"data": result, "expires": time.time() + 300}
        return JSONResponse(content=result)
    else:
        raise HTTPException(401, result.get("error", "Token generation failed"))

@app.post("/token/batch")
async def batch_token(file: UploadFile = File(...), region: Optional[str] = Query("AUTO")):
    content = await file.read()
    try:
        accounts = json.loads(content.decode('utf-8'))
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {e}")
    if not isinstance(accounts, list):
        raise HTTPException(400, "Expected a JSON array of accounts")
    results = []
    for acc in accounts:
        uid = acc.get('uid') or acc.get('guestUid')
        pwd = acc.get('password') or acc.get('guestPass')
        if not uid or not pwd:
            results.append({"error": "Missing uid or password", "input": acc})
            continue
        res = generate_jwt_sync(str(uid), str(pwd), region)
        results.append(res)
        await asyncio.sleep(random.uniform(0.5, 1.5))
    return JSONResponse(content={"total": len(results), "results": results})

@app.get("/level")
async def get_level_info(uid: str = Query(...)):
    try:
        player = await fetch_real_player_data(uid)
        current_level = int(player["level"])
        current_exp = player.get("exp", 0)
        progress = calculate_level_progress(current_exp, current_level)
        if not progress:
            raise HTTPException(500, "Could not calculate level progress")
        return {
            "success": True,
            "uid": uid,
            "nickname": player["name"],
            "current_level": progress["current_level"],
            "current_exp": progress["current_exp"],
            "exp_for_current_level": progress["exp_for_current_level"],
            "exp_for_next_level": progress["exp_for_next_level"],
            "exp_needed": progress["exp_needed"],
            "exp_needed_for_100": progress["exp_needed_for_100"],
            "progress_percentage": progress["progress_percentage"],
            "level_100_exp": LEVELS["100"]
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/bancheck")
async def check_ban_status(uid: str = Query(...)):
    if not uid.isdigit() or not (8 <= len(uid) <= 11):
        return {
            "error": True,
            "message": "Invalid UID (must be 8-11 digits)",
            "status": "error"
        }
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://ff.garena.com/api/antihack/check_banned?lang=en&uid={uid}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
                'Accept': 'application/json, text/plain, */*',
                'authority': 'ff.garena.com',
                'x-requested-with': 'B6FksShzIgjfrYImLpTsadjS86sddhFH',
            }
            resp = await client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                period = data.get("period")
                is_banned = period != 0 if period is not None else False
                reason = data.get("reason") or data.get("desc") or ""
                return {
                    "error": False,
                    "success": True,
                    "uid": uid,
                    "status": "Banned ❌" if is_banned else "Not Banned ✅",
                    "status_code": "banned" if is_banned else "not_banned",
                    "is_banned": is_banned,
                    "period": period,
                    "reason": reason,
                    "timestamp": data.get("timestamp"),
                    "raw_data": data,
                    "gif": "https://files.catbox.moe/lns4kb.gif" if is_banned else "https://files.catbox.moe/7to40v.gif"
                }
            else:
                return {"error": True, "success": False, "message": f"API Error ({resp.status_code})", "status": "api_error"}
    except Exception as e:
        return {"error": True, "success": False, "message": str(e), "status": "error"}

@app.get("/region")
async def get_region(uid: str = Query(...)):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-MM,en-US;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://topup.pk",
        "Referer": "https://topup.pk/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; RMX5070) AppleWebKit/537.36",
        "X-Requested-With": "mark.via.gp",
        "Cookie": "source=mb; region=PK; mspid2=13c49fb51ece78886ebf7108a4907756; language=en; session_key=hq02g63z3zjcumm76mafcooitj7nc79y",
    }
    payload = {"app_id": 100067, "login_id": str(uid)}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post("https://topup.pk/api/auth/player_id_login", json=payload, headers=headers, timeout=15)
            data = resp.json() if resp.text else {}
    except Exception:
        data = {}
    return {
        "uid": uid,
        "nickname": data.get("nickname", ""),
        "region": data.get("region", ""),
        "credits": {
            "developer": "t.me/sulav_codex_ff",
            "main_channel": "t.me/sulavxapis",
            "group": "t.me/sulavxlikes"
        }
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)