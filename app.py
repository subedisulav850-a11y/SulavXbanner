import io
import os
import re
import sys
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
import jwt

# Import compiled protobuf modules
import my_pb2
import output_pb2

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

# Crypto constants
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

# Token caches
token_cache = {}
jwt_cache = {}

# ================= LEVELS Dictionary (for /level) =================
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

def get_exp_for_level(level: int) -> int:
    """Get EXP needed for a specific level (1-100)."""
    return LEVELS.get(str(level), 0)

def calculate_level_progress(current_exp: int, current_level: int) -> Optional[Dict]:
    """Calculate progress to next level."""
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
        "exp": basic.get("exp", 0)  # added for /level
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

# ================= JWT / Access Token Functions =================
def encrypt_aes(plaintext: bytes) -> bytes:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(plaintext, AES.block_size))

def build_game_data(open_id: str, access_token: str, platform_type: int) -> bytes:
    gd = my_pb2.GameData()
    gd.timestamp = "2024-12-05 18:15:32"
    gd.game_name = "free fire"
    gd.game_version = 1
    gd.version_code = "1.108.3"
    gd.os_info = "Android OS 9 / API-28 (PI/rel.cjw.20220518.114133)"
    gd.device_type = "Handheld"
    gd.network_provider = "Verizon Wireless"
    gd.connection_type = "WIFI"
    gd.screen_width = 1280
    gd.screen_height = 960
    gd.dpi = "240"
    gd.cpu_info = "ARMv7 VFPv3 NEON VMH | 2400 | 4"
    gd.total_ram = 5951
    gd.gpu_name = "Adreno (TM) 640"
    gd.gpu_version = "OpenGL ES 3.0"
    gd.user_id = "Google|74b585a9-0268-4ad3-8f36-ef41d2e53610"
    gd.ip_address = "172.190.111.97"
    gd.language = "en"
    gd.open_id = open_id
    gd.access_token = access_token
    gd.platform_type = platform_type
    gd.field_99 = str(platform_type)
    gd.field_100 = str(platform_type)
    return gd.SerializeToString()

async def fetch_open_id_from_access_token(access_token: str) -> Optional[str]:
    import requests
    # First try inspect endpoint
    inspect_url = f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}"
    try:
        resp = requests.get(inspect_url, timeout=10)
        if resp.status_code == 200 and resp.json().get("open_id"):
            return resp.json()["open_id"]
    except:
        pass
    # Fallback: use shop2game API
    try:
        uid_url = "https://prod-api.reward.ff.garena.com/redemption/api/auth/inspect_token/"
        headers = {"access-token": access_token, "User-Agent": "Mozilla/5.0"}
        uid_resp = requests.get(uid_url, headers=headers, timeout=10)
        uid_data = uid_resp.json()
        uid = uid_data.get("uid")
        if not uid:
            return None
        openid_url = "https://shop2game.com/api/auth/player_id_login"
        payload = {"app_id": 100067, "login_id": str(uid)}
        openid_resp = requests.post(openid_url, json=payload, timeout=10)
        return openid_resp.json().get("open_id")
    except Exception as e:
        logger.warning(f"OpenID fetch failed: {e}")
        return None

