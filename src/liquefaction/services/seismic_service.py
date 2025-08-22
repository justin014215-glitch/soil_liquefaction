# src/liquefaction/services/seismic_service.py
import math
import os
import json
import time
import logging
import geopandas as gpd
from typing import Dict, Any, Optional, Tuple
from django.conf import settings
from pathlib import Path
from pyproj import Transformer
from geopy.geocoders import Nominatim
from shapely.geometry import Point
import pandas as pd

logger = logging.getLogger(__name__)


class SeismicParameterService:
    """地震參數查詢服務 - 使用 HBF 搜尋方法"""
    
    def __init__(self):
        self.taiwan_seismic_data = self._load_json_data("taiwan_seismic_data.json")
        self.general_zone_coefficients = self._load_json_data("general_zone_seismic_coefficient.json")
        self.taipei_basin_zones = self._load_json_data("taipei_basin_zone.json")
        self.fault_distance_parameters = self._load_json_data("斷層參數.json")
        
        # 台北盆地微分區係數
        self.taipei_basin_seismic_coefficients = {
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
        self.city_mw_mapping = {
            "基隆市": 7.3, "新北市": 7.3, "臺北市": 7.3, "宜蘭縣": 7.3, "花蓮縣": 7.3, "台東縣": 7.3,
            "桃園市": 7.1, "台中市": 7.1, "彰化縣": 7.1, "南投縣": 7.1, "雲林縣": 7.1,
            "嘉義縣": 7.1, "台南市": 7.1, "高雄市": 7.1,
            "新竹縣": 6.9, "苗栗縣": 6.9, "屏東縣": 6.9,
            "澎湖縣": 6.7, "金門縣": 6.7, "馬祖縣": 6.7
        }
    
    def _get_parameter_file_path(self, filename: str) -> str:
        """取得參數檔案的絕對路徑"""
        try:
            return settings.BASE_DIR.parent / "參數" / filename
        except:
            # 非 Django 環境
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent.parent
            return project_root / "參數" / filename
    
    def _load_json_data(self, filename: str) -> Dict[str, Any]:
        """載入JSON參數檔案"""
        file_path = self._get_parameter_file_path(filename)
        
        if not os.path.exists(file_path):
            logger.warning(f"找不到檔案：{file_path}")
            return {}
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功載入檔案：{file_path}")
                return data
        except Exception as e:
            logger.error(f"載入檔案失敗 {file_path}: {e}")
            return {}
    
    def tw97_to_wgs84(self, x: float, y: float) -> Tuple[float, float]:
        """將 TWD97 坐標轉換為 WGS84（經緯度）"""
        transformer = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lat, lon
    
    def normalize_address_name(self, name: str) -> str:
        """標準化地址名稱，移除常見的地址變體"""
        if not name:
            return ""
        
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
    
    def enhanced_geocoding(self, lat: float, lon: float) -> Dict[str, str]:
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
                    city = self.normalize_address_name(addr[field])
                    break
            
            # 特別處理桃園市和臺南市
            if city in ["桃園市", "臺南市"]:
                return self.parse_taoyuan_tainan_address(full_address, addr, city)
            
            # 其他縣市的原有處理邏輯
            district = None
            for field in ["suburb", "town", "city_district", "municipality", "neighbourhood"]:
                if addr.get(field):
                    district = self.normalize_address_name(addr[field])
                    break
            
            # 取得里的資訊
            village = None
            for field in ["neighbourhood", "hamlet", "quarter"]:
                if addr.get(field):
                    village = self.normalize_address_name(addr[field])
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
    
    def parse_taoyuan_tainan_address(self, full_address: str, addr: dict, city: str) -> Dict[str, str]:
        """專門解析桃園市和臺南市的地址"""
        logger.info(f"使用專門解析器處理 {city} 地址")
        
        # 方法1：從完整地址字串解析
        district, village = self.parse_address_string(full_address, city)
        
        if district:
            logger.info(f"從地址字串解析成功：{city} -> {district} -> {village}")
            return {
                "city": city,
                "district": district,
                "village": village,
                "full_address": full_address
            }
        
        # 方法2：從API回傳的結構化資料解析
        district, village = self.parse_structured_address(addr, city)
        
        logger.info(f"從結構化資料解析：{city} -> {district} -> {village}")
        return {
            "city": city,
            "district": district,
            "village": village,
            "full_address": full_address
        }
    
    def parse_address_string(self, full_address: str, city: str) -> Tuple[Optional[str], Optional[str]]:
        """從完整地址字串解析區和里"""
        import re
        
        try:
            # 移除縣市名稱，專注於後面的部分
            address_parts = full_address.replace(city, "").strip()
            
            # 使用正則表達式找出區和里
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
    
    def parse_structured_address(self, addr: dict, city: str) -> Tuple[Optional[str], Optional[str]]:
        """從結構化地址資料解析區和里"""
        district = None
        village = None
        
        # 優先順序調整：先找區級行政單位
        district_fields = ["suburb", "city_district", "town", "municipality"]
        village_fields = ["neighbourhood", "hamlet", "quarter"]
        
        # 找區
        for field in district_fields:
            if addr.get(field):
                candidate = self.normalize_address_name(addr[field])
                # 確保是區而不是里
                if candidate.endswith('區') and not candidate.endswith('里'):
                    district = candidate
                    logger.info(f"從 {field} 欄位找到區：{district}")
                    break
        
        # 找里
        for field in village_fields:
            if addr.get(field):
                candidate = self.normalize_address_name(addr[field])
                # 確保是里而不是區，且不是已經被識別為區的名稱
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
    
    def find_taipei_basin_zone(self, city: str, district: str, village: str = None) -> Optional[str]:
        """尋找台北盆地微分區"""
        logger.info(f"尋找台北盆地微分區：{city}-{district}-{village}")
        
        # 標準化地址名稱
        city = self.normalize_address_name(city)
        district = self.normalize_address_name(district)
        if village:
            village = self.normalize_address_name(village)
        
        # 只處理台北市和新北市
        if city not in ['臺北市', '新北市']:
            logger.info(f"{city} 不在台北盆地範圍內")
            return None
        
        # 檢查該縣市是否在台北盆地資料中
        if city not in self.taipei_basin_zones:
            logger.warning(f"在台北盆地資料中找不到 {city}")
            return None
        
        # 取得該縣市的資料
        city_data = self.taipei_basin_zones[city]
        
        # 移除「區」字後綴進行比對
        district_key = district.replace('區', '') if district.endswith('區') else district
        
        # 在該縣市的行政區中尋找匹配
        matching_districts = []
        for dist_key in city_data.keys():
            if (district_key in dist_key or 
                dist_key in district_key or
                district in dist_key or
                dist_key in district):
                matching_districts.append(dist_key)
        
        if not matching_districts:
            logger.warning(f"在台北盆地資料中找不到 {city} 的 {district}")
            return None
        
        # 使用最匹配的區
        best_match_district = min(matching_districts, key=lambda x: abs(len(x) - len(district_key)))
        district_zones = city_data[best_match_district]
        
        # 如果有里的資訊，嘗試找到對應的微分區
        if village:
            for zone_name, village_list in district_zones.items():
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
        
        # 如果沒有里的資訊或找不到精確匹配，回傳第一個微分區
        default_zone = list(district_zones.keys())[0]
        logger.info(f"使用預設微分區：{default_zone}")
        return default_zone
    
    def get_fault_based_parameters(self, fault_name: str, distance_km: float, city: str, district: str) -> Optional[Dict[str, Any]]:
        """根據斷層距離取得地震參數"""
        # 條件：若 r>14 則不需要查詢與斷層相關的參數
        if distance_km > 14:
            logger.info(f"距離 {distance_km:.2f} km > 14 km，跳過斷層參數查詢")
            return None
        
        # 尋找匹配的斷層記錄
        matching_records = []
        for record in self.fault_distance_parameters:
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
        
        # 進行距離內插（簡化版本，使用最接近的距離範圍）
        distance_ranges = {
            "<=1": 1.0, "3": 3.0, "5": 5.0, "7": 7.0, 
            "9": 9.0, "11": 11.0, "13": 13.0, ">=14": 14.0
        }
        
        # 找到最適合的距離範圍
        best_record = None
        min_diff = float('inf')
        
        for record in matching_records:
            r_range = record["r"]
            if r_range in distance_ranges:
                range_distance = distance_ranges[r_range]
                diff = abs(distance_km - range_distance)
                if diff < min_diff:
                    min_diff = diff
                    best_record = record
        
        if best_record:
            return {
                "斷層名稱": fault_name,
                "r": best_record["r"],
                "對應鄉鎮": f"[{city}] {district}",
                "SDS": float(best_record["SDS"]),
                "SD1": float(best_record["SD1"]),
                "SMS": float(best_record["SMS"]),
                "SM1": float(best_record["SM1"]),
                "內插方法": f"最接近距離匹配 (差距={min_diff:.2f}km)"
            }
        
        return None
    
    def compute_distances_to_faults(self, x: float, y: float, source_epsg: str, faults_gdf: gpd.GeoDataFrame) -> dict:
        """計算點到各斷層線的最近距離"""
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
        elif 'E_NAME' in faults_proj.columns:
            name_col = 'E_NAME'
        elif 'Fault_No_3' in faults_proj.columns:
            name_col = 'Fault_No_3'
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
            
            # 如果該斷層已存在，保留較近的距離
            if fault_name in fault_distances:
                fault_distances[fault_name] = min(fault_distances[fault_name], distance_km)
            else:
                fault_distances[fault_name] = distance_km
        
        return fault_distances
    
    def query_seismic_parameters(self, twd97_x: float, twd97_y: float, use_fault_data: bool = False, fault_gdf=None) -> Dict[str, Any]:
        """
        查詢指定座標的地震參數 - 使用 HBF 搜尋邏輯
        
        Args:
            twd97_x: TWD97 X座標
            twd97_y: TWD97 Y座標
            use_fault_data: 是否使用斷層資料
            fault_gdf: 斷層GeoDataFrame
            
        Returns:
            地震參數字典
        """
        try:
            print(f"正在查詢座標 ({twd97_x}, {twd97_y}) 的地震參數...")
            
            # 檢查座標是否在台灣範圍內
            if not (160000 <= twd97_x <= 380000) or not (2420000 <= twd97_y <= 2800000):
                return {
                    'success': False,
                    'error': '座標超出台灣地區範圍',
                    'coordinates': {'x': twd97_x, 'y': twd97_y}
                }
            
            # 步驟1: 將 TWD97 座標轉換為 WGS84
            lat, lon = self.tw97_to_wgs84(twd97_x, twd97_y)
            print(f"  轉換為 WGS84: ({lat:.6f}, {lon:.6f})")
            
            # 步驟2: 使用增強地理編碼獲取地址資訊
            try:
                geo_info = self.enhanced_geocoding(lat, lon)
                city = geo_info.get('city')
                district = geo_info.get('district') 
                village = geo_info.get('village')
                
                print(f"  地理編碼結果: {city} - {district} - {village}")
                
                if not city:
                    print(f"  無法獲取城市資訊")
                    return {
                        'success': False,
                        'error': '無法獲取地理位置資訊',
                        'coordinates': {'x': twd97_x, 'y': twd97_y}
                    }
                    
            except Exception as e:
                print(f"  地理編碼失敗: {e}")
                return {
                    'success': False,
                    'error': f'地理編碼失敗: {str(e)}',
                    'coordinates': {'x': twd97_x, 'y': twd97_y}
                }
            
            # 步驟3: 新增斷層距離參數查詢 (最高優先順序)
            result = None
            
            # 台北地區跳過斷層計算
            taipei_regions = ['臺北市', '新北市']
            skip_fault_calculation = city in taipei_regions
            
            if skip_fault_calculation:
                print(f"  檢測到台北地區 ({city})，跳過斷層距離參數查詢")
            elif use_fault_data and fault_gdf is not None:
                try:
                    print(f"  正在計算斷層距離...")
                    distances = self.compute_distances_to_faults(twd97_x, twd97_y, "EPSG:3826", fault_gdf)
                    
                    if distances:
                        nearest_fault, min_distance = min(distances.items(), key=lambda item: item[1])
                        print(f"  最近斷層: {nearest_fault} ({min_distance:.2f} km)")
                        
                        # 如果距離≤14km，查詢斷層距離參數
                        if min_distance <= 14:
                            print(f"  查詢斷層距離參數...")
                            fault_params = self.get_fault_based_parameters(nearest_fault, min_distance, city, district)
                            if fault_params:
                                # 獲取基準地震規模
                                base_mw = self.city_mw_mapping.get(city, 7.0)
                                
                                result = {
                                    'success': True,
                                    'coordinates': {'x': twd97_x, 'y': twd97_y},
                                    'seismic_parameters': {
                                        'sds': fault_params.get('SDS'),
                                        'sms': fault_params.get('SMS'),
                                        'sd1': fault_params.get('SD1'),
                                        'sm1': fault_params.get('SM1'),
                                        'base_mw': base_mw,
                                        'nearby_faults': f"{nearest_fault} ({min_distance:.2f} km)"
                                    },
                                    'site_parameters': {
                                        'vs30': self._estimate_vs30(twd97_x, twd97_y),
                                        'site_class': None
                                    },
                                    'administrative': {
                                        'city': city,
                                        'district': district or "",
                                        'village': village or ""
                                    },
                                    'data_source': f'斷層距離參數 (r={fault_params.get("r", "")})'
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
                taipei_zone = self.find_taipei_basin_zone(city, district, village)
                if taipei_zone:
                    print(f"  找到台北盆地微分區: {taipei_zone}")
                    coefficients = self.taipei_basin_seismic_coefficients.get(taipei_zone, {})
                    base_mw = self.city_mw_mapping.get(city, 7.0)
                    
                    result = {
                        'success': True,
                        'coordinates': {'x': twd97_x, 'y': twd97_y},
                        'seismic_parameters': {
                            'sds': coefficients.get('SD_S'),
                            'sms': coefficients.get('SM_S'),
                            'sd1': coefficients.get('SD1', None),
                            'sm1': coefficients.get('SM1', None),
                            'base_mw': base_mw,
                            'nearby_faults': ""
                        },
                        'site_parameters': {
                            'vs30': self._estimate_vs30(twd97_x, twd97_y),
                            'site_class': None
                        },
                        'administrative': {
                            'city': city,
                            'district': district,
                            'village': village or "",
                            'taipei_zone': taipei_zone
                        },
                        'data_source': '台北盆地微分區'
                    }
            
            # 步驟5: 如果沒有找到台北盆地資料，查詢一般震區資料
            if not result:
                print(f"  查詢一般震區資料...")
                city_data = self.general_zone_coefficients.get(city, {})
                if city_data and district:
                    district_data = city_data.get(district, {})
                    if district_data and village:
                        village_data = district_data.get(village, {})
                        if village_data:
                            base_mw = self.city_mw_mapping.get(city, 7.0)
                            
                            result = {
                                'success': True,
                                'coordinates': {'x': twd97_x, 'y': twd97_y},
                                'seismic_parameters': {
                                    'sds': village_data.get('SDS'),
                                    'sms': village_data.get('SMS'),
                                    'sd1': village_data.get('SD1'),
                                    'sm1': village_data.get('SM1'),
                                    'base_mw': base_mw,
                                    'nearby_faults': village_data.get('鄰近之斷層', "")
                                },
                                'site_parameters': {
                                    'vs30': self._estimate_vs30(twd97_x, twd97_y),
                                    'site_class': None
                                },
                                'administrative': {
                                    'city': city,
                                    'district': district,
                                    'village': village
                                },
                                'data_source': '一般震區資料'
                            }
            
            # 步驟6: 如果還是沒有找到，使用預設值
            if not result:
                print(f"  使用預設地震參數")
                base_mw = self.city_mw_mapping.get(city, 7.0)
                
                result = {
                    'success': True,
                    'coordinates': {'x': twd97_x, 'y': twd97_y},
                    'seismic_parameters': {
                        'sds': 0.6,
                        'sms': 0.8,
                        'sd1': None,
                        'sm1': None,
                        'base_mw': base_mw,
                        'nearby_faults': ""
                    },
                    'site_parameters': {
                        'vs30': self._estimate_vs30(twd97_x, twd97_y),
                        'site_class': None
                    },
                    'administrative': {
                        'city': city,
                        'district': district or "",
                        'village': village or ""
                    },
                    'data_source': '預設值'
                }
            
            # 計算場址分類
            if result and result['site_parameters']['vs30']:
                result['site_parameters']['site_class'] = self._determine_site_class(
                    result['site_parameters']['vs30']
                )
            
            print(f"  查詢成功：{result['administrative']['city']} - {result['administrative']['district']}")
            return result
            
        except Exception as e:
            logger.error(f"地震參數查詢錯誤: {str(e)}")
            return {
                'success': False,
                'error': f'查詢過程發生錯誤: {str(e)}',
                'coordinates': {'x': twd97_x, 'y': twd97_y}
            }
    
    def _estimate_vs30(self, x: float, y: float) -> float:
        """估算 Vs30 值"""
        # 簡化的 Vs30 估算，實際應該使用地質資料
        # 基於地理位置做簡單估算
        
        # 山區通常有較高的 Vs30
        if y > 2750000:  # 北部山區
            base_vs30 = 600
        elif 2650000 <= y <= 2750000:  # 中部地區
            base_vs30 = 400
        elif y < 2550000:  # 南部地區
            base_vs30 = 350
        else:  # 其他地區
            base_vs30 = 450
        
        # 加入一些隨機變化（基於座標）
        variation = (x % 1000 + y % 1000) / 1000 * 100 - 50
        vs30 = max(200, min(800, base_vs30 + variation))
        
        return round(vs30, 1)
    
    def _determine_site_class(self, vs30: float) -> str:
        """根據 Vs30 判定地盤分類"""
        if vs30 >= 760:
            return 'A'
        elif vs30 >= 360:
            return 'B'
        elif vs30 >= 180:
            return 'C'
        elif vs30 >= 120:
            return 'D'
        else:
            return 'E'
    
    def batch_query_seismic_parameters(self, coordinates: list, use_fault_data: bool = False, fault_gdf=None) -> Dict[str, Any]:
        """
        批次查詢多個座標的地震參數
        
        Args:
            coordinates: 座標列表 [{'x': float, 'y': float, 'borehole_id': str}, ...]
            use_fault_data: 是否使用斷層資料
            fault_gdf: 斷層GeoDataFrame
            
        Returns:
            批次查詢結果
        """
        results = {}
        errors = []
        
        for coord in coordinates:
            try:
                borehole_id = coord.get('borehole_id', 'unknown')
                result = self.query_seismic_parameters(
                    coord['x'], coord['y'], 
                    use_fault_data=use_fault_data, 
                    fault_gdf=fault_gdf
                )
                results[borehole_id] = result
                
                if not result['success']:
                    errors.append(f"鑽孔 {borehole_id}: {result['error']}")
                    
            except Exception as e:
                error_msg = f"鑽孔 {coord.get('borehole_id', 'unknown')} 查詢錯誤: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        return {
            'success': len(errors) == 0,
            'results': results,
            'errors': errors,
            'total_queried': len(coordinates),
            'success_count': len([r for r in results.values() if r.get('success', False)])
        }