import numpy as np
import pandas as pd
import logging
import geopandas as gpd
import tkinter as tk
import time
import json
import os
import sys
from pathlib import Path
import traceback
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from enum import Enum
from shapely.geometry import Point
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from tkinter import filedialog
from pyproj import Transformer
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from decimal import Decimal, ROUND_HALF_UP
from report import generate_all_wells_excel_reports, generate_all_wells_charts
import tkinter as tk
from tkinter import filedialog
from datetime import datetime

'''
各參數單位：
    統體單位重 : (t/m^3)
    SPT上下限深度 : (m) 
    FC : (%)
    PI : (%)
    土層深度、土層厚度、土層中點、分析點 : (m)
    sigma_v : (t/m^2)

'''


def setup_django_paths():
    """設定 Django 路徑 - 簡化版本"""
    try:
        from django.conf import settings
        # 在 Django 環境中，不需要特別設定路徑
        pass
    except ImportError:
        # 非 Django 環境的處理
        pass
# 在檔案開頭呼叫
setup_django_paths()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']  # 解決中文顯示問題

# 常數設定
g = 9.81  # 重力加速度 (m/s²)

#讀取檔案
def get_input_file(input_file_path=None, show_gui=True):
    if input_file_path is None and show_gui:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilename(
                title="請選擇輸入的 CSV 檔案",
                filetypes=[("CSV 檔案", "*.csv")]
            )
            root.destroy()
            print("正在讀取資料...")
        except ImportError:
            # Django 環境中不使用 GUI
            raise ValueError("在網頁環境中必須提供 input_file_path")

        if not file_path:
            print("未選擇檔案，程式結束。")
            return None
    elif input_file_path is not None:
        file_path = input_file_path
        if not file_path:
            print("檔案讀取失敗")
            return None
    else:
        raise ValueError("必須提供 input_file_path 或設定 show_gui=True")

    return file_path

# 新增：取得統體單位重單位選擇
def get_unit_weight_unit():
    """取得使用者選擇的統體單位重單位"""
    print("\n=== 統體單位重單位設定 ===")
    print("請選擇您的資料中統體單位重/統體密度的單位：")
    print("1. t/m³ (公噸/立方公尺)")
    print("2. kN/m³ (千牛頓/立方公尺)")
    
    while True:
        try:
            choice = input("請輸入選項 (1 或 2，預設為 1): ").strip()
            
            if choice == "" or choice == "1":
                print("✅ 選擇：t/m³ (無需轉換)")
                return "t/m3", 1.0
            elif choice == "2":
                print("✅ 選擇：kN/m³ (將除以 9.81 轉換為 t/m³)")
                return "kN/m3", 1.0/9.81
            else:
                print("❌ 請輸入有效選項 (1 或 2)")
                continue
                
        except Exception as e:
            print(f"❌ 輸入錯誤：{e}")
            continue

# 支援的座標系統清單
AVAILABLE_CRS = {
    "1": {"name": "TWD97 台灣本島", "epsg": "EPSG:3826"},
    "2": {"name": "TWD97 澎湖", "epsg": "EPSG:3825"},
    "3": {"name": "WGS84 經緯度", "epsg": "EPSG:4326"}
}

#讀取.json
def load_json_file(file_path: str) -> Optional[Dict[str, Any]]:
    """安全載入JSON檔案"""
    if not os.path.exists(file_path):
        logger.warning(f"找不到檔案：{file_path}")
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"成功載入檔案：{file_path}")
            return data
    except Exception as e:
        logger.error(f"載入檔案失敗 {file_path}: {e}")
        return None

def get_parameter_file_path(filename):
    """取得參數檔案的絕對路徑"""
    try:
        from django.conf import settings
        return settings.BASE_DIR.parent / "參數" / filename
    except ImportError:
        # 非 Django 環境
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent
        return project_root / "參數" / filename

taiwan_seismic_data = load_json_file(str(get_parameter_file_path("taiwan_seismic_data.json"))) or {}
general_zone_seismic_coefficients = load_json_file(str(get_parameter_file_path("general_zone_seismic_coefficient.json"))) or {}
taipei_basin_zones = load_json_file(str(get_parameter_file_path("taipei_basin_zone.json"))) or {}
fault_distance_parameters = load_json_file(str(get_parameter_file_path("斷層參數.json"))) or {}

# 台北盆地微分區係數
taipei_basin_seismic_coefficients = {
    '臺北一區': {
        'SD_S': 0.6,
        'SM_S': 0.8,
        'T0_D': 1.60,
        'T0_M': 1.60
    },
    '臺北二區': {
        'SD_S': 0.6,
        'SM_S': 0.8,
        'T0_D': 1.30,
        'T0_M': 1.30
    },
    '臺北三區': {
        'SD_S': 0.6,
        'SM_S': 0.8,
        'T0_D': 1.05,
        'T0_M': 1.05
    }
}

# 城市與地震規模 Mw 對照表
city_mw_mapping = {
    "基隆市": 7.3, "新北市": 7.3, "臺北市": 7.3, "宜蘭縣": 7.3, "花蓮縣": 7.3, "台東縣": 7.3,
    "桃園市": 7.1, "台中市": 7.1, "彰化縣": 7.1, "南投縣": 7.1, "雲林縣": 7.1,
    "嘉義縣": 7.1, "台南市": 7.1, "高雄市": 7.1,
    "新竹縣": 6.9, "苗栗縣": 6.9, "屏東縣": 6.9,
    "澎湖縣": 6.7, "金門縣": 6.7, "馬祖縣": 6.7
}

#地震規模修正
earthquake_mw_adjustments = {
    "Design": 0.0,     # 設計地震：使用基準Mw，不調整
    "MidEq": -0.2,     # 中小地震：基準Mw - 0.2
    "MaxEq": +0.2      # 最大地震：基準Mw + 0.2
}

#格式化結果到指定小數位數（修正浮點誤差)
def format_result(value, decimal_places=3):
    """格式化結果到指定小數位數（修正浮點誤差）"""
    if pd.isna(value) or value == "-" or value == np.nan:
        return "-"
    try:
        if isinstance(value, float):
            value_dec = Decimal.from_float(value)
        else:
            value_dec = Decimal(str(value))

        quantize_str = "1." + "0" * decimal_places
        return float(value_dec.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, ArithmeticError):
        return "-"

# 將 TW97 坐標轉換為 WGS84（經緯度）
def tw97_to_wgs84(x, y):
    transformer = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)
    return lat, lon

# 根據經緯度取得城市名稱
def get_city_from_coordinates(lat, lon):
    try:
        geolocator = Nominatim(user_agent="tw97_geoapi")
        location = geolocator.reverse((lat, lon), language='zh-TW')
        if location and location.raw.get('address'):
            address = location.raw['address']
            return address.get('city') or address.get('county') or address.get('town')
        return None
    except Exception as e:
        print(f"地理編碼錯誤：{e}")
        return None

# 根據座標取得城市名稱與地震規模 Mw
def generate_earthquake_parameters_from_tw97(x_tw97, y_tw97):
    lat, lon = tw97_to_wgs84(x_tw97, y_tw97)
    city = get_city_from_coordinates(lat, lon)
    
    print("🔴 WARNING: generate_earthquake_parameters_from_tw97 被呼叫了！")
    print("🔴 呼叫堆疊：")
    traceback.print_stack()

    if city is None:
        print(f"座標 ({x_tw97}, {y_tw97}) 查無城市")
        return "未知城市", 0  

    mw = city_mw_mapping.get(city)
    if mw is None:
        print(f"城市：{city}，但查表無對應 Mw")
        return city, 0

    print(f"座標 ({x_tw97}, {y_tw97}) 城市：{city}，推估地震規模 Mw = {mw}")
    return city, mw

# 計算不同地震情境的Mw值
def get_scenario_mw(base_mw, scenario):
    """根據地震情境調整Mw值 - 使用加減法"""
    adjustment = earthquake_mw_adjustments.get(scenario, 0.0)
    adjusted_mw = base_mw + adjustment
    
    # 確保Mw在合理範圍內 (5.0 ~ 8.5)
    adjusted_mw = max(5.0, min(8.5, adjusted_mw))
    # 修正浮點數精度問題
    adjusted_mw = round(adjusted_mw, 1)

    return adjusted_mw



# 判定符號
def parse_numeric_value(value):
    """解析數值，處理 > 符號和空白"""
    if pd.isna(value) or value == '' or value is None:
        return None
    
    value_str = str(value).strip()
    
    if value_str == '':
        return None
    
    # 處理 > 符號
    if value_str.startswith('>'):
        try:
            return float(value_str[1:].strip())
        except (ValueError, TypeError):
            return None
    
    # 直接轉換數字
    try:
        return float(value_str)
    except (ValueError, TypeError):
        return None

#標準化地址名稱，移除常見的地址變體
def normalize_address_name(name: str) -> str:
    """標準化地址名稱，移除常見的地址變體"""
    if not name:
        return ""
    
    # 移除常見的地址後綴和變體
    name = name.strip()
    
    # 處理縣市名稱
    city_variants = {
        '台北市': '臺北市',
        '台中市': '臺中市',
        '台南市': '臺南市',
        '台東縣': '臺東縣',
    }
    
    for variant, standard in city_variants.items():
        if variant in name:
            name = name.replace(variant, standard)
    
    return name

#台北微分區搜尋系統
def find_taipei_basin_zone(city: str, district: str, village: str = None) -> Optional[str]:
    """尋找台北盆地微分區 - 修正版本"""
    logger.info(f"尋找台北盆地微分區：{city}-{district}-{village}")
    
    # 標準化地址名稱
    city = normalize_address_name(city)
    district = normalize_address_name(district)
    if village:
        village = normalize_address_name(village)
    
    # 只處理台北市和新北市
    if city not in ['臺北市', '新北市']:
        logger.info(f"{city} 不在台北盆地範圍內")
        return None
    
    # 檢查該縣市是否在台北盆地資料中
    if city not in taipei_basin_zones:
        logger.warning(f"在台北盆地資料中找不到 {city}")
        logger.info(f"可用的縣市名稱：{list(taipei_basin_zones.keys())}")
        return None
    
    # 取得該縣市的資料
    city_data = taipei_basin_zones[city]
    logger.info(f"該縣市的可用區域：{list(city_data.keys())}")
    
    # 移除「區」字後綴進行比對
    district_key = district.replace('區', '') if district.endswith('區') else district
    
    # 在該縣市的行政區中尋找匹配 - 更靈活的匹配方式
    matching_districts = []
    for dist_key in city_data.keys():
        # 嘗試多種匹配方式
        if (district_key in dist_key or 
            dist_key in district_key or
            district in dist_key or
            dist_key in district or
            district_key == dist_key.replace('區', '') or
            dist_key == district_key.replace('區', '')):
            matching_districts.append(dist_key)
    
    if not matching_districts:
        logger.warning(f"在台北盆地資料中找不到 {city} 的 {district}")
        logger.info(f"可用的區域名稱：{list(city_data.keys())}")
        return None
    
    # 使用最匹配的區
    best_match_district = min(matching_districts, key=lambda x: abs(len(x) - len(district_key)))
    district_zones = city_data[best_match_district]
    
    logger.info(f"找到匹配的區域：{city}-{best_match_district}，可用微分區：{list(district_zones.keys())}")
    
    # 如果有里的資訊，嘗試找到對應的微分區
    if village:
        for zone_name, village_list in district_zones.items():
            # 檢查里名是否在村里清單中
            if village in village_list:
                logger.info(f"找到精確匹配的微分區：{zone_name}")
                return zone_name
            
            # 也嘗試移除「里」字的匹配
            village_without_suffix = village.replace('里', '') if village.endswith('里') else village
            for v in village_list:
                v_without_suffix = v.replace('里', '') if v.endswith('里') else v
                if village_without_suffix == v_without_suffix:
                    logger.info(f"找到匹配的微分區（移除里字後）：{zone_name}")
                    return zone_name
        
        logger.warning(f"在 {city}-{best_match_district} 的微分區中找不到里 {village}")
        # 列出該區所有微分區和里供參考
        for zone_name, village_list in district_zones.items():
            logger.info(f"  {zone_name}: {len(village_list)}個里 - {village_list[:5]}...")
    
    # 如果沒有里的資訊或找不到精確匹配，回傳第一個微分區
    default_zone = list(district_zones.keys())[0]
    logger.info(f"使用預設微分區：{default_zone}")
    return default_zone

