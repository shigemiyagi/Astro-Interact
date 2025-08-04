# main.py
# Astro-Interact バックエンドAPI - 最終修正版

import datetime
import logging
import math
from typing import Dict, List, Optional

import swisseph as swe
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from geopy.geocoders import Nominatim
from pydantic import BaseModel, Field

# --- 0. ロギング設定 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# --- A. 天文計算用の定数 ---
PLANET_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN,
    "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON, "Mean North Node": swe.MEAN_NODE,
    "Mean Black Moon Lilith": swe.MEAN_APOG,
}
HELIO_PLANET_IDS = {
    "Earth": swe.EARTH, "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN,
    "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON,
}
CHART_TYPE_ABBREVIATIONS = {
    "natal": 'N', "progressed": 'P', "transit": 'T', 
    "solarArc": 'SA', "solarReturn": 'SR', "heliocentric": 'H'
}
SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
ASPECTS = {"Conjunction": 0, "Opposition": 180, "Trine": 120, "Square": 90, "Sextile": 60}
ORBS = {
    "major_luminary": {"Conjunction": 8, "Opposition": 8, "Trine": 7, "Square": 7, "Sextile": 5},
    "default":        {"Conjunction": 6, "Opposition": 6, "Trine": 5, "Square": 5, "Sextile": 4},
}

swe.set_ephe_path('./ephe')

# --- 1. Pydanticモデル定義 (変更なし) ---
class NatalChartRequest(BaseModel):
    date: str; time: str; location: str
class EventChartRequest(BaseModel):
    date: str
class SolarReturnRequest(BaseModel):
    year: int; location: str
class EventsRequest(BaseModel):
    progressed: EventChartRequest; transit: EventChartRequest
    solarArc: EventChartRequest; solarReturn: SolarReturnRequest
    heliocentric: EventChartRequest
class HoroscopeRequest(BaseModel):
    natal: NatalChartRequest; events: EventsRequest
class PlanetData(BaseModel):
    sign: str; degree: float; isRetro: bool
    position: float; house: Optional[int] = None
class ChartData(BaseModel):
    planets: Dict[str, PlanetData]; houses: Optional[List[float]] = None
class AspectData(BaseModel):
    p1: str; p1Sign: str; p2: str; p2Sign: str
    aspect: str; orb: float; state: str
class HoroscopeResponse(BaseModel):
    natal: ChartData; progressed: ChartData; transit: ChartData
    solarArc: ChartData; solarReturn: ChartData; heliocentric: ChartData
    aspects: Dict[str, List[AspectData]]

# --- 2. FastAPIアプリケーションの初期化 ---
app = FastAPI(title="Astro-Interact API", version="1.0.0")