async def access_to_jwt(access_token: str, open_id: Optional[str] = None) -> Dict[str, Any]:
    if not open_id:
        open_id = await fetch_open_id_from_access_token(access_token)
        if not open_id:
            return {"error": "Could not retrieve open_id", "success": False}
    platforms = [8, 3, 4, 6]
    for pt in platforms:
        try:
            game_data_bytes = build_game_data(open_id, access_token, pt)
            encrypted = encrypt_aes(game_data_bytes)
            import requests
            resp = requests.post(
                "https://loginbp.ggblueshark.com/MajorLogin",
                data=encrypted,
                headers={
                    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
                    "Content-Type": "application/octet-stream",
                    "X-Unity-Version": "2018.4.11f1",
                    "X-GA": "v1 1",
                    "ReleaseVersion": "OB53"
                },
                timeout=10
            )
            if resp.status_code == 200:
                garena = output_pb2.Garena_420()
                garena.ParseFromString(resp.content)
                if garena.token:
                    try:
                        decoded = jwt.decode(garena.token, options={"verify_signature": False})
                    except:
                        decoded = {}
                    return {
                        "success": True,
                        "platform_type_used": pt,
                        "token": garena.token,
                        "account_id": decoded.get("account_id"),
                        "account_name": decoded.get("nickname"),
                        "open_id": open_id,
                        "access_token": access_token,
                        "platform": decoded.get("external_type"),
                        "region": decoded.get("lock_region"),
                        "url": garena.url if hasattr(garena, 'url') else None,
                        "timestamp": garena.timestamp if hasattr(garena, 'timestamp') else None
                    }
        except Exception as e:
            logger.warning(f"Platform {pt} failed: {e}")
    return {"error": "No valid platform found", "success": False}

async def uid_password_to_jwt(uid: str, password: str) -> Dict[str, Any]:
    import requests
    oauth_url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    payload = {
        'uid': uid,
        'password': password,
        'response_type': "token",
        'client_type': "2",
        'client_secret': "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        'client_id': "100067"
    }
    headers = {'User-Agent': "GarenaMSDK/4.0.19P9(SM-M526B ;Android 13;pt;BR;)"}
    try:
        oauth_resp = requests.post(oauth_url, data=payload, headers=headers, timeout=10)
        if oauth_resp.status_code != 200:
            return {"error": "OAuth failed", "success": False}
        oauth_data = oauth_resp.json()
        access_token = oauth_data.get("access_token")
        open_id = oauth_data.get("open_id")
        if not access_token or not open_id:
            return {"error": "Missing access_token or open_id", "success": False}
        return await access_to_jwt(access_token, open_id)
    except Exception as e:
        return {"error": str(e), "success": False}

# ================= New Endpoint: /level =================
@app.get("/level")
async def get_level_info(uid: str = Query(...)):
    """Get level progress information for a player."""
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

# ================= New Endpoint: /bancheck =================
@app.get("/bancheck")
async def check_ban_status(uid: str = Query(...)):
    """Check if a UID is banned."""
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

# ================= New Endpoint: /region =================
@app.get("/region")
async def get_region(uid: str = Query(...)):
    """Get region information for a UID."""
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
            "developer": "t.me/danger_ff_like",
            "main_channel": "t.me/freefirelikesdanger",
            "api_channel": "t.me/dangerfreefireapis"
        }
    }

# ================= Existing API Endpoints =================
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
    result = await access_to_jwt(access_token, open_id)
    if result.get("success"):
        jwt_cache[cache_key] = {"data": result, "expires": time.time() + 300}
        return JSONResponse(content=result)
    else:
        raise HTTPException(401, result.get("error", "JWT generation failed"))

@app.get("/token")
async def token_endpoint(uid: str = Query(...), password: str = Query(...)):
    cache_key = f"uidpwd:{uid}:{password}"
    if cache_key in token_cache and token_cache[cache_key]["expires"] > time.time():
        return JSONResponse(content=token_cache[cache_key]["data"])
    result = await uid_password_to_jwt(uid, password)
    if result.get("success"):
        token_cache[cache_key] = {"data": result, "expires": time.time() + 300}
        return JSONResponse(content=result)
    else:
        raise HTTPException(401, result.get("error", "Token generation failed"))

@app.post("/token/batch")
async def batch_token(file: UploadFile = File(...)):
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
        res = await uid_password_to_jwt(str(uid), str(pwd))
        results.append(res)
        await asyncio.sleep(random.uniform(0.5, 1.5))
    return JSONResponse(content={"total": len(results), "results": results})

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

app = FastAPI(lifespan=lifespan, title="FF Ultimate API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)