#利用逆地理編碼搜尋地區
def enhanced_geocoding(lat: float, lon: float) -> Dict[str, str]:
    """增強的逆地理編碼，嘗試多種方式解析地址"""
    geolocator = Nominatim(user_agent="tw-seismic-query", timeout=10)
    
    try:
        # 第一次嘗試：標準逆地理編碼
        location = geolocator.reverse((lat, lon), language="zh-TW", exactly_one=True)
        time.sleep(1)  # 避免 API 限制
        
        if not location:
            raise Exception("無法取得地理位置資訊")
        
        logger.info(f"地理查詢結果：{location.address}")
        
        # 解析地址
        addr = location.raw.get("address", {})
        full_address = location.address
        
        # 先取得縣市資訊
        city = None
        for field in ["state", "county", "province", "city"]:
            if addr.get(field):
                city = normalize_address_name(addr[field])
                break
        
        # 特別處理桃園市和臺南市
        if city in ["桃園市", "臺南市"]:
            return parse_taoyuan_tainan_address(full_address, addr, city)
        
        # 其他縣市的原有處理邏輯
        # 嘗試多種欄位來取得區鄉鎮資訊
        district = None
        for field in ["suburb", "town", "city_district", "municipality", "neighbourhood"]:
            if addr.get(field):
                district = normalize_address_name(addr[field])
                break
        
        # 取得里的資訊
        village = None
        for field in ["neighbourhood", "hamlet", "quarter"]:
            if addr.get(field):
                village = normalize_address_name(addr[field])
                break
        
        return {
            "city": city,
            "district": district,
            "village": village,
            "full_address": full_address
        }
    
    except Exception as e:
        logger.error(f"地理查詢失敗：{e}")
        raise Exception(f"地理查詢服務錯誤：{e}")

#優化台南和桃園搜尋問題
def parse_taoyuan_tainan_address(full_address: str, addr: dict, city: str) -> Dict[str, str]:
    """專門解析桃園市和臺南市的地址"""
    logger.info(f"使用專門解析器處理 {city} 地址")
    
    # 方法1：從完整地址字串解析
    district, village = parse_address_string(full_address, city)
    
    if district:
        logger.info(f"從地址字串解析成功：{city} -> {district} -> {village}")
        return {
            "city": city,
            "district": district,
            "village": village,
            "full_address": full_address
        }
    
    # 方法2：從API回傳的結構化資料解析
    district, village = parse_structured_address(addr, city)
    
    logger.info(f"從結構化資料解析：{city} -> {district} -> {village}")
    return {
        "city": city,
        "district": district,
        "village": village,
        "full_address": full_address
    }

#從完整地址字串解析區和里
def parse_address_string(full_address: str, city: str) -> Tuple[Optional[str], Optional[str]]:
    """從完整地址字串解析區和里"""
    import re
    
    try:
        # 移除縣市名稱，專注於後面的部分
        address_parts = full_address.replace(city, "").strip()
        
        # 使用正則表達式找出區和里
        # 模式：尋找「某某區」和「某某里」
        district_pattern = r'([^,，\s]+區)'
        village_pattern = r'([^,，\s]+里)'
        
        district_matches = re.findall(district_pattern, address_parts)
        village_matches = re.findall(village_pattern, address_parts)
        
        district = district_matches[0] if district_matches else None
        village = village_matches[0] if village_matches else None
        
        logger.info(f"地址字串解析結果：區={district}, 里={village}")
        
        # 驗證結果的合理性
        if district and village:
            # 確保區名不是里名
            if not district.endswith('里'):
                return district, village
        
        return None, None
        
    except Exception as e:
        logger.warning(f"地址字串解析失敗：{e}")
        return None, None

#針對台南和桃園問題解決
def parse_structured_address(addr: dict, city: str) -> Tuple[Optional[str], Optional[str]]:
    """從結構化地址資料解析區和里"""
    district = None
    village = None
    
    # 優先順序調整：先找區級行政單位
    # 桃園市和臺南市都是直轄市，下轄區
    district_fields = ["suburb", "city_district", "town", "municipality"]
    village_fields = ["neighbourhood", "hamlet", "quarter"]
    
    # 找區
    for field in district_fields:
        if addr.get(field):
            candidate = normalize_address_name(addr[field])
            # 確保是區而不是里
            if candidate.endswith('區') and not candidate.endswith('里'):
                district = candidate
                logger.info(f"從 {field} 欄位找到區：{district}")
                break
    
    # 找里
    for field in village_fields:
        if addr.get(field):
            candidate = normalize_address_name(addr[field])
            # 確保是里而不是區，且不是已經被識別為區的名稱
            if candidate.endswith('里') and candidate != district:
                village = candidate
                logger.info(f"從 {field} 欄位找到里：{village}")
                break
    
    # 如果仍然沒找到區，嘗試從所有欄位中找尋
    if not district:
        logger.warning(f"未在標準欄位找到區，嘗試所有欄位")
        for field, value in addr.items():
            if value and isinstance(value, str):
                candidate = normalize_address_name(value)
                if candidate.endswith('區') and not candidate.endswith('里'):
                    district = candidate
                    logger.info(f"從 {field} 欄位找到區：{district}")
                    break
    
    # 如果仍然沒找到里，嘗試從所有欄位中找尋
    if not village:
        logger.warning(f"未在標準欄位找到里，嘗試所有欄位")
        for field, value in addr.items():
            if value and isinstance(value, str):
                candidate = normalize_address_name(value)
                if candidate.endswith('里') and candidate != district:
                    village = candidate
                    logger.info(f"從 {field} 欄位找到里：{village}")
                    break
    
    logger.info(f"結構化資料解析結果：區={district}, 里={village}")
    
    # 最後驗證：確保區和里不相同
    if district == village:
        logger.warning(f"區和里相同({district})，清除里的資訊")
        village = None
    
    return district, village


###斷層查詢    
def get_fault_based_parameters(fault_name: str, distance_km: float, city: str, district: str) -> Optional[Dict[str, Any]]:
    """
    根據斷層距離取得地震參數 - 加入內插功能
    
    Args:
        fault_name: 斷層名稱
        distance_km: 距離斷層的距離(公里)
        city: 縣市名稱
        district: 鄉鎮區名稱
    
    Returns:
        斷層相關的地震參數，如果 r>14 或找不到則回傳 None
    """
    # 條件：若 r>14 則不需要查詢與斷層相關的參數
    if distance_km > 14:
        logger.info(f"距離 {distance_km:.2f} km > 14 km，跳過斷層參數查詢")
        return None
    
    # 尋找匹配的斷層記錄
    matching_records = []
    for record in fault_distance_parameters:
        record_fault_name = record["斷層名稱"]
        
        # 模糊匹配斷層名稱
        if (fault_name in record_fault_name or 
            record_fault_name in fault_name or
            fault_name.replace('斷層', '') in record_fault_name or
            record_fault_name.replace('斷層', '') in fault_name):
            
            # 檢查對應鄉鎮是否匹配
            target_areas = record["對應鄉鎮"]
            if city in target_areas and district in target_areas:
                matching_records.append(record)
    
    if not matching_records:
        logger.warning(f"在斷層參數中找不到 {fault_name} 對應 {city}-{district} 的記錄")
        return None
    
    # 將距離範圍轉換為數值進行內插
    distance_ranges = {
        "<=1": 1.0,     # 修改：使用 1.0 作為 <=1 的代表值
        "3": 3.0,
        "5": 5.0,
        "7": 7.0,
        "9": 9.0,
        "11": 11.0,
        "13": 13.0,
        ">=14": 14.0    # 使用 14.0 作為 >=14 的代表值
    }
    
    # 建立距離-參數對應表
    distance_params = {}
    for record in matching_records:
        r_range = record["r"]
        if r_range in distance_ranges:
            dist_key = distance_ranges[r_range]
            distance_params[dist_key] = {
                "SDS": float(record["SDS"]),
                "SD1": float(record["SD1"]),
                "SMS": float(record["SMS"]),
                "SM1": float(record["SM1"]),
                "原始範圍": r_range
            }
    
    if not distance_params:
        logger.warning(f"沒有可用的距離參數進行內插")
        return None
    
    # 排序距離點
    sorted_distances = sorted(distance_params.keys())
    
    # 如果實際距離小於等於最小距離，使用最小距離的參數
    if distance_km <= sorted_distances[0]:
        closest_dist = sorted_distances[0]
        params = distance_params[closest_dist]
        logger.info(f"使用最小距離參數: r={params['原始範圍']}")
        
        return {
            "斷層名稱": fault_name,
            "r": params['原始範圍'],
            "對應鄉鎮": f"[{city}] {district}",
            "SDS": params["SDS"],
            "SD1": params["SD1"],
            "SMS": params["SMS"],
            "SM1": params["SM1"],
            "內插方法": "使用最小距離"
        }
    
    # 如果實際距離大於等於最大距離，使用最大距離的參數
    if distance_km >= sorted_distances[-1]:
        closest_dist = sorted_distances[-1]
        params = distance_params[closest_dist]
        logger.info(f"使用最大距離參數: r={params['原始範圍']}")
        
        return {
            "斷層名稱": fault_name,
            "r": params['原始範圍'],
            "對應鄉鎮": f"[{city}] {district}",
            "SDS": params["SDS"],
            "SD1": params["SD1"],
            "SMS": params["SMS"],
            "SM1": params["SM1"],
            "內插方法": "使用最大距離"
        }
    
    # 找到實際距離所在的區間進行線性內插
    for i in range(len(sorted_distances) - 1):
        lower_dist = sorted_distances[i]
        upper_dist = sorted_distances[i + 1]
        
        if lower_dist <= distance_km <= upper_dist:
            lower_params = distance_params[lower_dist]
            upper_params = distance_params[upper_dist]
            
            # 計算內插權重
            if upper_dist == lower_dist:
                # 避免除零錯誤
                weight = 0.5
            else:
                weight = (distance_km - lower_dist) / (upper_dist - lower_dist)
            
            # 線性內插各參數
            interpolated_params = {}
            for param in ["SDS", "SD1", "SMS", "SM1"]:
                lower_val = lower_params[param]
                upper_val = upper_params[param]
                interpolated_val = lower_val + weight * (upper_val - lower_val)
                interpolated_params[param] = round(interpolated_val, 3)
            
            logger.info(f"線性內插: {lower_params['原始範圍']} ({lower_dist}) ← {distance_km:.2f} → {upper_params['原始範圍']} ({upper_dist}), 權重={weight:.3f}")
            
            return {
                "斷層名稱": fault_name,
                "r": f"{lower_params['原始範圍']}~{upper_params['原始範圍']}",
                "對應鄉鎮": f"[{city}] {district}",
                "SDS": interpolated_params["SDS"],
                "SD1": interpolated_params["SD1"],
                "SMS": interpolated_params["SMS"],
                "SM1": interpolated_params["SM1"],
                "內插方法": f"線性內插 (權重={weight:.3f})",
                "內插範圍": f"{lower_params['原始範圍']} ← {distance_km:.2f}km → {upper_params['原始範圍']}",
                "下界參數": f"SDS={lower_params['SDS']}, SD1={lower_params['SD1']}, SMS={lower_params['SMS']}, SM1={lower_params['SM1']}",
                "上界參數": f"SDS={upper_params['SDS']}, SD1={upper_params['SD1']}, SMS={upper_params['SMS']}, SM1={upper_params['SM1']}"
            }
    
    logger.warning(f"找不到距離 {distance_km:.2f} km 對應的參數範圍")
    return None


def compute_distances_to_faults(x: float, y: float, source_epsg: str, faults_gdf: gpd.GeoDataFrame) -> dict:
    """
    計算點到各斷層線的最近距離
    針對地調所斷層資料格式優化
    """
    # 統一使用 TWD97 投影座標系統進行精確計算
    target_epsg = "EPSG:3826"
    
    # 步驟1: 將輸入座標轉換為 TWD97
    if source_epsg != target_epsg:
        transformer = Transformer.from_crs(source_epsg, target_epsg, always_xy=True)
        x_proj, y_proj = transformer.transform(x, y)
    else:
        x_proj, y_proj = x, y
    
    # 步驟2: 確保斷層資料也是 TWD97
    if faults_gdf.crs is None:
        logger.warning("斷層資料沒有座標系統資訊，假設為 TWD97")
        faults_proj = faults_gdf.copy()
    elif faults_gdf.crs.to_epsg() != 3826:
        logger.info(f"將斷層資料從 {faults_gdf.crs} 轉換為 TWD97")
        faults_proj = faults_gdf.to_crs(target_epsg)
    else:
        faults_proj = faults_gdf.copy()
    
    # 步驟3: 建立查詢點
    point = Point(x_proj, y_proj)
    
    # 步驟4: 根據地調所資料格式選擇正確的斷層名稱欄位
    name_col = None
    if 'FAULT_NAME' in faults_proj.columns:
        name_col = 'FAULT_NAME'
        logger.info("使用 FAULT_NAME 欄位作為斷層名稱")
    elif 'E_NAME' in faults_proj.columns:
        name_col = 'E_NAME'
        logger.info("使用 E_NAME 欄位作為斷層名稱")
    elif 'Fault_No_3' in faults_proj.columns:
        name_col = 'Fault_No_3'
        logger.info("使用 Fault_No_3 欄位作為斷層名稱")
    else:
        logger.warning("未找到適當的斷層名稱欄位")
        return {}
    
    # 步驟5: 計算距離並按斷層名稱分組
    fault_distances = {}
    
    for idx, row in faults_proj.iterrows():
        fault_geom = row.geometry
        
        # 計算點到線的最短距離（單位：公尺）
        distance_m = fault_geom.distance(point)
        distance_km = distance_m / 1000.0
        
        # 取得斷層名稱
        if name_col and pd.notna(row[name_col]):
            fault_name = str(row[name_col]).strip()
        else:
            fault_name = f"斷層_{idx+1}"
        
        # 如果該斷層已存在，保留較近的距離（因為斷層可能有多個線段）
        if fault_name in fault_distances:
            fault_distances[fault_name] = min(fault_distances[fault_name], distance_km)
        else:
            fault_distances[fault_name] = distance_km
    
    return fault_distances