origins = [
    "null", "http://localhost", "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 3. ヘルパー関数 (変更なし) ---
def get_lat_lon_from_location(location: str) -> (float, float):
    logging.info(f"ジオコーディング開始: {location}")
    try:
        geolocator = Nominatim(user_agent="astro_interact_app")
        loc = geolocator.geocode(location)
        if loc:
            lat, lon = loc.latitude, loc.longitude
            logging.info(f"ジオコーディング完了: {location} -> ({lat}, {lon})")
            return lat, lon
        logging.warning(f"ジオコーディング失敗: {location}")
        return 0.0, 0.0
    except Exception as e:
        logging.exception(f"ジオコーディング中にエラーが発生: {e}")
        return 0.0, 0.0

def get_julian_day(date_str: str, time_str: str = "12:00:00") -> float:
    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    jd_et, jd_ut = swe.utc_to_jd(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 1)
    return jd_ut

# --- 4. 天文計算ロジック ---
def calculate_planets(jd: float, planet_ids: dict, flags: int) -> Dict[str, PlanetData]:
    planets = {}
    for name, p_id in planet_ids.items():
        pos_data, ret_code = swe.calc_ut(jd, p_id, flags)
        
        longitude = pos_data[0]
        is_retro = False
        if len(pos_data) > 3:
            is_retro = pos_data[3] < 0
            
        planets[name] = PlanetData(
            sign=SIGNS[int(longitude / 30)],
            degree=longitude % 30,
            isRetro=is_retro,
            position=longitude,
        )
    return planets

def calculate_houses(jd: float, lat: float, lon: float) -> (List[float], float):
    house_cusps_tuple, ascmc_tuple = swe.houses(jd, lat, lon, b'P')
    return list(house_cusps_tuple), ascmc_tuple[0]

def assign_houses_to_planets(planets: Dict[str, PlanetData], house_cusps: List[float]):
    for planet in planets.values():
        for i in range(12):
            cusp1, cusp2 = house_cusps[i], house_cusps[(i + 1) % 12]
            pos = planet.position
            if (cusp1 < cusp2 and cusp1 <= pos < cusp2) or \
               (cusp1 > cusp2 and (cusp1 <= pos < 360 or 0 <= pos < cusp2)):
                planet.house = i + 1
                break
    return planets

def calculate_aspects(chart1: ChartData, chart2: ChartData) -> List[AspectData]:
    aspect_list = []
    planets1, planets2 = chart1.planets, chart2.planets
    p1_keys, p2_keys = list(planets1.keys()), list(planets2.keys())

    for i in range(len(p1_keys)):
        for j in range(len(p2_keys)):
            if chart1 is chart2 and i >= j: continue
            p1_name, p2_name = p1_keys[i], p2_keys[j]
            p1, p2 = planets1[p1_name], planets2[p2_name]

            angle_diff = abs(p1.position - p2.position)
            if angle_diff > 180: angle_diff = 360 - angle_diff

            for aspect_name, aspect_degree in ASPECTS.items():
                is_luminary = "Sun" in [p1_name, p2_name] or "Moon" in [p1_name, p2_name]
                orb_rules = ORBS["major_luminary"] if is_luminary else ORBS["default"]
                orb = orb_rules[aspect_name]

                if abs(angle_diff - aspect_degree) < orb:
                    aspect_list.append(AspectData(
                        p1=p1_name, p1Sign=p1.sign, p2=p2_name, p2Sign=p2.sign,
                        aspect=aspect_name, orb=abs(angle_diff - aspect_degree), state="Applying"
                    ))
                    break
    return aspect_list

def calculate_all_charts(request: HoroscopeRequest) -> HoroscopeResponse:
    logging.info("ホロスコープ計算処理を開始...")
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    charts = {}

    natal_info = request.natal
    lat, lon = get_lat_lon_from_location(natal_info.location)
    jd_natal = get_julian_day(natal_info.date, natal_info.time)
    natal_planets = calculate_planets(jd_natal, PLANET_IDS, flags)
    natal_houses, asc = calculate_houses(jd_natal, lat, lon)
    natal_planets = assign_houses_to_planets(natal_planets, natal_houses)
    charts["natal"] = ChartData(planets=natal_planets, houses=natal_houses)

    jd_transit = get_julian_day(request.events.transit.date)
    charts["transit"] = ChartData(planets=calculate_planets(jd_transit, PLANET_IDS, flags))

    natal_dt = datetime.datetime.strptime(f"{natal_info.date} {natal_info.time}", "%Y-%m-%d %H:%M:%S")
    prog_dt = datetime.datetime.strptime(request.events.progressed.date, "%Y-%m-%d")
    days_after_birth = (prog_dt - natal_dt.replace(hour=0, minute=0, second=0)).days
    jd_progressed = jd_natal + days_after_birth
    charts["progressed"] = ChartData(planets=calculate_planets(jd_progressed, PLANET_IDS, flags))

    solar_arc = (charts["progressed"].planets["Sun"].position - charts["natal"].planets["Sun"].position) % 360
    sa_planets = {}
    for name, p_data in natal_planets.items():
        new_pos = (p_data.position + solar_arc) % 360
        sa_planets[name] = PlanetData(
            sign=SIGNS[int(new_pos / 30)], degree=new_pos % 30,
            isRetro=p_data.isRetro, position=new_pos, house=p_data.house
        )
    charts["solarArc"] = ChartData(planets=sa_planets, houses=natal_houses)

    sr_info = request.events.solarReturn
    sr_lat, sr_lon = get_lat_lon_from_location(sr_info.location)
    
    # ★★★ 修正箇所 ★★★
    # 正しいライブラリ(pyswisseph)の正しい関数名 `swe.solret_ut` を使用
    ret_code, jd_solret, serr = swe.solret_ut(jd_natal, sr_info.year)
    if ret_code != 0:
        logging.error(f"ソーラーリターン計算失敗: {serr}")
        sr_planets, sr_houses = {}, []
    else:
        sr_planets = calculate_planets(jd_solret, PLANET_IDS, flags)
        sr_houses, sr_asc = calculate_houses(jd_solret, sr_lat, sr_lon)
        sr_planets = assign_houses_to_planets(sr_planets, sr_houses)
    charts["solarReturn"] = ChartData(planets=sr_planets, houses=sr_houses)

    jd_helio = get_julian_day(request.events.heliocentric.date)
    helio_flags = flags | swe.FLG_HELCTR
    charts["heliocentric"] = ChartData(planets=calculate_planets(jd_helio, HELIO_PLANET_IDS, helio_flags))

    logging.info("アスペクト計算を開始...")
    aspects = {}
    chart_names = list(charts.keys())
    for i in range(len(chart_names)):
        for j in range(i, len(chart_names)):
            c1_name, c2_name = chart_names[i], chart_names[j]
            if ('helio' in c1_name and 'helio' not in c2_name) or \
               ('helio' not in c1_name and 'helio' in c2_name):
                continue
            
            key = f"{CHART_TYPE_ABBREVIATIONS[c1_name]}-{CHART_TYPE_ABBREVIATIONS[c2_name]}"
            aspects[key] = calculate_aspects(charts[c1_name], charts[c2_name])

    response = HoroscopeResponse(
        natal=charts["natal"], progressed=charts["progressed"], transit=charts["transit"],
        solarArc=charts["solarArc"], solarReturn=charts["solarReturn"], heliocentric=charts["heliocentric"],
        aspects=aspects
    )
    logging.info("ホロスコープ計算処理が正常に完了。")
    return response

# --- 5. APIエンドポイントの実装 (変更なし) ---
@app.post("/horoscope", response_model=HoroscopeResponse)
async def create_horoscope(request: HoroscopeRequest):
    logging.info(f"リクエスト受信: /horoscope, natal_date={request.natal.date}")
    try:
        return calculate_all_charts(request)
    except Exception as e:
        logging.exception("ホロスコープ計算中に予期せぬエラーが発生しました。")
        raise HTTPException(status_code=500, detail="サーバー内部でエラーが発生しました。")
