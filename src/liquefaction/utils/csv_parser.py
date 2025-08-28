# src/liquefaction/utils/csv_parser.py
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class CSVParser:
    """CSV 檔案解析器，用於解析鑽孔資料"""
    
    # 預期的欄位對應（支援多種命名方式）
    # 修正後的 FIELD_MAPPING - 請更新您的 csv_parser.py

    FIELD_MAPPING = {
        # 基本資訊
        'borehole_id': ['鑽孔編號', '孔號', 'borehole_id', 'hole_id', 'ID'],
        'twd97_x': ['TWD97_X', 'X座標', 'X', 'twd97_x', 'longitude'],
        'twd97_y': ['TWD97_Y', 'Y座標', 'Y', 'twd97_y', 'latitude'],
        'surface_elevation': ['鑽孔地表高程', '地表高程', '高程', 'elevation', 'surface_elevation'],
        'water_depth': ['water_depth(m)', '地下水位', '水位深度', 'water_depth', 'groundwater_depth'],
        
        # 行政區域
        'city': ['縣市', '城市', 'city'],
        'district': ['鄉鎮區', '區', 'district'],
        'village': ['里', '村', 'village'],
        
        # 專案和試驗資訊
        'project_name': ['計畫名稱', '專案名稱', 'project_name'],
        'test_number': ['試驗編號', 'test_number', 'test_no'],
        'test_name_chinese': ['試驗中文名稱', '試驗名稱'],
        'test_name_english': ['試驗英文名稱', 'test_name'],
        
        # 深度資訊
        'top_depth': ['上限深度(公尺)', '上限深度(m)', '上限深度', '頂深度', 'top_depth', 'depth_from'],
        'bottom_depth': ['下限深度(公尺)', '下限深度(m)', '下限深度', '底深度', 'bottom_depth', 'depth_to'],
        
        # 樣品資訊
        'sample_id': ['取樣編號', '樣品編號', 'sample_id', 'sample_no'],
        'uscs': ['統一土壤分類', 'USCS', '土壤分類', 'soil_type', 'classification'],

        
        # SPT 資料
        'spt_n': ['N_value', 'SPT_N', 'SPT-N', 'N值', 'spt_n'],
        
        # 密度相關
        'unit_weight': ['統體單位重(t/m3)', '單位重(t/m3)', '統體單位重', '單位重', 'unit_weight', 'gamma'],
        'bulk_density': ['統體密度', 'bulk_density'],
        'dry_unit_weight': ['乾單位重(t/m3)', '乾單位重', 'dry_unit_weight'],
        
        # 物理性質
        'water_content': ['含水量(%)', '含水量', '含水率', 'water_content', 'moisture_content'],
        'water_content_rock': ['含水量(岩石)(%)', '含水量(岩石)', 'rock_water_content'],
        'liquid_limit': ['液性限度(%)', '液性限度', 'liquid_limit', 'LL'],
        'plastic_index': ['塑性指數(%)', '塑性指數', 'plastic_index', 'PI'],
        'plastic_limit': ['塑性限度(%)', '塑性限度', 'plastic_limit', 'PL'],
        'shrinkage_index': ['縮性指數(%)', '縮性指數', 'shrinkage_index'],
        'specific_gravity': ['比重', 'specific_gravity', 'Gs'],
        'specific_gravity_rock': ['比重(岩石)', '岩石比重', 'rock_specific_gravity'],
        'void_ratio': ['空隙比', 'void_ratio', 'e'],
        
        # 粒徑分析
        'gravel_percent': ['礫石(%)', '礫石含量', 'gravel_percent', 'gravel'],
        'sand_percent': ['砂(%)', '砂土含量', 'sand_percent', 'sand'],
        'silt_percent': ['粉土(%)', '粉土含量', 'silt_percent', 'silt'],
        'clay_percent': ['黏土(%)', '黏土含量', 'clay_percent', 'clay'],
        'fines_content': ['細料(%)', '細料含量', 'fines_content', 'fines'],
        
        # 粒徑分佈
        'd10': ['D10(mm)', 'D10', 'd10'],
        'd30': ['D30(mm)', 'D30', 'd30'],
        'd50': ['D50(mm)', 'D50', 'd50'],
        'd60': ['D60(mm)', 'D60', 'd60'],
        
        # 岩石相關參數
        'core_length': ['岩心長度(cm)', '岩心長度', 'core_length'],
        'core_diameter': ['岩心直徑(cm)', '岩心直徑', 'core_diameter'],
        'ucs': ['單軸壓縮強度(kg/cm2)', '單軸壓縮強度', '抗壓強度', 'ucs', 'unconfined_compression']
    }
    def __init__(self, unit_weight_unit = 't/m3'):
        self.unit_weight_unit = unit_weight_unit
        self.column_mapping = {}
        self.parsed_data = {}
        self.errors = []
        self.warnings = []
        # 新增：收集統體單位重數值用於判斷單位
        self.unit_weight_values = []
        self.detected_unit = None
    
    def parse_csv(self, file_path: str, encoding: str = 'utf-8', unit_weight_unit: str = 't/m3') -> Dict[str, Any]:
        """
        解析 CSV 檔案
        
        Args:
            file_path: CSV 檔案路徑
            encoding: 檔案編碼
            
        Returns:
            解析結果字典
        """


        if unit_weight_unit:
            self.unit_weight_unit = unit_weight_unit
        try:
            # 清空之前的數據
            self.unit_weight_values = []
            self.detected_unit = None
            # 嘗試不同編碼讀取檔案
            df = self._read_csv_with_encoding(file_path, encoding)
            
            # 建立欄位對應
            self._build_column_mapping(df.columns)
            
            # 驗證必要欄位
            missing_fields = self._validate_required_fields()
            if missing_fields:
                return {
                    'success': False,
                    'error': f"缺少必要欄位: {', '.join(missing_fields)}",
                    'missing_fields': missing_fields,
                    'available_columns': list(df.columns),
                    'warnings': self.warnings,
                    'errors': self.errors
                }
            # 解析資料
            self._parse_data(df)
            
            # 資料驗證
            self._validate_data()
            
            return {
                'success': True,
                'data': self.parsed_data,
                'warnings': self.warnings,
                'errors': self.errors,
                'column_mapping': self.column_mapping,
                'detected_unit': self.detected_unit,  # 新增
                'unit_consistency': self.detected_unit == self.unit_weight_unit  # 新增
 
            }
            
        except Exception as e:
            logger.error(f"CSV 解析錯誤: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'warnings': self.warnings,
                'errors': self.errors
            }
    
    def _detect_unit_weight_unit(self) -> str:
        """
        根據統體單位重數值範圍自動判斷單位
        
        Returns:
            判斷出的單位 ('t/m3' 或 'kN/m3')
        """
        if not self.unit_weight_values:
            return self.unit_weight_unit  # 沒有數值，返回預設單位
        
        # 過濾有效數值
        valid_values = [v for v in self.unit_weight_values if v is not None and v > 0]
        if not valid_values:
            return self.unit_weight_unit
        
        avg_value = sum(valid_values) / len(valid_values)
        min_value = min(valid_values)
        max_value = max(valid_values)
        
        # 判斷邏輯
        t_m3_score = 0
        kn_m3_score = 0
        
        # 基於平均值判斷
        if 1.0 <= avg_value <= 3.0:
            t_m3_score += 3
        elif 9.8 <= avg_value <= 30.0:
            kn_m3_score += 3
        
        # 基於範圍判斷
        if 0.8 <= min_value <= 3.5 and 1.5 <= max_value <= 4.0:
            t_m3_score += 2
        elif 8.0 <= min_value <= 35.0 and 12.0 <= max_value <= 40.0:
            kn_m3_score += 2
        
        # 基於數值分佈判斷
        t_m3_count = sum(1 for v in valid_values if 0.5 <= v <= 4.0)
        kn_m3_count = sum(1 for v in valid_values if 8.0 <= v <= 40.0)
        
        if t_m3_count > len(valid_values) * 0.7:
            t_m3_score += 1
        elif kn_m3_count > len(valid_values) * 0.7:
            kn_m3_score += 1
        
        # 判斷結果
        if t_m3_score > kn_m3_score:
            detected_unit = 't/m3'
        elif kn_m3_score > t_m3_score:
            detected_unit = 'kN/m3'
        else:
            # 無法判斷，使用預設
            detected_unit = self.unit_weight_unit
        
        return detected_unit

    def _read_csv_with_encoding(self, file_path: str, encoding: str) -> pd.DataFrame:
        """嘗試不同編碼讀取 CSV 檔案"""
        encodings = [encoding, 'utf-8', 'cp950', 'big5', 'gb2312']
        
        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc)
                logger.info(f"成功使用 {enc} 編碼讀取檔案")
                return df
            except (UnicodeDecodeError, pd.errors.EmptyDataError):
                continue
        
        raise ValueError("無法讀取 CSV 檔案，請檢查檔案格式和編碼")
    
    def _build_column_mapping(self, columns: List[str]) -> None:
        """建立欄位對應關係"""
        self.column_mapping = {}
        
        for field, possible_names in self.FIELD_MAPPING.items():
            for col in columns:
                if col.strip() in possible_names:
                    self.column_mapping[field] = col.strip()
                    break
        
        logger.info(f"欄位對應: {self.column_mapping}")
    
    def _validate_required_fields(self) -> List[str]:
        """驗證必要欄位"""
        required_fields = ['borehole_id', 'twd97_x', 'twd97_y', 'top_depth', 'bottom_depth']
        missing_fields = []
        
        for field in required_fields:
            if field not in self.column_mapping:
                missing_fields.append(field)
        
        return missing_fields
    
    def _parse_data(self, df: pd.DataFrame) -> None:
        """解析資料"""
        self.parsed_data = {
            'boreholes': {},
            'soil_layers': []
        }
        
        for index, row in df.iterrows():
            try:
                # 解析鑽孔基本資訊
                borehole_id = str(row[self.column_mapping['borehole_id']]).strip()
                
                if borehole_id not in self.parsed_data['boreholes']:
                    try:
                        self.parsed_data['boreholes'][borehole_id] = self._parse_borehole_data(row)
                    except ValueError as e:
                        if "座標資料" in str(e):
                            # 座標問題，記錄警告並跳過此鑽孔
                            warning_msg = f"跳過鑽孔 {borehole_id}: {str(e)}"
                            self.warnings.append(warning_msg)
                            logger.warning(warning_msg)
                            continue
                        else:
                            raise
                
                # 只有鑽孔資料成功解析才處理土層資訊
                if borehole_id in self.parsed_data['boreholes']:
                    soil_layer = self._parse_soil_layer_data(row, borehole_id)
                    if soil_layer:
                        self.parsed_data['soil_layers'].append(soil_layer)
                    
            except Exception as e:
                error_msg = f"第 {index + 2} 行資料解析錯誤: {str(e)}"
                self.errors.append(error_msg)
                logger.warning(error_msg)
    
    def _parse_borehole_data(self, row: pd.Series) -> Dict[str, Any]:
        """解析鑽孔資料"""
        borehole_data = {}
        
        # 必要欄位
        borehole_data['borehole_id'] = str(row[self.column_mapping['borehole_id']]).strip()
        
        # 檢查並解析座標
        try:
            x_val = row[self.column_mapping['twd97_x']]
            y_val = row[self.column_mapping['twd97_y']]
            
            # 檢查座標是否為空值或無效
            if pd.isna(x_val) or pd.isna(y_val) or str(x_val).strip() == '' or str(y_val).strip() == '':
                raise ValueError(f"座標資料缺失: X={x_val}, Y={y_val}")
            
            borehole_data['twd97_x'] = float(x_val)
            borehole_data['twd97_y'] = float(y_val)
            
            # 檢查座標是否在合理範圍內（台灣地區）
            if not (160000 <= borehole_data['twd97_x'] <= 380000) or not (2420000 <= borehole_data['twd97_y'] <= 2800000):
                self.warnings.append(f"鑽孔 {borehole_data['borehole_id']}: 座標可能超出台灣地區範圍")
                
        except (ValueError, TypeError) as e:
            # 座標無效，拋出錯誤讓上層處理
            raise ValueError(f"鑽孔 {borehole_data['borehole_id']} 座標資料無效: {str(e)}")        
        # 選填欄位
        optional_fields = ['surface_elevation', 'water_depth', 'city', 'district', 'village']

        for field in optional_fields:
            if field in self.column_mapping:
                value = row[self.column_mapping[field]]
                if pd.notna(value) and str(value).strip():
                    if field in ['surface_elevation', 'water_depth']:
                        try:
                            borehole_data[field] = float(value)
                        except (ValueError, TypeError):
                            if field == 'surface_elevation':
                                borehole_data[field] = 0.0
                                self.warnings.append(f"鑽孔 {borehole_data['borehole_id']}: 地表高程數值格式錯誤，已設為 0")
                            else:
                                borehole_data[field] = 0.0
                    else:
                        borehole_data[field] = str(value).strip()
                else:
                    # 如果沒有地表高程資料，設為 0 並提醒
                    if field == 'surface_elevation':
                        borehole_data[field] = 0.0
                        self.warnings.append(f"鑽孔 {borehole_data['borehole_id']}: 未提供地表高程，已設為 0")
            else:
                # 如果欄位不存在，地表高程設為 0 並提醒
                if field == 'surface_elevation':
                    borehole_data[field] = 0.0
                    self.warnings.append(f"鑽孔 {borehole_data['borehole_id']}: 未找到地表高程欄位，已設為 0")
        
        return borehole_data
    
    def _parse_soil_layer_data(self, row: pd.Series, borehole_id: str) -> Dict[str, Any]:
        """解析土層資料 - 修正版"""
        soil_layer = {'borehole_id': borehole_id}
        
        try:
            # 必要欄位
            soil_layer['top_depth'] = float(row[self.column_mapping['top_depth']])
            soil_layer['bottom_depth'] = float(row[self.column_mapping['bottom_depth']])
            
            # 驗證深度邏輯
            if soil_layer['top_depth'] >= soil_layer['bottom_depth']:
                self.warnings.append(f"鑽孔 {borehole_id}: 深度邏輯錯誤，上限深度應小於下限深度")
                return None
            # 檢查取樣編號篩選條件
            # ===== 新增：計算細料含量 FC =====
            if 'fines_content' not in soil_layer or not soil_layer.get('fines_content'):
                silt = soil_layer.get('silt_percent', 0)
                clay = soil_layer.get('clay_percent', 0)

                # 將可能的字串轉換成浮點數
                try:
                    if isinstance(silt, str):
                        silt = float(silt) if silt.replace('.', '', 1).isdigit() else 0
                    if isinstance(clay, str):
                        clay = float(clay) if clay.replace('.', '', 1).isdigit() else 0
                except (ValueError, AttributeError):
                    silt = 0
                    clay = 0

                # 若 silt 或 clay 都有值，計算 FC
                if silt or clay:
                    soil_layer['fines_content'] = silt + clay
                    self.warnings.append(
                        f"鑽孔 {borehole_id}: 自動計算細料含量 = 粉土({silt}) + 黏土({clay}) = {soil_layer['fines_content']}"
                    )
            # ===== FC 計算結束 =====

            if 'sample_id' in self.column_mapping:
                sample_id_value = row[self.column_mapping['sample_id']]
                if pd.notna(sample_id_value) and str(sample_id_value).strip():
                    sample_id_str = str(sample_id_value).strip()
                    
                    # 過濾條件：只保留T開頭的取樣編號
                    if not sample_id_str.upper().startswith('S'):
                        # 記錄過濾信息（可選）
                        # self.warnings.append(f"鑽孔 {borehole_id}: 過濾掉取樣編號 '{sample_id_str}' (非T開頭)")
                        return None  # 跳過這筆資料
                    else:
                        soil_layer['sample_id'] = sample_id_str

                else:
                    # 沒有取樣編號，也跳過
                    # self.warnings.append(f"鑽孔 {borehole_id}: 跳過空白取樣編號的資料")
                    return None
            else:
                # 沒有取樣編號欄位，跳過所有資料
                self.warnings.append(f"鑽孔 {borehole_id}: CSV中未找到取樣編號欄位，跳過所有資料")
                return None
            # 專案和試驗資訊
            optional_text_fields = ['project_name', 'test_number', 'sample_id', 'uscs']
            
            for field in optional_text_fields:
                if field in self.column_mapping:
                    value = row[self.column_mapping[field]]
                    if pd.notna(value) and str(value).strip() and str(value).strip() != '-':
                        soil_layer[field] = str(value).strip()
            # ===== 新增：特別處理塑性指數 NP 情況 =====
            if 'plastic_index' in self.column_mapping:
                pi_value = row[self.column_mapping['plastic_index']]
                if pd.notna(pi_value) and str(pi_value).strip() and str(pi_value).strip() != '-':
                    value_str = str(pi_value).strip().upper()
                    
                    if value_str == 'NP':
                        # NP（非塑性）設為 0，保留原始值資訊
                        soil_layer['plastic_index'] = 0
                        soil_layer['plastic_index_original'] = 'NP'
                        # 不產生警告訊息 - NP 是正常情況
                    else:
                        try:
                            # 嘗試轉換為數值
                            numeric_pi = float(value_str)
                            soil_layer['plastic_index'] = numeric_pi
                            soil_layer['plastic_index_original'] = value_str
                        except (ValueError, TypeError):
                            # 只在真正無法轉換時才警告
                            self.warnings.append(f"鑽孔 {borehole_id}: 塑性指數數值格式錯誤 ({pi_value})")
                            soil_layer['plastic_index_original'] = value_str
            # ===== 塑性指數處理結束 =====
            # SPT N值處理
            if 'spt_n' in self.column_mapping:
                value = row[self.column_mapping['spt_n']]
                if pd.notna(value) and str(value).strip() and str(value).strip() != '-':
                    try:
                        soil_layer['spt_n'] = float(value)
                    except (ValueError, TypeError):
                        value_str = str(value).strip()
                        if value_str.startswith('>'):
                            try:
                                soil_layer['spt_n'] = float(value_str[1:])
                            except:
                                self.warnings.append(f"鑽孔 {borehole_id}: N值格式錯誤 ({value})")
                        else:
                            import re
                            numbers = re.findall(r'\d+\.?\d*', value_str)
                            if numbers:
                                try:
                                    soil_layer['spt_n'] = float(numbers[0])
                                except:
                                    self.warnings.append(f"鑽孔 {borehole_id}: 無法解析N值 ({value})")
                            else:
                                self.warnings.append(f"鑽孔 {borehole_id}: N值格式錯誤 ({value})")
                                    # ===== 新增：特別處理塑性指數 NP 情況 =====
                            if field == 'plastic_index':
                                value_str = str(value).strip().upper()
                                if value_str == 'NP':
                                    # NP（非塑性）設為 0，但保留原始值資訊
                                    soil_layer[field] = 0
                                    soil_layer['plastic_index_original'] = 'NP'  # 保留原始值
                                    self.warnings.append(f"鑽孔 {borehole_id}: 塑性指數為 NP（非塑性），已轉換為 0")
                                else:
                                    try:
                                        soil_layer[field] = float(value_str)
                                        soil_layer['plastic_index_original'] = value_str  # 保留原始值
                                    except (ValueError, TypeError):
                                        self.warnings.append(f"鑽孔 {borehole_id}: 塑性指數數值格式錯誤 ({value})")
                                        soil_layer[field] = 0
                                        soil_layer['plastic_index_original'] = value_str
            
                                     # ===== 新增：如果沒有細料含量但有粉土和黏土含量，自動計算 =====
                                # 在方法最後，返回之前添加
                                if 'fines_content' not in soil_layer or not soil_layer.get('fines_content'):
                                    silt_percent = soil_layer.get('silt_percent', 0)
                                    clay_percent = soil_layer.get('clay_percent', 0)
                                    
                                    if silt_percent and clay_percent:
                                        try:
                                            silt_val = float(silt_percent) if silt_percent else 0
                                            clay_val = float(clay_percent) if clay_percent else 0
                                            soil_layer['fines_content'] = silt_val + clay_val
                                            self.warnings.append(f"鑽孔 {borehole_id}: 自動計算細料含量 = 粉土({silt_val}) + 黏土({clay_val}) = {soil_layer['fines_content']}")
                                        except (ValueError, TypeError):
                                            pass
            # 數值型欄位處理
            numeric_fields = [
                'unit_weight', 'bulk_density', 'dry_unit_weight', 'void_ratio',
                'water_content', 'water_content_rock', #'liquid_limit',
                #'plastic_index', 
                'plastic_limit', 'shrinkage_index', 'specific_gravity', 'specific_gravity_rock',
                'gravel_percent', 'sand_percent', 'silt_percent', 'clay_percent', 'fines_content',
                'd10', 'd30', 'd50', 'd60', 'core_length', 'core_diameter', 'ucs'
            ]
            
            for field in numeric_fields:
                if field in self.column_mapping:
                    value = row[self.column_mapping[field]]
                    if pd.notna(value) and str(value).strip() and str(value).strip() != '-':
                        try:
                            numeric_value = float(value)
                            soil_layer[field] = numeric_value
                            
                            # 收集統體單位重數值用於單位判斷
                            if field == 'unit_weight':
                                self.unit_weight_values.append(numeric_value)
                                              # ===== 新增：檢測 kN/m³ 單位 =====
                            # 通常 kN/m³ 的單位重數值範圍在 15-25 之間
                            # 而 kgf/m³ 或 t/m³ 會在 1.5-2.5 之間
                            if 15 <= numeric_value <= 30:
                                    # 使用 set 來避免同一鑽孔重複警告
                                    if not hasattr(self, '_kn_unit_warned_boreholes'):
                                        self._kn_unit_warned_boreholes = set()
                                    
                                    if borehole_id  in self._kn_unit_warned_boreholes:
                                        self._kn_unit_warned_boreholes.add(borehole_id)
                                        self.warnings.append(f"偵測到{borehole_id}使用kN/m³，請確認統體單位重之單位後重新上傳檔案")

                            # ===== kN/m³ 檢測結束 =====    
                        except (ValueError, TypeError):
                            self.warnings.append(f"鑽孔 {borehole_id}: {field} 數值格式錯誤 ({value})")
            
            return soil_layer
            
        except Exception as e:
            self.errors.append(f"鑽孔 {borehole_id} 土層資料解析錯誤: {str(e)}")
            return None
    
    def _validate_data(self) -> None:
        """資料驗證"""
        # 驗證座標範圍（台灣地區）
        for borehole_id, borehole in self.parsed_data['boreholes'].items():
            x, y = borehole['twd97_x'], borehole['twd97_y']
            
            # TWD97 座標範圍檢查（大約）
            if not (160000 <= x <= 380000) or not (2420000 <= y <= 2800000):
                self.warnings.append(f"鑽孔 {borehole_id}: 座標可能超出台灣地區範圍")
        
        # 驗證土層連續性
        #self._validate_layer_continuity()
    
    def _validate_layer_continuity(self) -> None:
        """驗證土層深度連續性"""
        borehole_layers = {}
        
        # 按鑽孔分組土層
        for layer in self.parsed_data['soil_layers']:
            borehole_id = layer['borehole_id']
            if borehole_id not in borehole_layers:
                borehole_layers[borehole_id] = []
            borehole_layers[borehole_id].append(layer)
        
        # 檢查每個鑽孔的土層連續性
        for borehole_id, layers in borehole_layers.items():
            if len(layers) <= 1:
                continue
                
            # 按深度排序
            layers.sort(key=lambda x: x['top_depth'])
            
            for i in range(len(layers) - 1):
                current_bottom = layers[i]['bottom_depth']
                next_top = layers[i + 1]['top_depth']
                
                if abs(current_bottom - next_top) > 0.1:  # 允許 0.1m 的誤差
                    self.warnings.append(
                        f"鑽孔 {borehole_id}: 深度 {current_bottom}m 與 {next_top}m 之間可能有間隙"
                    )
    
    def get_summary(self) -> Dict[str, Any]:
        """取得解析摘要"""
        if not self.parsed_data:
            return {}
        
        total_boreholes = len(self.parsed_data['boreholes'])
        total_layers = len(self.parsed_data['soil_layers'])
        
        # 統計分析
        layer_depths = [layer['bottom_depth'] - layer['top_depth'] 
                       for layer in self.parsed_data['soil_layers']]
        
        summary = {
            'total_boreholes': total_boreholes,
            'total_layers': total_layers,
            'average_layer_thickness': np.mean(layer_depths) if layer_depths else 0,
            'max_depth': max([layer['bottom_depth'] for layer in self.parsed_data['soil_layers']]) if self.parsed_data['soil_layers'] else 0,
            'warnings_count': len(self.warnings),
            'errors_count': len(self.errors)
        }
        
        return summary
    
    def _validate_unit_weight_consistency(self):
        """驗證統體單位重的一致性並給出警告"""
        if not self.unit_weight_values:
            return
        
        # 自動判斷單位
        self.detected_unit = self._detect_unit_weight_unit()
        
        # 與設定單位比較
        if self.detected_unit != self.unit_weight_unit:
            avg_value = sum(v for v in self.unit_weight_values if v is not None) / len([v for v in self.unit_weight_values if v is not None])
            self.warnings.append(
                f"⚠️ 單位不一致警告：CSV中的統體單位重數值（平均值: {avg_value:.2f}）"
                f"看起來是 {self.detected_unit} 單位，但專案設定為 {self.unit_weight_unit}。"
                f"請確認單位是否正確，或考慮修改專案設定。"
            )
        
        # 根據檢測到的單位進行範圍檢查
        for i, (layer, value) in enumerate(zip(self.parsed_data['soil_layers'], self.unit_weight_values)):
            if value is None:
                continue
                
            borehole_id = layer['borehole_id']
            
            if self.detected_unit == 't/m3':
                if not (0.8 <= value <= 3.5):  # 稍微放寬範圍
                    self.warnings.append(
                        f"鑽孔 {borehole_id}: 統體單位重 {value} t/m³ 可能超出合理範圍 (0.8~3.5)"
                    )
            elif self.detected_unit == 'kN/m3':
                if not (8.0 <= value <= 35.0):  # 稍微放寬範圍
                    self.warnings.append(
                        f"鑽孔 {borehole_id}: 統體單位重 {value} kN/m³ 可能超出合理範圍 (8.0~35.0)"
                    )    