#從檔案中的鑽孔座標獲取地震參數
def coordinate_search_from_file(x_tw97: float, y_tw97: float, use_fault_data: bool = False, fault_gdf=None) -> Optional[Dict[str, Any]]:
    """使用檔案中的TWD97座標進行座標搜尋"""
    try:
        print(f"正在查詢座標 ({x_tw97}, {y_tw97}) 的地震參數...")
        
        # 步驟1: 將 TWD97 座標轉換為 WGS84
        lat, lon = tw97_to_wgs84(x_tw97, y_tw97)
        print(f"  轉換為 WGS84: ({lat:.6f}, {lon:.6f})")
        
        # 步驟2: 使用增強地理編碼獲取地址資訊
        try:
            geo_info = enhanced_geocoding(lat, lon)  # 使用原有的函數
            city = geo_info.get('city')
            district = geo_info.get('district') 
            village = geo_info.get('village')
            
            print(f"  地理編碼結果: {city} - {district} - {village}")
            
            if not city:
                print(f"  無法獲取城市資訊")
                return None
                
        except Exception as e:
            print(f"  地理編碼失敗: {e}")
            return None
        
        # 步驟3: 新增斷層距離參數查詢 (最高優先順序)
        result = None
        
        if use_fault_data and fault_gdf is not None:
            try:
                print(f"  正在計算斷層距離...")
                # 修改：使用正確的函數呼叫方式
                distances = compute_distances_to_faults(x_tw97, y_tw97, "EPSG:3826", fault_gdf)
                
                if distances:
                    nearest_fault, min_distance = min(distances.items(), key=lambda item: item[1])
                    print(f"  最近斷層: {nearest_fault} ({min_distance:.2f} km)")
                    
                    # 如果距離≤14km，查詢斷層距離參數
                    if min_distance <= 14:
                        print(f"  查詢斷層距離參數...")
                        fault_params = get_fault_based_parameters(nearest_fault, min_distance, city, district)
                        if fault_params:
                            result = {
                                '縣市': city,
                                '鄉鎮/區': district,
                                '里': village or "",
                                '微分區': "",
                                'SDS': fault_params.get('SDS'),
                                'SMS': fault_params.get('SMS'),
                                'SD1': fault_params.get('SD1'),
                                'SM1': fault_params.get('SM1'),
                                '鄰近之斷層': f"{nearest_fault} ({min_distance:.2f} km)",
                                '資料來源': f'斷層距離參數 (r={fault_params.get("r", "")})'
                            }
                            print(f"  ✅ 使用斷層距離參數: r={fault_params.get('r')}")
                            return result
                        else:
                            print(f"  未找到對應的斷層距離參數")
                    else:
                        print(f"  距離 {min_distance:.2f}km > 14km，不使用斷層距離參數")
                else:
                    print(f"  未計算出斷層距離")
                        
            except Exception as e:
                print(f"  斷層距離參數查詢失敗: {e}")
        
        # 步驟4: 優先查詢台北盆地微分區
        if not result and city in ['臺北市', '新北市'] and district:
            taipei_zone = find_taipei_basin_zone(city, district, village)
            if taipei_zone:
                print(f"  找到台北盆地微分區: {taipei_zone}")
                coefficients = taipei_basin_seismic_coefficients.get(taipei_zone, {})
                result = {
                    '縣市': city,
                    '鄉鎮/區': district,
                    '里': village or "",
                    '微分區': taipei_zone,
                    'SDS': coefficients.get('SD_S'),  # 台北盆地使用SD_S
                    'SMS': coefficients.get('SM_S'),  # 台北盆地使用SM_S
                    'SD1': coefficients.get('SD1', None),
                    'SM1': coefficients.get('SM1', None),
                    '鄰近之斷層': "",
                    '資料來源': '台北盆地微分區'
                }
        
        # 步驟5: 如果沒有找到台北盆地資料，查詢一般震區資料
        if not result:
            print(f"  查詢一般震區資料...")
            # 查詢一般震區係數
            city_data = general_zone_seismic_coefficients.get(city, {})
            if city_data and district:
                district_data = city_data.get(district, {})
                if district_data and village:
                    village_data = district_data.get(village, {})
                    if village_data:
                        result = {
                            '縣市': city,
                            '鄉鎮/區': district,
                            '里': village,
                            '微分區': "",
                            'SDS': village_data.get('SDS'),
                            'SMS': village_data.get('SMS'),
                            'SD1': village_data.get('SD1'),
                            'SM1': village_data.get('SM1'),
                            '鄰近之斷層': village_data.get('鄰近之斷層', ""),
                            '資料來源': '一般震區資料'
                        }
        
        # 步驟6: 如果還是沒有找到，使用預設值
        if not result:
            print(f"  使用預設地震參數")
            result = {
                '縣市': city,
                '鄉鎮/區': district or "",
                '里': village or "",
                '微分區': "",
                'SDS': 0.8,  # 預設值
                'SMS': 1.0,  # 預設值
                'SD1': None,
                'SM1': None,
                '鄰近之斷層': "",
                '資料來源': '預設值'
            }
        
        # 步驟7: 添加斷層距離資訊 (不影響主要參數選擇)
        if use_fault_data and fault_gdf is not None and result:
            try:
                distances = compute_distances_to_faults(x_tw97, y_tw97, "EPSG:3826", fault_gdf)
                if distances:
                    nearest_fault, min_distance = min(distances.items(), key=lambda item: item[1])
                    original_fault = result.get("鄰近之斷層", "")
                    if original_fault and original_fault.strip():
                        result["鄰近之斷層"] = f"{original_fault} (最近斷層: {nearest_fault} {min_distance:.2f} km)"
                    else:
                        result["鄰近之斷層"] = f"{nearest_fault} ({min_distance:.2f} km)"
            except Exception as e:
                print(f"  計算斷層距離失敗: {e}")
        
        if result:
            print(f"  查詢成功：{result['縣市']} - {result['鄉鎮/區']}")
            if 'SDS' in result and 'SMS' in result:
                print(f"  SDS: {result['SDS']}, SMS: {result['SMS']}")
            return result
        else:
            print(f"  座標 ({x_tw97}, {y_tw97}) 查詢失敗")
            return None
            
    except Exception as e:
        logger.error(f"座標搜尋發生錯誤：{e}")
        print(f"座標搜尋錯誤：{e}")
        return None
def get_earthquake_parameters_from_wells(df: pd.DataFrame, use_fault_data: bool = False, fault_gdf=None) -> Dict[str, Dict[str, Any]]:
    """從檔案中的鑽孔座標獲取地震參數"""
    well_params = {}
    unique_wells_data = df.groupby('鑽孔編號')[['TWD97_X', 'TWD97_Y']].first()
    well_ids = unique_wells_data.index.tolist()
    
    print(f"\n=== 正在獲取 {len(well_ids)} 個鑽孔的地震參數 ===")
    
    for i, well_id in enumerate(well_ids, 1):
        print(f"\n進度 [{i}/{len(well_ids)}] 處理鑽孔：{well_id}")
        
        # 取得該鑽孔的座標
        well_data = df[df['鑽孔編號'] == well_id].iloc[0]
        x_tw97 = well_data['TWD97_X']
        y_tw97 = well_data['TWD97_Y']
        
        print(f"  TWD97座標：({x_tw97}, {y_tw97})")
        
        # 進行座標搜尋（傳入已載入的斷層資料）
        search_result = coordinate_search_from_file(x_tw97, y_tw97, use_fault_data, fault_gdf)
        
        if search_result:
            # 取得基準地震規模

            city = search_result.get('縣市', '未知')
            base_mw_map = {
                "基隆市": 7.3, "新北市": 7.3, "臺北市": 7.3, "宜蘭縣": 7.3, "花蓮縣": 7.3, "台東縣": 7.3,
                "桃園市": 7.1, "台中市": 7.1, "彰化縣": 7.1, "南投縣": 7.1, "雲林縣": 7.1,
                "嘉義縣": 7.1, "台南市": 7.1, "高雄市": 7.1,
                "新竹縣": 6.9, "苗栗縣": 6.9, "屏東縣": 6.9,
                "澎湖縣": 6.7, "金門縣": 6.7, "馬祖縣": 6.7
            }
            base_mw = base_mw_map.get(city, 7.0)
            
            well_params[well_id] = {
                'city': city,
                'base_mw': base_mw,
                'x': x_tw97,
                'y': y_tw97,
                'SDS': search_result.get('SDS'),
                'SMS': search_result.get('SMS'),
                'SD1': search_result.get('SD1', None),
                'SM1': search_result.get('SM1', None),
                'search_result': search_result
            }
            
            print(f"  ✅ 成功：{city}, Mw={base_mw}, SDS={well_params[well_id]['SDS']}, SMS={well_params[well_id]['SMS']}")
        else:
            # 使用預設值
            well_params[well_id] = {
                'city': '未知',
                'base_mw': 7.0,
                'x': x_tw97,
                'y': y_tw97,
                'SDS': 0.8,
                'SMS': 1.0,
                'SD1': None,
                'SM1': None,
                'search_result': None
            }
            print(f"  ⚠️ 沒有搜尋到地震參數")
        
        # 避免過於頻繁的查詢
        if i < len(well_ids):
            time.sleep(0.5)
    
    return well_params


# NCEER液化分析類別
class NCEER:
    def __init__(self, default_em = 72):
        """初始化NCEER分析器"""
        self.g = 9.81  # 重力加速度 (m/s²)
        self.Pa = 100  # 大氣壓力 (t/m²)
        
        # Fa係數查表
        self.fa_table = {
            "第一類地盤": {
                "SDS<=0.5": 1.0, "SDS=0.6": 1.0, "SDS=0.7": 1.0, "SDS=0.8": 1.0, "SDS>=0.9": 1.0,
                "SMS<=0.5": 1.0, "SMS=0.6": 1.0, "SMS=0.7": 1.0, "SMS=0.8": 1.0, "SMS>=0.9": 1.0
            },
            "第二類地盤": {
                "SDS<=0.5": 1.1, "SDS=0.6": 1.1, "SDS=0.7": 1.0, "SDS=0.8": 1.0, "SDS>=0.9": 1.0,
                "SMS<=0.5": 1.1, "SMS=0.6": 1.1, "SMS=0.7": 1.0, "SMS=0.8": 1.0, "SMS>=0.9": 1.0
            },
            "第三類地盤": {
                "SDS<=0.5": 1.2, "SDS=0.6": 1.2, "SDS=0.7": 1.1, "SDS=0.8": 1.0, "SDS>=0.9": 1.0,
                "SMS<=0.5": 1.2, "SMS=0.6": 1.2, "SMS=0.7": 1.1, "SMS=0.8": 1.0, "SMS>=0.9": 1.0
            }
        }



