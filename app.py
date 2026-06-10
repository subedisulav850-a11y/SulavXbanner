import io
import os
import re
import asyncio
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor

# ================= CONFIGURATION =================
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0  
AVATAR_SHIFT_X = 0  
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

FONT_FILE = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"
PRIME_FILES = {i: f"prime{i}.png" for i in range(0, 9)}
PRIME8_FRAME_FILE = "prime8frame.png"

# Real API endpoint
INFO_API_URL = "https://info.killersharmabot.online/player-info"
# CDN URL as requested
CDN_URL = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"

# ================= Lifespan =================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.prime_images = load_prime_images()
    app.state.prime8_frame = load_prime8_frame()
    app.state.client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20.0,
        follow_redirects=True
    )
    app.state.thread_pool = ThreadPoolExecutor(max_workers=4)
    yield
    await app.state.client.aclose()
    app.state.thread_pool.shutdown()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Helper Functions =================
def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove invisible Unicode characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b\uFEFF\uf8ff]', '', str(text))
    return ' '.join(text.split())

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Wrap text into two lines maximum, splitting at spaces."""
    words = text.split()
    if not words:
        return [text]
    # Try to put first part on line 1, rest on line 2
    for i in range(1, len(words)):
        line1 = ' '.join(words[:i])
        line2 = ' '.join(words[i:])
        bbox1 = font.getbbox(line1)
        bbox2 = font.getbbox(line2)
        if (bbox1[2] - bbox1[0] <= max_width) and (bbox2[2] - bbox2[0] <= max_width):
            return [line1, line2]
    # If cannot split nicely, return original as single line
    return [text]

def load_unicode_font(size: int, font_file: str = FONT_FILE):
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except:
        pass
    return ImageFont.load_default()

def is_cherokee(c: str) -> bool:
    return 0x13A0 <= ord(c) <= 0x13FF or 0xAB70 <= ord(c) <= 0xABBF

def draw_text_stroked(draw, x, y, text, f_main, f_alt, stroke=3):
    cx = x
    for ch in text:
        font = f_alt if is_cherokee(ch) else f_main
        for dx in range(-stroke, stroke+1):
            for dy in range(-stroke, stroke+1):
                draw.text((cx+dx, y+dy), ch, font=font, fill="black")
        draw.text((cx, y), ch, font=font, fill="white")
        cx += font.getlength(ch)

def load_prime_images() -> Dict[int, Optional[Image.Image]]:
    images = {}
    for lvl, path in PRIME_FILES.items():
        if os.path.exists(path):
            try:
                images[lvl] = Image.open(path).convert("RGBA")
                print(f"Loaded {path}")
            except Exception as e:
                print(f"Failed {path}: {e}")
                images[lvl] = None
        else:
            images[lvl] = None
    return images

def load_prime8_frame() -> Optional[Image.Image]:
    if os.path.exists(PRIME8_FRAME_FILE):
        try:
            img = Image.open(PRIME8_FRAME_FILE).convert("RGBA")
            print(f"Loaded {PRIME8_FRAME_FILE}")
            return img
        except Exception as e:
            print(f"Failed {PRIME8_FRAME_FILE}: {e}")
    return None

async def fetch_image_bytes(item_id: str) -> Optional[bytes]:
    if not item_id or str(item_id).lower() in ("0", "none", "null", ""):
        return None
    url = f"{CDN_URL}/{item_id}.png"
    try:
        resp = await app.state.client.get(url)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"Error fetching {item_id}: {e}")
    return None

def bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except:
            pass
    # Fallback grey square
    return Image.new("RGBA", (400, 400), (200, 200, 200, 255))

# ================= Data Extraction =================
def extract_player_data(data: Dict[str, Any]) -> Dict[str, Any]:
    basic = data.get("basicInfo", {})
    clan = data.get("clanBasicInfo", {})
    profile = data.get("profileInfo", {})

    name = clean_text(basic.get("nickname", "Unknown"))
    level = str(basic.get("level", 0))
    guild = clean_text(clan.get("clanName", ""))
    avatar_id = str(profile.get("avatarId") or basic.get("headPic", ""))
    banner_id = str(basic.get("bannerId", ""))
    prime_level = int(basic.get("primeLevel", {}).get("level", 0))

    # Creation date (for prime 8 layout)
    create_at = basic.get("createAt", "")
    since_text = ""
    if create_at and str(create_at).isdigit():
        try:
            dt = datetime.fromtimestamp(int(create_at))
            since_text = dt.strftime("Since %d %b %Y")
        except:
            since_text = str(create_at)

    country = clean_text(basic.get("region", ""))

    print(f"Extracted: {name}, Lv.{level}, Guild:{guild}, Avatar:{avatar_id}, Banner:{banner_id}, Prime:{prime_level}, Since:{since_text}, Country:{country}")
    return {
        "name": name, "level": level, "guild": guild,
        "avatar_id": avatar_id, "banner_id": banner_id,
        "prime_level": prime_level, "since_text": since_text, "country": country
    }

# ================= Image Processing =================
def process_banner_image(avatar_bytes: Optional[bytes],
                         banner_bytes: Optional[bytes],
                         player: Dict[str, Any]) -> io.BytesIO:
    avatar_img = bytes_to_image(avatar_bytes)
    banner_img = bytes_to_image(banner_bytes)

    TARGET_HEIGHT = 400

    # Avatar crop
    zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
    avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.LANCZOS)
    left = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_X
    top = (zoom_size - TARGET_HEIGHT) // 2 - AVATAR_SHIFT_Y
    avatar_img = avatar_img.crop((left, top, left + TARGET_HEIGHT, top + TARGET_HEIGHT))

    # Prime 8 frame
    if player["prime_level"] == 8 and app.state.prime8_frame is not None:
        frame_resized = app.state.prime8_frame.resize(avatar_img.size, Image.LANCZOS)
        avatar_img = Image.alpha_composite(avatar_img, frame_resized)

    # Banner crop & resize
    b_w, b_h = banner_img.size
    if b_w > 100 and b_h > 100:
        banner_img = banner_img.rotate(3, expand=True)
        bw_rot, bh_rot = banner_img.size
        crop_left = bw_rot * BANNER_START_X
        crop_top = bh_rot * BANNER_START_Y
        crop_right = bw_rot * BANNER_END_X
        crop_bottom = bh_rot * BANNER_END_Y
        banner_img = banner_img.crop((crop_left, crop_top, crop_right, crop_bottom))

    b_w, b_h = banner_img.size
    aspect = (b_w / b_h) if b_h > 0 else 2.0
    new_banner_w = int(TARGET_HEIGHT * aspect * 2)
    banner_img = banner_img.resize((new_banner_w, TARGET_HEIGHT), Image.LANCZOS)

    final_w = TARGET_HEIGHT + new_banner_w
    combined = Image.new("RGBA", (final_w, TARGET_HEIGHT), (0, 0, 0, 255))
    combined.paste(avatar_img, (0, 0))
    combined.paste(banner_img, (TARGET_HEIGHT, 0))
    draw = ImageDraw.Draw(combined)

    name_x = TARGET_HEIGHT + 65
    max_text_width = new_banner_w - 100

    # Fonts
    font_name = load_unicode_font(110)
    font_name_cherokee = load_unicode_font(110, FONT_CHEROKEE)
    font_guild = load_unicode_font(80)
    font_guild_cherokee = load_unicode_font(80, FONT_CHEROKEE)
    font_level = load_unicode_font(50)

    # ----- Standard layout (prime 0-7) -----
    if player["prime_level"] != 8:
        name_lines = wrap_text(player["name"], font_name, max_text_width)
        y = 40
        for line in name_lines:
            draw_text_stroked(draw, name_x, y, line, font_name, font_name_cherokee, 4)
            y += 85
        if player["guild"]:
            draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_cherokee, 3)

    # ----- Prime level 8 special layout (frame + extra fields) -----
    else:
        font_since = load_unicode_font(65)
        font_since_cherokee = load_unicode_font(65, FONT_CHEROKEE)
        font_country = load_unicode_font(85)
        font_country_cherokee = load_unicode_font(85, FONT_CHEROKEE)
        y = 40
        if player["guild"]:
            draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_cherokee, 3)
            y += 70
        if player["since_text"]:
            draw_text_stroked(draw, name_x, y, player["since_text"], font_since, font_since_cherokee, 2)
            y += 55
        y += 20
        name_lines = wrap_text(player["name"], font_name, max_text_width)
        for line in name_lines:
            draw_text_stroked(draw, name_x, y, line, font_name, font_name_cherokee, 4)
            y += 85
        if player["guild"]:
            draw_text_stroked(draw, name_x, y, player["guild"], font_guild, font_guild_cherokee, 3)
            y += 70
        if player["country"]:
            draw_text_stroked(draw, name_x, y, player["country"], font_country, font_country_cherokee, 3)

    # Level badge (bottom right)
    lvl_text = f"Lvl.{player['level']}"
    bbox = draw.textbbox((0, 0), lvl_text, font=font_level)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.rectangle([final_w - w - 60, TARGET_HEIGHT - h - 50, final_w, TARGET_HEIGHT], fill="black")
    draw.text((final_w - w - 30, TARGET_HEIGHT - h - 40), lvl_text, font=font_level, fill="white")

    # Prime badge (bottom left)
    prime_img = app.state.prime_images.get(player["prime_level"])
    if prime_img is not None:
        badge_size = 80
        prime_resized = prime_img.resize((badge_size, badge_size), Image.LANCZOS)
        combined.paste(prime_resized, (15, TARGET_HEIGHT - badge_size - 15), prime_resized)

    img_io = io.BytesIO()
    combined.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

# ================= API Endpoints =================
@app.get("/profile")
async def get_banner(uid: str):
    if not uid:
        raise HTTPException(status_code=400, detail="UID required")

    resp = await app.state.client.get(f"{INFO_API_URL}?uid={uid}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Info API Error")
    data = resp.json()

    player = extract_player_data(data)

    avatar_task = fetch_image_bytes(player["avatar_id"])
    banner_task = fetch_image_bytes(player["banner_id"])
    avatar_bytes, banner_bytes = await asyncio.gather(avatar_task, banner_task)

    loop = asyncio.get_event_loop()
    img_io = await loop.run_in_executor(
        app.state.thread_pool,
        process_banner_image,
        avatar_bytes,
        banner_bytes,
        player
    )

    return Response(content=img_io.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)