###    
    def validate_input_data(self, df):
        """驗證輸入數據的完整性"""
        required_columns = ['鑽孔編號', 'TWD97_X', 'TWD97_Y', '上限深度(公尺)', '下限深度(公尺)']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            raise ValueError(f"缺少必要欄位：{missing_columns}")
        
        # 檢查數據類型和範圍
        for col in ['TWD97_X', 'TWD97_Y']:
            if not pd.api.types.is_numeric_dtype(df[col]):
                try:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                except:
                    raise ValueError(f"座標欄位 {col} 包含無效數據")
        
        return df


    def get_user_em_value(self):
        """取得使用者輸入的 Em 值"""
        while True:
            try:
                user_input = input("請輸入 SPT 錘擊能量效率 Em (預設 72，直接按 Enter 使用預設值): ").strip()
                
                if user_input == "":
                    return 72  # 預設值
                
                em_value = float(user_input)
                
                if em_value <= 0:
                    print("錯誤：Em 值必須大於 0，請重新輸入")
                    continue
                elif em_value > 100:
                    print("警告：Em 值通常不會超過 100%，請確認輸入是否正確")
                    confirm = input("是否繼續使用此值？(y/n): ").strip().lower()
                    if confirm in ['y', 'yes']:
                        return em_value
                    else:
                        continue
                else:
                    return em_value
                    
            except ValueError:
                print("錯誤：請輸入有效的數值")
                continue

    def compute_coefficient(self, group):
        """為同一鑽孔的所有土層計算土層深度、厚度、中點深度、分析點深度和應力"""
        group = group.copy()
        
        # 處理 N 值
        if 'N_value' in group.columns:
            group['N'] = group['N_value'].apply(lambda x: parse_numeric_value(x))
        else:
            group['N'] = np.nan
                    
        # 統一欄位名稱
        if 'SPT_top_depth' in group.columns and '上限深度(公尺)' not in group.columns:
            group = group.rename(columns={'SPT_top_depth': '上限深度(公尺)'})
        if 'SPT_bottom_depth' in group.columns and '下限深度(公尺)' not in group.columns:
            group = group.rename(columns={'SPT_bottom_depth': '下限深度(公尺)'})
        group = group.sort_values('上限深度(公尺)').reset_index(drop=True)
        # 統一處理統體單位重和統體密度欄位為 Density
        if '統體密度(t/m3)' in group.columns and '統體單位重(t/m3)' in group.columns:
            # 兩個欄位都存在，優先使用統體密度，如果為空則使用統體單位重
            group['Density'] = group['統體密度(t/m3)'].fillna(group['統體單位重(t/m3)'])
        elif '統體密度(t/m3)' in group.columns:
            group['Density'] = group['統體密度(t/m3)']
        elif '統體單位重(t/m3)' in group.columns:
            group['Density'] = group['統體單位重(t/m3)']
        else:
            group['Density'] = 0.0  # 如果都沒有，設為預設值
        # 【關鍵修正】處理統體單位重缺失值
        print(f"    檢查統體單位重缺失情況...")
        unit_weight_col = 'Density'
        
        # 處理 Density 缺失值
        print(f"    檢查 Density 缺失情況...")

        # 檢查並處理 Density 缺失 - 新的處理邏輯
        missing_count = 0
        for i in range(len(group)):
            density = group.iloc[i][unit_weight_col]
            if pd.isna(density) or density == "" or density is None:
                missing_count += 1
                # 直接設為0，不使用前一層的值或預設值
                group.iloc[i, group.columns.get_loc(unit_weight_col)] = 0.0
                print(f"      第{i+1}層 Density 缺失，設為0")

        if missing_count > 0:
            print(f"    共處理 {missing_count} 個 Density 缺失值，全部設為0")
        # 計算土層深度
        dirt_depths = []
        valid_indices = []
        
        for i in range(len(group)):
            current_row = group.iloc[i]
            lower_depth = current_row['下限深度(公尺)']
            
            # 驗證深度數據
            if pd.isna(lower_depth):
                print(f"    警告：第{i+1}層下限深度缺失，跳過")
                continue
            
            # 如果有下一層
            if i + 1 < len(group):
                next_row = group.iloc[i + 1]
                next_upper_depth = next_row['上限深度(公尺)']
                if not pd.isna(next_upper_depth):
                    dirt_depth = (lower_depth + next_upper_depth) / 2
                else:
                    dirt_depth = lower_depth
            else:
                # 最後一層
                dirt_depth = lower_depth
            
            # 限制土層深度最大為30m
            if dirt_depth > 30:
                print(f"    警告：第{i+1}層深度 {dirt_depth}m 超過30m限制，跳過")
                continue
            
            dirt_depths.append(dirt_depth)
            valid_indices.append(i)
        
        # 只保留有效的資料行
        if len(valid_indices) < len(group):
            group = group.iloc[valid_indices].reset_index(drop=True)
            print(f"    過濾掉 {len(group) - len(valid_indices)} 層無效土層")
        
        group['土層深度'] = dirt_depths

        # 計算土層厚度
        dirt_thickness = []
        for i in range(len(group)):
            if i == 0:
                thickness = dirt_depths[i] if not pd.isna(dirt_depths[i]) else np.nan
            else:
                current_depth = dirt_depths[i]
                previous_depth = dirt_depths[i-1]
                if not pd.isna(current_depth) and not pd.isna(previous_depth):
                    thickness = current_depth - previous_depth
                else:
                    thickness = np.nan
            dirt_thickness.append(thickness)
        
        group['土層厚度'] = dirt_thickness

        # 計算土層中點深度
        dirt_mid_depth = []
        for i in range(len(group)):
            depth = dirt_depths[i]
            thickness = dirt_thickness[i]
            
            if not pd.isna(depth) and not pd.isna(thickness):
                mid_depth = depth - thickness / 2
            else:
                mid_depth = np.nan
            dirt_mid_depth.append(mid_depth)
        
        group['土層中點深度'] = dirt_mid_depth
        
        # 計算分析點深度 - 修改 GWT_CSR 處理邏輯
        analysis_depths = []
        
        
        # 從 water_depth(m) 取得 GWT_CSR，如果為空值則設為 0
        if 'water_depth(m)' in group.columns:
            GWT_CSR = group['water_depth(m)'].iloc[0]
        else:
            GWT_CSR = 0
        
        # 處理 GWT_CSR 空值
        if pd.isna(GWT_CSR) or GWT_CSR == "" or GWT_CSR is None:
            GWT_CSR = 0
            print(f"    地下水位深度為空值，設為 0")
        
        # 確保 GWT_CSR 為數值型態
        try:
            GWT_CSR = float(GWT_CSR)
        except (ValueError, TypeError):
            GWT_CSR = 0
            print(f"    地下水位深度無法轉換為數值，設為 0")

        group['GWT_CSR'] = GWT_CSR
        GWT_CRR = GWT_CSR
        

        for i in range(len(group)):
            if pd.isna(dirt_depths[i]) or dirt_depths[i] == "":
                analysis_depth = ""
            elif dirt_depths[i] > GWT_CSR:
                if not pd.isna(dirt_thickness[i]):
                    min_value = min((dirt_depths[i] - GWT_CSR) / 2, dirt_thickness[i] / 2)
                    analysis_depth = dirt_depths[i] - min_value
                else:
                    analysis_depth = dirt_depths[i] 
            else:
                analysis_depth = dirt_mid_depth[i] if not pd.isna(dirt_mid_depth[i]) else ""
            
            analysis_depths.append(analysis_depth)
        
        group['分析點深度'] = analysis_depths
        
        # 計算FC值（細料含量）
        fc_values = []
        for i in range(len(group)):
            row = group.iloc[i]
            FC = row.get('細料(%)', np.nan)
            
            if pd.isna(FC) or FC == "":
                粉土 = row.get('粉土(%)', 0)
                黏土 = row.get('黏土(%)', 0)
                
                if pd.isna(粉土):
                    粉土 = 0
                if pd.isna(黏土):
                    黏土 = 0
                    
                try:
                    if isinstance(粉土, str):
                        粉土 = float(粉土) if 粉土.replace('.', '').isdigit() else 0
                    if isinstance(黏土, str):
                        黏土 = float(黏土) if 黏土.replace('.', '').isdigit() else 0
                except (ValueError, AttributeError):
                    粉土 = 0
                    黏土 = 0
                    
                FC = 粉土 + 黏土
            
            fc_values.append(FC)
        
        group['FC'] = fc_values

        # 【關鍵修正】改善 sigmav 累計計算
        cumulative_sigmav = []

        for i in range(len(group)):
            current_analysis_depth = analysis_depths[i]
            current_unit_weight = group.iloc[i][unit_weight_col]
            
        
            try:
                current_analysis_depth = float(current_analysis_depth)
                current_unit_weight = float(current_unit_weight)
            except (ValueError, TypeError):
                print(f"    警告：第{i+1}層數據無法轉換為數值")
                cumulative_sigmav.append(np.nan)
                continue
            
            if i == 0:
                # 第一層：sigma_v = 該層分析點深度 × 該層單位重
                sigma_v = current_analysis_depth * current_unit_weight
                print(f"    第1層 sigma_v = {current_analysis_depth} × {current_unit_weight} = {sigma_v}")
            else:
                # 其他層的計算
                prev_soil_depth = dirt_depths[i-1]
                prev_analysis_depth = analysis_depths[i-1]
                prev_unit_weight = group.iloc[i-1][unit_weight_col]
                prev_sigma_v = cumulative_sigmav[i-1]
                
                # 檢查前一層數據有效性
                if (pd.isna(prev_soil_depth) or pd.isna(prev_analysis_depth) or 
                    pd.isna(prev_unit_weight) or pd.isna(prev_sigma_v) or 
                    prev_analysis_depth == ""):
                    print(f"    警告：第{i+1}層計算需要的前一層數據不完整")
                    cumulative_sigmav.append(np.nan)
                    continue
                
                try:
                    prev_soil_depth = float(prev_soil_depth)
                    prev_analysis_depth = float(prev_analysis_depth)
                    prev_unit_weight = float(prev_unit_weight)
                    prev_sigma_v = float(prev_sigma_v)
                except (ValueError, TypeError):
                    print(f"    警告：第{i+1}層前一層數據無法轉換為數值")
                    cumulative_sigmav.append(np.nan)
                    continue
                
                # 計算sigma_v
                part1 = (prev_soil_depth - prev_analysis_depth) * prev_unit_weight
                part2 = (current_analysis_depth - prev_soil_depth) * current_unit_weight
                sigma_v = part1 + part2 + prev_sigma_v
                
                print(f"    第{i+1}層 sigma_v = ({prev_soil_depth} - {prev_analysis_depth}) × {prev_unit_weight} + ({current_analysis_depth} - {prev_soil_depth}) × {current_unit_weight} + {prev_sigma_v} = {sigma_v}")
            
            cumulative_sigmav.append(sigma_v)
        
        group['累計sigmav'] = cumulative_sigmav

        # 計算 sigmav_CSR' (有效應力) 
        sigma_v_CSR_values = []
        for i in range(len(group)):
            if pd.isna(cumulative_sigmav[i]) or pd.isna(analysis_depths[i]) or analysis_depths[i] == "":
                sigma_v_CSR_values.append(np.nan)
                continue
            
            try:
                analysis_depth = float(analysis_depths[i])
                累計sigmav = float(cumulative_sigmav[i])
            except (ValueError, TypeError):
                sigma_v_CSR_values.append(np.nan)
                continue
            
            if analysis_depth <= GWT_CSR:
                # 在地下水位以上，不需要扣除浮力
                sigma_v_CSR = 累計sigmav
            else:
                sigma_v_CSR = 累計sigmav - max(0, (analysis_depth - GWT_CSR) )
            
            sigma_v_CSR_values.append(sigma_v_CSR)
        
        group['sigma_v_CSR'] = sigma_v_CSR_values
        
        # 計算 sigma_v_CRR (類似計算)
        sigma_v_CRR_values = []
        for i in range(len(group)):
            if pd.isna(cumulative_sigmav[i]) or pd.isna(analysis_depths[i]) or analysis_depths[i] == "":
                sigma_v_CRR_values.append(np.nan)
                continue
            
            try:
                analysis_depth = float(analysis_depths[i])
                累計sigmav = float(cumulative_sigmav[i])
            except (ValueError, TypeError):
                sigma_v_CRR_values.append(np.nan)
                continue
            
            if analysis_depth <= GWT_CRR:
                sigma_v_CRR = 累計sigmav
            else:
                sigma_v_CRR = 累計sigmav - max(0, (analysis_depth - GWT_CRR) )

            
            sigma_v_CRR_values.append(sigma_v_CRR)
        
        group['sigma_v_CRR'] = sigma_v_CRR_values

        return group
    def compute_Vs(self, row):
        """計算剪力波速 Vs"""
        soil_class = row.get('統一土壤分類', row.get('土壤分類', ''))
        N_value = row.get('N', np.nan)
        
        if soil_class in ["GW", "GP", "SW", "SP", "GM", "GC", "SM", "SC"]:
            soil_type = "Granular"
        elif soil_class in ["ML", "CL", "OL", "MH", "CH", "OH"]:
            soil_type = "Cohesive"
        else:
            soil_type = "-"
            
        if N_value in [None, 0, ""] or pd.isna(N_value):
            return "NG"

        try:
            N_numeric = float(N_value)
        except (ValueError, TypeError):
            return "NG"

        if soil_type == "Granular":
            Vs = round(80 * (min(N_numeric, 50) ** (1/3)), 2)
        elif soil_type == "Cohesive":
            Vs = round(100 * (min(N_numeric, 25) ** (1/3)), 2)
        else:
            Vs = "NG"
        
        return Vs

    def compute_d_over_v(self, row):
        """計算 d/v 值"""
        thickness = row['土層厚度']
        vs = row['Vs']
        
        if pd.isna(thickness) or pd.isna(vs) or thickness == 0 or vs == 0 or vs == "" or vs == "NG":
            return ""
        
        try:
            thickness_num = float(thickness)
            vs_num = float(vs)
            return round(thickness_num / vs_num, 3)
        except (ValueError, ZeroDivisionError, TypeError):
            return "NG"
    
    def compute_Vs30(self, group):
        """計算 Vs30"""
        # 計算每層的 d/v
        group['d/v'] = group.apply(self.compute_d_over_v, axis=1)
        
        valid_data = group[
            (pd.notna(group['土層厚度'])) & 
            (group['d/v'] != "") & 
            (group['d/v'] != "NG") &
            (group['土層厚度'] > 0)
        ].copy()

        if len(valid_data) == 0:
            return None
        else:
            sum_thickness = valid_data['土層厚度'].sum()
            sum_d_over_v = valid_data['d/v'].sum()
            
            if sum_d_over_v > 0:
                vs30 = round(sum_thickness / sum_d_over_v, 2)
            else:
                vs30 = None

        return vs30

    def ground_class_from_vs30(self, vs30):
        """根據 Vs30 判定地盤分類"""
        if vs30 is None or vs30 == "NG":
            return "第二類地盤"  # 預設值
        
        if vs30 >= 270:
            return "第一類地盤"
        elif 180 <= vs30 < 270:
            return "第二類地盤"
        else:
            return "第三類地盤"
        
    def compute_Fa(self, row, scenario='Design'):
        """計算場址係數 Fa"""
        def get_range_key(value, prefix):
            if value <= 0.5:
                return f"{prefix}<=0.5"
            elif value <= 0.55:
                return f"{prefix}=0.6"
            elif value <= 0.65:
                return f"{prefix}=0.6"
            elif value <= 0.75:
                return f"{prefix}=0.7"
            elif value <= 0.85:
                return f"{prefix}=0.8"
            else:
                return f"{prefix}>=0.9"
        
        # 從 row 中取得參數
        SDS = row.get('SDS') or row.get('使用SDS')
        SMS = row.get('SMS') or row.get('使用SMS')
        
        # 計算地盤分類
        vs30 = getattr(row, '_vs30', None)  # 如果已經計算過就使用
        if vs30 is None:
            # 需要整個group來計算Vs30，這裡使用預設值
            site_class = "第二類地盤"
        else:
            site_class = self.ground_class_from_vs30(vs30)
        
        # 確定 SDS 和 SMS 的範圍
        SDS_range = get_range_key(SDS, "SDS")
        SMS_range = get_range_key(SMS, "SMS")
        
        # 查詢對應的係數
        Fa_SDS = self.fa_table[site_class][SDS_range]
        Fa_SMS = self.fa_table[site_class][SMS_range]
        
        return Fa_SDS, Fa_SMS

    def compute_A_value(self, row, scenario):
        """計算設計地表加速度 A_value - 修改版"""
        # 檢查是否為台北盆地微分區
        data_source = row.get('資料來源', '')
        
        if '台北盆地微分區' in data_source:
            # 台北盆地微分區：直接使用 SD_S, SM_S 值
            SD_S = row.get('SDS') or row.get('使用SDS')  # 台北盆地的SDS就是SD_S
            SM_S = row.get('SMS') or row.get('使用SMS')  # 台北盆地的SMS就是SM_S
            
            # 根據情境計算 A_value
            if scenario == "Design": 
                A_value = 0.4 * SD_S / 3.5
            elif scenario == "MidEq": 
                A_value = 0.4 * SD_S / 4.2
            elif scenario == "MaxEq":
                A_value = 0.4 * SM_S
            else:
                A_value = 0.4 * SD_S
            
            return A_value, SD_S, SM_S
        else:
            # 一般情況：原有的場址係數計算
            Fa_SDS, Fa_SMS = self.compute_Fa(row, scenario)
            
            SDS = row.get('SDS') or row.get('使用SDS')
            SMS = row.get('SMS') or row.get('使用SMS')
            
            SD_S = Fa_SDS * SDS
            SM_S = Fa_SMS * SMS
            
            if scenario == "Design":
                A_value = 0.4 * SD_S
            elif scenario == "MidEq": 
                A_value = 0.4 * SD_S / 4.2
            elif scenario == "MaxEq":
                A_value = 0.4 * SM_S
            else:
                A_value = 0.4 * SD_S
            
            return A_value, SD_S, SM_S

    def compute_N60(self, row):
        """計算 N60"""
        N_value = row['N_value'] if 'N_value' in row else row.get('N', np.nan)
        
        # 從檔案中尋找 Em 欄位，沒有的話使用類別中設定的預設值
        if 'Em' in row and pd.notna(row['Em']) and row['Em'] != "":
            Em = row['Em']
        else:
            Em = self.default_em  # 使用類別中設定的預設值
        
        N_value_parsed = parse_numeric_value(N_value)
        Em_parsed = parse_numeric_value(Em)
        
        if N_value_parsed is None or Em_parsed is None:
            return 0.00
        
        try:
            N60 = N_value_parsed * Em_parsed / 60
            return format_result(N60)
        except (ValueError, TypeError):
            return 0.00
        
    def compute_N1_60(self, row):
        """計算 N1_60"""
        N_value = row['N_value'] if 'N_value' in row else row.get('N', np.nan)
        sigma_v = row['累計sigmav']
        sigma_v_CRR = row['sigma_v_CRR']
        N60 = self.compute_N60(row)  
        N_value_parsed = parse_numeric_value(N_value)
        
        if N_value_parsed is None or pd.isna(sigma_v) or sigma_v <= 0:
            return 0.00
        
        try:
            Cn = np.minimum(np.sqrt(self.Pa / sigma_v_CRR), 1.7)
            N1_60 = Cn * parse_numeric_value(N60)
            return format_result(N1_60)
        except (ValueError, TypeError):
            return 0.00
        
    def compute_N1_60cs(self, row):
        """計算 N1_60cs"""
        N1_60 = self.compute_N1_60(row)  # 修正：應該是函數調用
        FC = row['FC']  # 細料含量
        
        if N1_60 == "-" or pd.isna(N1_60):
            return "-"
        
        try:
            N1_60_parsed = parse_numeric_value(N1_60)
            if N1_60_parsed is None:
                return "-"
            
            if FC <= 5:
                a = 0.0  # 明確指定為浮點數
                b = 1.0
            elif 5 < FC <= 35:    
                # 修正1: 使用圓括號而不是方括號調用 np.exp
                a = np.exp(1.76 - 190/(FC ** 2))
                # 修正2: 移除方括號，直接計算數值
                b = 0.99 + (FC ** 1.5) / 1000
            elif FC > 35:  # 修正3: 簡化條件判斷
                a = 5.0
                b = 1.2
            else:
                # 這個 else 實際上不會被執行，但保留作為安全措施
                a = 5.0
                b = 1.2
            
            N1_60cs = a + (b * N1_60_parsed)
            return format_result(N1_60cs)
            
        except (ValueError, TypeError, ZeroDivisionError) as e:
            print(f"計算 N1_60cs 時發生錯誤: {e}, FC = {FC}, N1_60 = {N1_60}")
            return "-"



    # 計算 CRR_7.5
    def compute_CRR_7_5(self, row):
        
        
        
        
        """計算 CRR_7.5 - 使用指定公式"""
        N1_60cs = self.compute_N1_60cs(row)
        
        if N1_60cs == "-" or pd.isna(N1_60cs) :
            return "-"
        
        try:

            if N1_60cs is None:
                return "-"
            CRR_7_5 = (1 / (34 - N1_60cs)) + (N1_60cs / 135) + (50 / ((10 * N1_60cs + 45) ** 2)) - (1/200)
        
            return format_result(CRR_7_5)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            print(f"計算 CRR_7_5 時發生錯誤: {e}, N1_60cs = {N1_60cs}")
        return "-"

    def calculate_FS(self, row, scenario='Design'):
        """計算液化安全係數 (FS) 及相關參數"""
        
        # 獲取基本參數
        soil_class = row.get('統一土壤分類', '') 
        
        PI_raw = row.get('塑性指數(%)', 0)
        is_np_or_empty = False  # 標記是否為NP或空值

        if pd.isna(PI_raw) or PI_raw == "" or PI_raw is None:
            PI = 0
            is_np_or_empty = True
        elif str(PI_raw).upper() == "NP":
            PI = 0
            is_np_or_empty = True
        else:
            try:
                PI = float(PI_raw)
                is_np_or_empty = False
            except (ValueError, TypeError):
                PI = 0
                is_np_or_empty = True
        
        dirt_depth = row['分析點深度']
        GWT_CSR = row.get('GWT_CSR', 0)
        N1_60cs_value = parse_numeric_value(row['N1_60cs'])
        
        # 獲取地震規模
        base_mw = row.get('基準Mw', 7.0)
        mw_value = get_scenario_mw(base_mw, scenario)
        

        # 新增判斷條件1: 深度 < 20m 或 深度在地下水位以上
        depth_condition = False
        if pd.notna(dirt_depth) and dirt_depth != "":
            if dirt_depth > 20 or dirt_depth <= GWT_CSR:
                depth_condition = True
                print(f"Debug - 深度條件觸發: depth={dirt_depth}, GWT={GWT_CSR}")
        
        # 新增判斷條件2: 塑性指數 > 7 (空值已轉為0，所以0不會觸發)
        pi_condition = False
        if PI > 7 and not is_np_or_empty :
            pi_condition = True
            print(f"Debug - PI條件觸發: PI={PI} (原值: {PI_raw}) > 7")
        
        # 新增判斷條件3: CRR_7_5 為 "-"
        crr_condition = False
        CRR_7_5_value = self.compute_CRR_7_5(row)
        if CRR_7_5_value == "-":
            crr_condition = True
            print(f"Debug - CRR條件觸發: CRR_7_5={CRR_7_5_value}")
        
        
        
        # 檢查是否符合任一 FS=3 的條件
        should_set_fs_3 = crr_condition 
        if should_set_fs_3:
            
            # 計算其他參數但設定 FS = 3
            try:
                # 計算 A_value, SD_S, SM_S
                A_value, SD_S, SM_S = self.compute_A_value(row, scenario)
                
                # 計算 MSF (規模修正因子)
                MSF = (mw_value / 7.5) ** (-2.56)
                
                # 計算 rd (應力折減係數)
                z = depth
                rd = (1 - 0.4113 * np.sqrt(z) + 0.04052 * z + 0.001753 * (z ** 1.5) ) / (1-0.4117 * np.sqrt(z) + 0.05729 * z - 0.006205 * (z ** 1.5) + 0.001210 * (z ** 2))
         
                # 計算 CSR 和 CRR
                sigma_v_csr = row.get('sigma_v_CSR')
                sigma_v = row.get('累計sigmav')
                
                if pd.notna(sigma_v_csr) and pd.notna(sigma_v) and rd != "-":
                    CSR = parse_numeric_value(0.65 * (A_value) * (sigma_v / sigma_v_csr) * rd )
                else:
                    CSR = "-"
                
                CRR_7_5_numeric = parse_numeric_value(CRR_7_5_value)
                if CRR_7_5_numeric is not None and MSF != "-":
                    CRR = CRR_7_5_numeric * MSF
                else:
                    CRR = "-"
                
            except Exception as e:
                print(f"Debug - 計算其他參數時發生錯誤: {e}")
                # 如果計算失敗，設定為預設值
                A_value = "-"
                SD_S = "-"
                SM_S = "-"
                MSF = "-"
                rd = "-"
                CSR = "-"
                CRR = "-"
            
            return {
                'Mw_used': format_result(mw_value),
                'A_value': format_result(A_value) if A_value != "-" else "-",
                'SD_S': format_result(SD_S) if SD_S != "-" else "-",
                'SM_S': format_result(SM_S) if SM_S != "-" else "-",
                'MSF': format_result(MSF) if MSF != "-" else "-",
                'rd': format_result(rd) if rd != "-" else "-",
                'CSR': format_result(CSR) if CSR != "-" else "-",
                'CRR': format_result(CRR) if CRR != "-" else "-",
                'FS': 3.0  # 明確設定為 3.0
            }
        
        print(f"Debug - 進行正常 FS 計算")
        
        # 如果不符合上述條件，進行正常計算
        # 取得必要參數
        depth = row['分析點深度']
        sigma_v_csr = row['sigma_v_CSR']
        CRR_7_5 = parse_numeric_value(CRR_7_5_value)
        sigma_v = row['累計sigmav']
        
        # 檢查必要數據完整性
        if pd.isna(depth) or pd.isna(sigma_v_csr) or CRR_7_5 is None or pd.isna(sigma_v):
            return {
                'Mw_used': format_result(mw_value),
                'A_value': "-",
                'SD_S': "-",
                'SM_S': "-",
                'MSF': "-",
                'rd': "-",
                'CSR': "-", 
                'CRR': "-",
                'FS': "-"
            }
        
        try:
            # 1. 計算 A_value, SD_S, SM_S
            A_value, SD_S, SM_S = self.compute_A_value(row, scenario)
            
            # 2. 計算 MSF (規模修正因子)
            MSF = (mw_value / 7.5) ** (-2.56)
            z = depth
            rd = (1 - 0.4113 * np.sqrt(z) + 0.04052 * z + 0.001753 * (z ** 1.5) ) / (1-0.4117 * np.sqrt(z) + 0.05729 * z - 0.006205 * (z ** 1.5) + 0.001210 * (z ** 2))
         

            
            # 4. 計算 CSR (反覆剪應力比)
            CSR = parse_numeric_value(0.65 * (A_value) * (sigma_v / sigma_v_csr) * rd )
            
            # 5. 計算調整後的 CRR
            CRR = CRR_7_5 * MSF
            
            # 6. 計算安全係數 FS
            if CSR > 0:
                FS = CRR / CSR
                FS = min(FS, 3)
            else:
                FS = 3  # 設定一個大數值表示非常安全
            
            print(f"Debug - 正常計算結果: FS={FS}")
                
            return {
                'Mw_used': format_result(mw_value),
                'A_value': format_result(A_value),
                'SD_S': format_result(SD_S),
                'SM_S': format_result(SM_S),
                'MSF': format_result(MSF),
                'rd': format_result(rd),
                'CSR': format_result(CSR),
                'CRR': format_result(CRR),
                'FS': format_result(FS)
            }
            
        except Exception as e:
            print(f"計算液化參數時發生錯誤: {e}")
            return {
                'Mw_used': format_result(mw_value),
                'A_value': "-",
                'SD_S': "-", 
                'SM_S': "-",
                'MSF': "-",
                'rd': "-",
                'CSR': "-",
                'CRR': "-", 
                'FS': "-"
            }

    def calculate_LPI_single_layer(self, row, scenario):
        """計算單層液化潛能指數 LPI"""
        fs_col = f'FS_{scenario}'
        
        z = row['分析點深度']
        thickness = row['土層厚度']
        fs_value = row[fs_col]
        
        # 檢查必要數據是否完整
        if pd.isna(z) or pd.isna(thickness) or fs_value == "-":
            return "-"
            
        # 只計算深度 20m 以內的土層
        if z > 20:
            return 0.0
            
        # Wi = 10 - 0.5*z
        Wi = 10 - 0.5 * z
        if Wi <= 0:
            return 0.0
            
        # max(0, 1 - FS)
        fs_numeric = float(fs_value) if fs_value != "-" else 3.0
        lpi_value = max(0, 1 - fs_numeric) * Wi * thickness
        
        return format_result(lpi_value)
    def generate_simplified_report(self, final_df: pd.DataFrame, output_dir: str = None, 
                              scenario: str = "Design") -> str:
        """生成簡化的液化分析報表"""
        print(f"\n正在生成簡化報表（{scenario} ）...")
        
        # 選擇需要的欄位並重新命名
        column_mapping = {
            '鑽孔編號': 'HOLE ID',
            'TWD97_X': 'X', 
            'TWD97_Y': 'Y',
            '鑽孔地表高程': 'Z',
            '上限深度(公尺)': 'from',
            '下限深度(公尺)': 'to',
            '統一土壤分類': 'USCS',
            'N': 'SPT-N',
            f'FS_{scenario}': 'FS',
            f'LPI_{scenario}': 'LPI'
        }
        
        # 檢查必要欄位是否存在
        missing_columns = []
        available_columns = []
        
        for original_col, new_col in column_mapping.items():
            if original_col in final_df.columns:
                available_columns.append((original_col, new_col))
            else:
                missing_columns.append(original_col)
        
        if missing_columns:
            print(f"警告：以下欄位在資料中找不到，將以空值填充：{missing_columns}")
        
        # 過濾深度條件：保留到第一個超過20m的層，其餘刪除
        print(f"  過濾前資料筆數：{len(final_df)}")
        
        # 檢查上限深度欄位
        depth_column = None
        possible_depth_cols = ['上限深度(公尺)', '上限深度(m)', 'from', '上限深度']
        
        for col in possible_depth_cols:
            if col in final_df.columns:
                depth_column = col
                break
        if depth_column:
            print(f"  正在處理深度過濾...")
            
            # 按鑽孔分組處理
            filtered_dfs = []
            
            for hole_id in final_df['鑽孔編號'].unique():
                hole_data = final_df[final_df['鑽孔編號'] == hole_id].copy()
                
                # 按上限深度排序
                hole_data = hole_data.sort_values(depth_column).reset_index(drop=True)
                
                # 檢查土層深度欄位
                soil_depth_col = None
                for col in ['土層深度', '土層深度(m)', '分析點深度']:
                    if col in hole_data.columns:
                        soil_depth_col = col
                        break
                
                if soil_depth_col is None:
                    print(f"    警告：鑽孔 {hole_id} 找不到土層深度欄位，使用原始邏輯")
                    # 使用原來的邏輯
                    depth_numeric = pd.to_numeric(hole_data[depth_column], errors='coerce')
                    over_20_indices = depth_numeric[depth_numeric > 20].index
                    
                    if len(over_20_indices) > 0:
                        first_over_20_idx = over_20_indices[0]
                        keep_data = hole_data.iloc[:first_over_20_idx + 1].copy()
                        if '下限深度(公尺)' in keep_data.columns:
                            keep_data.loc[keep_data.index[first_over_20_idx], '下限深度(公尺)'] = 20.0
                    else:
                        keep_data = hole_data
                else:
                    # 使用土層深度進行判斷
                    soil_depths = pd.to_numeric(hole_data[soil_depth_col], errors='coerce')
                    
                    # 找到第一個土層深度超過20m的索引
                    first_over_20_idx = None
                    for i, depth in enumerate(soil_depths):
                        if pd.notna(depth) and depth > 20:
                            first_over_20_idx = i
                            break
                    
                    if first_over_20_idx is not None:
                        # 保留到第一個超過20m的層（包含）
                        keep_data = hole_data.iloc[:first_over_20_idx + 1].copy()
                        
                        # 將第一個超過20m的土層深度設為20
                        keep_data.iloc[first_over_20_idx, keep_data.columns.get_loc(soil_depth_col)] = 20.0
                        
                        print(f"    鑽孔 {hole_id}: 保留 {len(keep_data)} 層（原 {len(hole_data)} 層），將第一個>20m層({soil_depths.iloc[first_over_20_idx]:.3f}m)設為20m")
                    else:
                        # 沒有超過20m的層，全部保留
                        keep_data = hole_data
                        print(f"    鑽孔 {hole_id}: 全部保留 {len(keep_data)} 層（無超過20m的土層）")
                
                filtered_dfs.append(keep_data)
            
            filtered_df = pd.concat(filtered_dfs, ignore_index=True)
            
            removed_count = len(final_df) - len(filtered_df)
            print(f"  總共移除資料：{removed_count} 筆")
            print(f"  過濾後資料筆數：{len(filtered_df)}")
            
            if len(filtered_df) == 0:
                print(f"  警告：過濾後沒有資料！")
                return None
        else:
            print(f"  警告：找不到上限深度欄位，跳過深度過濾")
            filtered_df = final_df.copy()
        
        # 建立簡化報表
        simplified_df = pd.DataFrame()
        
        for original_col, new_col in available_columns:
            if original_col in filtered_df.columns:
                simplified_df[new_col] = filtered_df[original_col]
        
        # 補充缺失的欄位（如果有的話）
        for original_col, new_col in column_mapping.items():
            if new_col not in simplified_df.columns:
                if original_col in filtered_df.columns:
                    simplified_df[new_col] = filtered_df[original_col]
                else:
                    simplified_df[new_col] = "-"
        
        # 確保欄位順序正確
        desired_order = ['HOLE ID', 'X', 'Y', 'Z', 'from', 'to', 'USCS', 'SPT-N', 'FS', 'LPI']
        simplified_df = simplified_df[desired_order]
        
        # 重新計算 from 和 to（根據土層深度作為中心深度）
        print("  正在重新計算 from 和 to 深度...")
        for hole_id in simplified_df['HOLE ID'].unique():
            hole_mask = simplified_df['HOLE ID'] == hole_id
            hole_data = simplified_df[hole_mask].copy()
            
            # 按照原始順序排序
            hole_data = hole_data.sort_values('from').reset_index(drop=True)
            hole_indices = simplified_df[hole_mask].index.tolist()
            
            # 檢查是否有土層深度欄位
            depth_col = None
            possible_depth_cols = ['土層深度', '土層深度(m)']
            
            # 從 filtered_df 中找對應的土層深度資料
            hole_original_data = filtered_df[filtered_df['鑽孔編號'] == hole_id].copy()
            
            for col in possible_depth_cols:
                if col in hole_original_data.columns:
                    depth_col = col
                    break
            
            if depth_col is None:
                print(f"    警告：鑽孔 {hole_id} 找不到土層深度欄位，使用原始 from/to")
                continue
            
            # 取得所有土層深度值並排序
            layer_depths = []
            for i in range(len(hole_data)):
                try:
                    depth_value = hole_original_data.iloc[i][depth_col]
                    depth = float(depth_value) if pd.notnull(depth_value) and depth_value != "-" else 0.0
                    layer_depths.append(depth)
                except (ValueError, IndexError, TypeError):
                    layer_depths.append(0.0)
            
            # 重新計算 from 和 to
            for i in range(len(hole_data)):
                actual_idx = hole_indices[i]
                current_depth = layer_depths[i]
                
                if i == 0:
                    # 第一層：from = 0, to = 當前深度
                    from_depth = 0.0
                    if i + 1 < len(layer_depths):
                        to_depth = current_depth
                    else:
                        # 只有一層的情況，to = 當前深度或20
                        to_depth = min(current_depth, 20.0)
                elif i == len(layer_depths) - 1:
                    # 最後一層：from = 前一層的 to, to = 20 或當前深度
                    prev_idx = hole_indices[i - 1]
                    from_depth = simplified_df.loc[prev_idx, 'to']
                    to_depth = 20.0
                else:
                    # 中間層：from = 前一層深度 + 當前深度, to = 當前深度
                    prev_idx = hole_indices[i - 1]
                    from_depth = simplified_df.loc[prev_idx, 'to']
                    to_depth = current_depth 
                
                # 確保不超過 20m
                to_depth = min(to_depth, 20.0)
                
                simplified_df.loc[actual_idx, 'from'] = from_depth
                simplified_df.loc[actual_idx, 'to'] = to_depth
            
            print(f"    鑽孔 {hole_id}: 重新計算 from/to，基於土層深度分割")
        
        # 處理數值格式
        numeric_cols = ['X', 'Y', 'Z', 'from', 'to', 'SPT-N', 'FS', 'LPI']
        for col in numeric_cols:
            if col in simplified_df.columns:
                simplified_df[col] = simplified_df[col].apply(
                    lambda x: format_result(x, 3) if pd.notnull(x) and x != "-" and x != "" else "-"
                )
        
        # 生成輸出檔名
        if output_dir is None:
            output_dir = ""
        current_date = datetime.now().strftime("%m%d")
        simplified_filename = os.path.join(output_dir, f"NCEER_{scenario}_{current_date}.csv")
        
        try:
            simplified_df.to_csv(simplified_filename, index=False, encoding='utf-8-sig')
            print(f"✅ 簡化報表已儲存至：{simplified_filename}")
            
            # 顯示報表統計
            total_rows = len(simplified_df)
            unique_holes = simplified_df['HOLE ID'].nunique()
            print(f"   總記錄數：{total_rows}")
            print(f"   鑽孔數量：{unique_holes}")
            
            return simplified_filename
            
        except Exception as e:
            print(f"儲存簡化報表時發生錯誤：{e}")
            return None
    
    def generate_lpi_summary_report(self, final_df: pd.DataFrame, output_dir: str = None) -> str:
        """生成LPI摘要報表"""
        print(f"\n正在生成LPI摘要報表...")
        
        # 取得每個鑽孔的基本資訊和LPI總和
        summary_data = []
        
        for hole_id in final_df['鑽孔編號'].unique():
            hole_data = final_df[final_df['鑽孔編號'] == hole_id]
            
            if len(hole_data) == 0:
                continue
            
            # ===== 加入跟簡化報表相同的深度過濾邏輯 =====
            # 按分析點深度排序
            hole_data = hole_data.sort_values('分析點深度').reset_index(drop=True)
            
            # 找到第一個深度超過20m的索引
            first_over_20_idx = None
            for i, row in hole_data.iterrows():
                depth = row.get('分析點深度', 0)
                try:
                    depth = float(depth) if pd.notna(depth) and depth != "" else 0
                except (ValueError, TypeError):
                    depth = 0
                
                if depth > 20:
                    first_over_20_idx = i
                    break
            
            # 如果有超過20m的層，只保留到第一個超過20m的層（包含）
            if first_over_20_idx is not None:
                hole_data = hole_data.iloc[:first_over_20_idx + 1].copy()
            # ===== 深度過濾邏輯結束 =====
            
            # 取得座標和高程（使用第一筆資料）
            first_row = hole_data.iloc[0]
            x = first_row.get('TWD97_X', '')
            y = first_row.get('TWD97_Y', '')
            z = first_row.get('鑽孔地表高程', '')
            
            # 計算各情境的LPI總和（使用過濾後的資料）
            lpi_sums = {}
            scenarios = ['Design', 'MidEq', 'MaxEq']
            
            for scenario in scenarios:
                lpi_col = f'LPI_{scenario}'
                if lpi_col in hole_data.columns:
                    # 將LPI值轉換為數值，忽略"-"和空值
                    lpi_values = []
                    for lpi_val in hole_data[lpi_col]:
                        if lpi_val != '-' and lpi_val != '' and pd.notna(lpi_val):
                            try:
                                lpi_values.append(float(lpi_val))
                            except (ValueError, TypeError):
                                continue
                    
                    total_lpi = sum(lpi_values) if lpi_values else 0.0
                    lpi_sums[scenario] = round(total_lpi, 3)
                else:
                    lpi_sums[scenario] = 0.0
            
            summary_data.append({
                'Hole_ID': hole_id,
                'X': x,
                'Y': y,
                'Z': z,
                'LPI_Design': lpi_sums['Design'],
                'LPI_MidEq': lpi_sums['MidEq'],
                'LPI_MaxEq': lpi_sums['MaxEq']
            })
        
        # 建立DataFrame
        summary_df = pd.DataFrame(summary_data)
        
        # 格式化數值
        numeric_cols = ['X', 'Y', 'Z', 'LPI_Design', 'LPI_MidEq', 'LPI_MaxEq']
        for col in numeric_cols:
            if col in summary_df.columns:
                summary_df[col] = summary_df[col].apply(
                    lambda x: format_result(x, 3) if pd.notnull(x) and x != "" else ""
                )
        
        # 生成輸出檔名
        current_date = datetime.now().strftime("%m%d")
        if output_dir is None:
            output_dir = ""
        
        filename = os.path.join(output_dir, f"LPI_Summary_NCEER_{current_date}.csv")
        
        try:
            summary_df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"✅ LPI摘要報表已儲存至：{filename}")
            
            # 顯示報表統計
            print(f"   鑽孔數量：{len(summary_df)}")
            print(f"   報表欄位：{list(summary_df.columns)}")
            
            return filename
            
        except Exception as e:
            print(f"儲存LPI摘要報表時發生錯誤：{e}")
            return None

    
    def NCEER_main(self, show_gui: bool = True, input_file_path: Optional[str] = None, 
         output_file_path: Optional[str] = None, use_fault_data: bool = True,
         fault_shapefile_path: Optional[str] = None, custom_em: Optional[float] = None):
    
        print("="*80)
        print("開始 NCEER 液化分析...")
        print("="*80)

        # 取得 Em 值
        if custom_em is not None:
            self.default_em = custom_em
            print(f"使用指定的 Em 值: {custom_em}")
        else:
            self.default_em = self.get_user_em_value()
            print(f"使用 Em 值: {self.default_em}")

        # 1. 取得檔案路徑
        if input_file_path is None and show_gui:
            file_path = get_input_file(None, show_gui=True)
        elif input_file_path is not None:
            file_path = input_file_path
        else:
            print("錯誤：未提供 input_file_path，且未啟用 GUI")
            return None, None, None
        
        if not file_path:
            return None, None, None

        # 2. 詢問是否使用斷層資料
        fault_gdf = None
        if use_fault_data:
            if fault_shapefile_path:
                try:
                    fault_gdf = gpd.read_file(fault_shapefile_path)
                    print(f"✅ 成功載入斷層資料：{len(fault_gdf)} 個記錄")
                except Exception as e:
                    print(f"⚠️ 載入斷層資料失敗：{e}")
                    fault_gdf = None
            else:
                # 詢問使用者是否要使用斷層資料
                use_fault = input("是否要使用斷層距離參數？(y/n，預設為 y): ").strip().lower()
                if use_fault in ['y', 'yes','']:
                    print("請選擇斷層 shapefile (.shp) 檔案...")
                    try:
                        root = tk.Tk()
                        root.withdraw()
                        shp_path = filedialog.askopenfilename(
                            title="選擇斷層 shapefile",
                            filetypes=[("Shapefile", "*.shp")]
                        )
                        root.destroy()
                        
                        if shp_path:
                            fault_gdf = gpd.read_file(shp_path)
                            print(f"✅ 成功載入斷層資料：{len(fault_gdf)} 個記錄")
                        else:
                            print("⚠️ 未選擇斷層檔案，跳過斷層距離參數查詢")
                            use_fault_data = False
                    except Exception as e:
                        print(f"⚠️ 載入斷層資料失敗：{e}")
                        use_fault_data = False
                else:
                    print("跳過斷層距離參數查詢")
                    use_fault_data = False

        # 3. 讀取資料
        print("正在讀取資料...")
        try:
            df = pd.read_csv(file_path)
            df = self.validate_input_data(df)
            print(f"共讀取 {len(df)} 筆資料")
        except Exception as e:
            print(f"讀取檔案錯誤：{e}")
            return None, None, None



        # 3.1 過濾N值為空的資料
        print("\n正在過濾N值...")
        original_count = len(df)

        # 檢查N值欄位
        n_value_column = None
        possible_n_cols = ['N_value', 'N值', 'SPT_N', 'N', 'spt_n']

        for col in possible_n_cols:
            if col in df.columns:
                n_value_column = col
                break

        if n_value_column is None:
            print("警告：找不到N值欄位，跳過N值過濾")
            print(f"可用欄位：{list(df.columns)}")
        else:
            print(f"使用N值欄位：{n_value_column}")
            
            # 過濾條件：N值不為空、不為NaN、不為空字串
            def is_valid_n_value(value):
                if pd.isna(value) or value == '' or value is None:
                    return False
                
                # 轉換為字串檢查
                value_str = str(value).strip()
                
                if value_str == '' or value_str.upper() == 'NAN':
                    return False
                
                # 嘗試解析數值（包含>符號的情況）
                parsed_value = parse_numeric_value(value)
                return parsed_value is not None
            
            # 應用過濾條件
            valid_mask = df[n_value_column].apply(is_valid_n_value)
            df = df[valid_mask].reset_index(drop=True)
            
            filtered_count = len(df)
            removed_count = original_count - filtered_count
            
            print(f"N值過濾結果：")
            print(f"  原始資料筆數：{original_count}")
            print(f"  保留資料筆數：{filtered_count}")
            print(f"  移除資料筆數：{removed_count}")
            
            if filtered_count == 0:
                print("❌ 錯誤：過濾後沒有任何資料！請檢查N值資料")
                return None, None, None
            
            # 顯示移除的資料統計
            if removed_count > 0:
                removed_wells = df[~valid_mask]['鑽孔編號'].nunique() if '鑽孔編號' in df.columns else 0
                print(f"  影響鑽孔數：{removed_wells} 個")
        #3.2 過濾非SPT鑽井
        # 過濾取樣編號：只保留開頭是 "S" 的資料
        print("\n正在過濾取樣編號...")
        original_count = len(df)
        
        # 檢查是否有取樣編號欄位
        sampling_id_column = None
        possible_columns = ['取樣編號', '樣本編號', 'Sample_ID', 'sampling_id', '編號']
        
        for col in possible_columns:
            if col in df.columns:
                sampling_id_column = col
                break
        
        if sampling_id_column is None:
            print("警告：找不到取樣編號欄位，跳過過濾步驟")
            print(f"可用欄位：{list(df.columns)}")
        else:
            print(f"使用欄位：{sampling_id_column}")
            
            # 過濾條件：取樣編號開頭是 "S"
            mask = df[sampling_id_column].astype(str).str.startswith('S')
            df = df[mask].reset_index(drop=True)
            
            filtered_count = len(df)
            removed_count = original_count - filtered_count
            
            print(f"過濾結果：")
            print(f"  原始資料筆數：{original_count}")
            print(f"  保留資料筆數：{filtered_count}")
            print(f"  移除資料筆數：{removed_count}")
            
            if filtered_count == 0:
                print("❌ 錯誤：過濾後沒有任何資料！請檢查取樣編號格式")
                return None, None, None
            
            # 顯示保留的取樣編號範例
            sample_ids = df[sampling_id_column].unique()[:5]
            print(f"  保留的取樣編號範例：{list(sample_ids)}")
            if len(df[sampling_id_column].unique()) > 5:
                print(f"  ... 等共 {len(df[sampling_id_column].unique())} 個不同的取樣編號")

        # 4. 獲取唯一的鑽孔編號
        well_ids = df['鑽孔編號'].unique()
        print(f"發現 {len(well_ids)} 個鑽孔：{list(well_ids)}")

        # 5. 使用檔案中的座標進行搜尋，獲取地震參數
        well_params = get_earthquake_parameters_from_wells(df, use_fault_data, fault_gdf)

        # 6. 將查詢結果添加到原始資料中
        print("\n正在將地震參數添加到資料中...")
        df['城市'] = df['鑽孔編號'].map(lambda x: well_params[x]['city'] if x in well_params else '未知')
        df['基準Mw'] = df['鑽孔編號'].map(lambda x: well_params[x]['base_mw'] if x in well_params else 7.0)
        df['SDS'] = df['鑽孔編號'].map(lambda x: well_params[x]['SDS'] if x in well_params else 0.8)
        df['SMS'] = df['鑽孔編號'].map(lambda x: well_params[x]['SMS'] if x in well_params else 1.0)
        df['資料來源'] = df['鑽孔編號'].map(lambda x: well_params[x]['search_result'].get('資料來源', '') if x in well_params and well_params[x]['search_result'] else '')
        
        # 7. 顯示每個鑽孔使用的地震參數
        print("\n=== 各鑽孔地震參數摘要 ===")
        for well_id in well_ids:
            params = well_params[well_id]
            print(f"鑽孔 {well_id}:")
            print(f"  位置: {params['city']}")
            print(f"  基準Mw: {params['base_mw']}")
            print(f"  SDS: {params['SDS']}")
            print(f"  SMS: {params['SMS']}")

        # 8. 逐井計算液化參數
        print("\n=== 正在計算液化參數 ===")
        results_list = []
        lpi_summary = {}

        for well_id in well_ids:
            print(f"\n處理鑽孔：{well_id}")
            well_df = df[df['鑽孔編號'] == well_id].copy()
            
            # 取得該井的地震參數
            params = well_params[well_id]
            SDS = params['SDS']
            SMS = params['SMS']
            base_mw = params['base_mw']
            city = params['city']
            
            # 地震情境設定
            earthquake_scenarios = {
                "Design": {"description": "設計地震"},
                "MidEq": {"description": "中小地震"}, 
                "MaxEq": {"description": "最大地震"}
            }
            
            print(f"  使用地震參數：SDS={SDS}, SMS={SMS}")
            
            # 確保 GWT_CSR 欄位存在
            if 'GWT_CSR' not in well_df.columns:
                well_df['GWT_CSR'] = 0  # 預設地下水位深度 0m
            
            try:
                # 計算基本參數
                well_df = self.compute_coefficient(well_df)
                
                # 計算 Vs 相關參數
                well_df['Vs'] = well_df.apply(self.compute_Vs, axis=1)
                
                # 計算 Vs30 (需要整個group)
                vs30 = self.compute_Vs30(well_df)
                well_df['Vs30'] = vs30
                well_df['地盤分類'] = self.ground_class_from_vs30(vs30)
                
                # 為每行添加 vs30 屬性以供 compute_Fa 使用
                for idx in well_df.index:
                    well_df.loc[idx, '_vs30'] = vs30
                
                # 計算 N60, N1_60, N1_60cs, CRR_7_5
                well_df['N_60'] = well_df.apply(self.compute_N60, axis=1)
                well_df['N1_60'] = well_df.apply(self.compute_N1_60, axis=1)  
                well_df['N1_60cs'] = well_df.apply(self.compute_N1_60cs, axis=1)
                well_df['CRR_7_5'] = well_df.apply(self.compute_CRR_7_5, axis=1)
                
                # 計算三種地震情境的液化參數
                for scenario, scenario_data in earthquake_scenarios.items():
                    print(f"    正在計算 {scenario} 地震情境...")
                    
                    # 根據情境調整 Mw 值
                    adjusted_mw = get_scenario_mw(base_mw, scenario)
                    
                    # 計算液化參數
                    liq_results = well_df.apply(
                        lambda row: self.calculate_FS(row, scenario), 
                        axis=1
                    )
                    
                    # 提取結果到對應欄位
                    well_df[f'Mw_{scenario}'] = [result['Mw_used'] for result in liq_results]
                    well_df[f'A_value_{scenario}'] = [result['A_value'] for result in liq_results]
                    well_df[f'SD_S_{scenario}'] = [result['SD_S'] for result in liq_results]
                    well_df[f'SM_S_{scenario}'] = [result['SM_S'] for result in liq_results]
                    well_df[f'MSF_{scenario}'] = [result['MSF'] for result in liq_results]
                    well_df[f'rd_{scenario}'] = [result['rd'] for result in liq_results]
                    well_df[f'CSR_{scenario}'] = [result['CSR'] for result in liq_results]
                    well_df[f'CRR_{scenario}'] = [result['CRR'] for result in liq_results]
                    well_df[f'FS_{scenario}'] = [result['FS'] for result in liq_results]
                    
                    print(f"      Mw: {base_mw} → {adjusted_mw} (調整值: {adjusted_mw - base_mw:+.1f})")
                
                # 計算每層 LPI
                for scenario in earthquake_scenarios.keys():
                    well_df[f'LPI_{scenario}'] = well_df.apply(
                        lambda row: self.calculate_LPI_single_layer(row, scenario), axis=1
                    )
                
                # 添加井的基本資訊
                well_df['城市'] = city
                well_df['基準地震規模Mw'] = format_result(base_mw, 1)
                well_df['使用SDS'] = SDS
                well_df['使用SMS'] = SMS
                
                # 計算該井總 LPI
                lpi_results = {}
                for scenario in earthquake_scenarios.keys():
                    lpi_col = f'LPI_{scenario}'
                    total_lpi = well_df[lpi_col].apply(
                        lambda x: float(x) if x != "-" and pd.notnull(x) else 0.0
                    ).sum()
                    lpi_results[scenario] = format_result(total_lpi)
                
                lpi_summary[well_id] = lpi_results
                results_list.append(well_df)
                
            except Exception as e:
                print(f"  ❌ 處理鑽孔 {well_id} 時發生錯誤：{e}")
                logger.error(f"處理鑽孔 {well_id} 錯誤：{e}")
                continue

        if not results_list:
            print("沒有成功處理任何鑽孔資料")
            return None, None, file_path

        # 9. 合併所有結果
        final_df = pd.concat(results_list, ignore_index=True)

        # 10. 格式化數值欄位
        numeric_columns = ['累計sigmav', 'sigma_v_CSR', '分析點深度', '土層厚度', '土層中點深度']
        for col in numeric_columns:
            if col in final_df.columns:
                final_df[col] = final_df[col].apply(lambda x: format_result(x) if pd.notnull(x) else "-")

        # 11. 選擇輸出資料夾 - 改善版本
        if show_gui:
            print("\n請選擇總輸出資料夾...")
            try:
                root = tk.Tk()
                root.withdraw()
                output_dir = filedialog.askdirectory(
                    title="選擇所有分析結果的總輸出資料夾"
                )
                root.destroy()
                
                if not output_dir:
                    print("⚠️ 未選擇輸出資料夾，使用當前目錄")
                    output_dir = os.getcwd()
                else:
                    print(f"✅ 已選擇總輸出資料夾：{output_dir}")
            except ImportError:
                # Django 環境中使用預設路徑
                output_dir = os.getcwd()
                print(f"網頁環境：使用預設輸出目錄：{output_dir}")   
                                    
            except Exception as e:
                print(f"GUI 錯誤：{e}")
                output_dir = os.getcwd()
                print(f"使用當前工作目錄：{output_dir}")
        else:
            if output_file_path:
                output_dir = os.path.dirname(output_file_path)
                if not output_dir:
                    output_dir = os.getcwd()
            else:
                output_dir = os.getcwd()
            print(f"使用輸出目錄：{output_dir}")

        # 確保輸出目錄存在
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                print(f"✅ 已創建輸出目錄：{output_dir}")
            except Exception as e:
                print(f"❌ 無法創建輸出目錄：{e}")
                output_dir = os.getcwd()
                print(f"改用當前工作目錄：{output_dir}")

        # 11.1 設定主要CSV輸出檔名
        current_date = datetime.now().strftime("%m%d")
        if output_file_path is None:
            output_filename = os.path.join(output_dir, f"NCEER液化分析結果_{current_date}.csv")
        else:
            output_filename = output_file_path

        try:
            final_df.to_csv(output_filename, index=False, encoding='utf-8-sig')
            print(f"\n✅ 分析完成！")
            print(f"✅ 已儲存所有結果至：{output_filename}")
        except Exception as e:
            print(f"儲存檔案錯誤：{e}")
            return final_df, lpi_summary, file_path

        # 12. 輸出詳細摘要統計
        print("\n" + "="*80)
        print("=== 最終分析摘要 ===")
        print("="*80)
        print("分析方法：NCEER(2001)")
        for well_id in well_ids:
            if well_id not in well_params:
                continue
                
            params = well_params[well_id]
            well_result = final_df[final_df['鑽孔編號'] == well_id]
            
            if len(well_result) == 0:
                continue
            
            print(f"\n鑽孔 {well_id}:")
            print(f"  TWD97座標: ({params['x']}, {params['y']})")
            print(f"  城市: {params['city']}")
            print(f"  基準地震規模 Mw: {params['base_mw']}")
            print(f"  使用地震參數: SDS={params['SDS']}, SMS={params['SMS']}")
            print(f"  分析層數: {len(well_result)}")
            
            # 顯示各情境使用的Mw值和地表加速度
            print("  各情境參數:")
            
            scenarios_info = {
                "Design": {"desc": "設計地震"},
                "MidEq": {"desc": "中小地震"}, 
                "MaxEq": {"desc": "最大地震"}
            }
            
            for scenario, info in scenarios_info.items():
                scenario_mw = get_scenario_mw(params['base_mw'], scenario)
                adjustment = earthquake_mw_adjustments[scenario]
                print(f"    {scenario} ({info['desc']}): Mw={scenario_mw:.1f} (基準{adjustment:+.1f})")
            
            # 統計液化潛能和 LPI
            for scenario in scenarios_info.keys():
                fs_col = f'FS_{scenario}'
                if fs_col in well_result.columns:
                    valid_fs = pd.to_numeric(well_result[fs_col], errors='coerce').dropna()
                    if len(valid_fs) > 0:
                        liquefaction_count = sum(valid_fs < 1.0)
                        total_lpi = lpi_summary.get(well_id, {}).get(scenario, "N/A")
                        print(f"  {scenario} 情境結果:")
                        print(f"    液化層數: {liquefaction_count}/{len(valid_fs)}")
                        print(f"    總LPI: {total_lpi}")

        print("\n程式執行完成！")


        # 13. 生成簡化報表到總輸出資料夾
        print("\n" + "="*60)
        print("=== 生成簡化報表 ===")
        print("="*60)

        simplified_reports = {}

        for scenario in ["Design", "MidEq", "MaxEq"]:
            try:
                report_file = self.generate_simplified_report(
                    final_df, 
                    output_dir=output_dir, 
                    scenario=scenario
                )
                if report_file:
                    simplified_reports[scenario] = report_file
            except Exception as e:
                print(f"生成 {scenario} 情境簡化報表時發生錯誤：{e}")

        if simplified_reports:
            print(f"\n✅ 共生成 {len(simplified_reports)} 個簡化報表：")
            for scenario, filename in simplified_reports.items():
                print(f"   {scenario} 情境：{filename}")

        # 14. 為每個鑽孔生成獨立資料夾，包含Excel報表和圖表
        print("\n" + "="*60)
        print("=== 為每個鑽孔生成資料夾（包含Excel報表和圖表）===")
        print("="*60)

        generate_individual = input("是否要為每個鑽孔生成獨立資料夾（包含Excel報表和JPG圖表）？(y/n，預設為 y): ").strip().lower()

        if generate_individual in ['', 'y', 'yes']:
            try:
                # 獲取所有鑽孔ID
                well_ids = final_df['鑽孔編號'].unique()
                
                print(f"正在為 {len(well_ids)} 個鑽孔生成獨立資料夾...")
                
                for i, well_id in enumerate(well_ids, 1):
                    print(f"\n進度 [{i}/{len(well_ids)}] 處理鑽孔：{well_id}")
                    
                    try:
                        # 1. 建立鑽孔資料夾
                        well_dir = os.path.join(output_dir, str(well_id))
                        if not os.path.exists(well_dir):
                            os.makedirs(well_dir)
                        print(f"  ✅ 已建立資料夾：{well_dir}")
                        
                        # 2. 篩選該鑽孔的資料
                        well_data = final_df[final_df['鑽孔編號'] == well_id].copy()
                        
                        if len(well_data) == 0:
                            print(f"  ⚠️ 鑽孔 {well_id} 沒有資料，跳過")
                            continue
                        
                        # 3. 生成Excel報表
                        print(f"  正在生成Excel報表...")
                        current_date = datetime.now().strftime("%m%d")
                        excel_filename = f"{well_id}_液化分析報表_{current_date}.xlsx"
                        excel_filepath = os.path.join(well_dir, excel_filename)
                        
                        # 確保導入模組
                        try:
                            from report import create_liquefaction_excel_from_dataframe
                            create_liquefaction_excel_from_dataframe(well_data, excel_filepath)
                            print(f"  ✅ Excel報表：{excel_filename}")
                        except Exception as e:
                            print(f"  ❌ Excel報表生成失敗：{e}")
                        
                        # 4. 生成圖表
                        print(f"  正在生成圖表...")
                        n_size = (5, 10)    # N值圖表大小
                        fs_size = (5, 10)   # FS圖表大小
                        
                        # 確保導入並使用正確的圖表生成器
                        try:
                            from report import LiquefactionChartGenerator
                            chart_generator = LiquefactionChartGenerator(
                                n_chart_size=n_size,
                                fs_chart_size=fs_size
                            )
                            
                            # 生成深度-N值圖表
                            chart1 = chart_generator.generate_depth_n_chart(well_data, well_id, well_dir)
                            if chart1:
                                print(f"  ✅ N值圖表：{os.path.basename(chart1)}")
                            
                            # 生成深度-FS圖表
                            chart2 = chart_generator.generate_depth_fs_chart(well_data, well_id, well_dir)
                            if chart2:
                                print(f"  ✅ FS圖表：{os.path.basename(chart2)}")
                            # 生成土壤柱狀圖
                            chart3 = chart_generator.generate_soil_column_chart(well_data, well_id, well_dir)
                            if chart3:
                                print(f"  ✅ 土壤柱狀圖：{os.path.basename(chart3)}")
                                
                        except Exception as e:
                            print(f"  ❌ 圖表生成失敗：{e}")
                            import traceback
                            print(f"     詳細錯誤：{traceback.format_exc()}")
                        
                        print(f"  ✅ 鑽孔 {well_id} 處理完成")
                        
                    except Exception as e:
                        print(f"  ❌ 處理鑽孔 {well_id} 時發生錯誤：{e}")
                        import traceback
                        print(f"     詳細錯誤：{traceback.format_exc()}")
                        continue
                
                print(f"\n🎉 所有鑽孔資料夾生成完成！")
                print(f"📁 輸出位置：{output_dir}")
                print(f"📂 每個鑽孔資料夾包含：")
                print(f"   - Excel液化分析報表")
                print(f"   - SPT-N值隨深度變化圖（限制0-20m）")
                print(f"   - 安全係數隨深度變化圖（限制0-20m）")
                print(f"   - 土壤柱狀圖（含地下水位標示）")
            except Exception as e:
                print(f"❌ 生成鑽孔資料夾時發生錯誤：{e}")
                import traceback
                print(f"詳細錯誤：{traceback.format_exc()}")
        else:
            print("跳過鑽孔資料夾生成")
        
        # 15. 生成LPI摘要報表
        print("\n" + "="*60)
        print("=== 生成LPI摘要報表 ===")
        print("="*60)

        try:
            lpi_summary_file = self.generate_lpi_summary_report(final_df, output_dir)
            if lpi_summary_file:
                print(f"✅ LPI摘要報表生成完成")
        except Exception as e:
            print(f"生成LPI摘要報表時發生錯誤：{e}")

        return final_df, lpi_summary, file_path
"""
        # 15. 生成JPG圖表 - 改善版本
        print("\n" + "="*60)
        print("=== 生成JPG圖表 ===")
        print("="*60)

        # 詢問是否要生成圖表
        generate_charts = input("是否要為每個鑽孔生成JPG格式的折線圖？(y/n，預設為 y): ").strip().lower()

        if generate_charts in ['', 'y', 'yes']:
            try:
                print(f"開始生成圖表，輸出目錄：{output_dir}")
                
                n_size = (5, 10)    # N值圖表：寬12英寸，高10英寸
                fs_size = (5, 10)   # FS圖表：寬14英寸，高10英寸
                # 先導入圖表生成模組
                from report import generate_all_wells_charts
                
                # 生成所有鑽孔的圖表
                chart_files = generate_all_wells_charts(final_df, output_dir,
                                                        n_chart_size= n_size,
                                                        fs_chart_size=fs_size
                                                        )
                
                if chart_files:
                    print(f"\n🎉 圖表生成完成！")
                    print(f"📈 每個鑽孔生成2張圖表：")
                    print(f"   - 計算深度 vs N值關係圖")
                    print(f"   - 計算深度 vs 安全係數關係圖 (三種地震情境)")
                    print(f"📁 圖表儲存位置：{os.path.join(output_dir, '圖表')}")
                else:
                    print(f"⚠️ 未生成任何圖表，請檢查資料完整性")
                
            except Exception as e:
                print(f"❌ 生成圖表時發生錯誤：{e}")
                import traceback
                print(f"詳細錯誤：{traceback.format_exc()}")
        else:
            print("跳過JPG圖表生成")

        return final_df, lpi_summary, file_path
"""


if __name__ == "__main__":
    input_path = get_input_file(None)
    NCEER_analyzer = NCEER()
    NCEER_analyzer.NCEER_main(show_gui=True, input_file_path=input_path)