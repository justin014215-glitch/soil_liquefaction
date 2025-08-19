# src/liquefaction/utils/csv_parser.py
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class CSVParser:
    """CSV 檔案解析器，用於解析鑽孔資料"""
    
    # 預期的欄位對應（支援多種命名方式）
    FIELD_MAPPING = {
        'borehole_id': ['鑽孔編號', '孔號', 'borehole_id', 'hole_id', 'ID'],
        'twd97_x': ['TWD97_X', 'X座標', 'X', 'twd97_x', 'longitude'],
        'twd97_y': ['TWD97_Y', 'Y座標', 'Y', 'twd97_y', 'latitude'],
        'surface_elevation': ['地表高程', '鑽孔地表高程', '高程', 'elevation', 'surface_elevation'],
        'water_depth': ['地下水位', '水位深度', 'water_depth', 'groundwater_depth'],
        'city': ['縣市', '城市', 'city'],
        'district': ['鄉鎮區', '區', 'district'],
        'village': ['里', '村', 'village'],
        'top_depth': ['上限深度', '上限深度(m)', '上限深度(公尺)', '頂深度', 'top_depth', 'depth_from'],
        'bottom_depth': ['下限深度', '下限深度(m)', '下限深度(公尺)', '底深度', 'bottom_depth', 'depth_to'],
        'sample_id': ['取樣編號', '樣品編號', 'sample_id', 'sample_no'],
        'uscs': ['USCS', '土壤分類', 'soil_type', 'classification', '統一土壤分類'],
        'spt_n': ['SPT_N', 'SPT-N', 'N值', 'spt_n', 'N_value'],
        'unit_weight': ['單位重', '統體單位重(t/m3)', 'unit_weight', 'gamma'],
        'water_content': ['含水量', '含水率', 'water_content', 'moisture_content'],
        'gravel_percent': ['礫石含量', '礫石%', 'gravel_percent', 'gravel'],
        'sand_percent': ['砂土含量', '砂%', 'sand_percent', 'sand'],
        'silt_percent': ['粉土含量', '粉土%', 'silt_percent', 'silt'],
        'clay_percent': ['黏土含量', '黏土%', 'clay_percent', 'clay'],
        'fines_content': ['細料含量', '細料%', 'fines_content', 'fines'],
        'plastic_index': ['塑性指數', 'PI', 'plastic_index', 'plasticity_index'],
    }
    
    def __init__(self):
        self.column_mapping = {}
        self.parsed_data = {}
        self.errors = []
        self.warnings = []
    
    def parse_csv(self, file_path: str, encoding: str = 'utf-8') -> Dict[str, Any]:
        """
        解析 CSV 檔案
        
        Args:
            file_path: CSV 檔案路徑
            encoding: 檔案編碼
            
        Returns:
            解析結果字典
        """
        try:
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
                'column_mapping': self.column_mapping
            }
            
        except Exception as e:
            logger.error(f"CSV 解析錯誤: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'warnings': self.warnings,
                'errors': self.errors
            }
    
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
        """解析土層資料"""
        soil_layer = {'borehole_id': borehole_id}
        
        try:
            # 必要欄位
            soil_layer['top_depth'] = float(row[self.column_mapping['top_depth']])
            soil_layer['bottom_depth'] = float(row[self.column_mapping['bottom_depth']])
            
            # 驗證深度邏輯
            if soil_layer['top_depth'] >= soil_layer['bottom_depth']:
                self.warnings.append(f"鑽孔 {borehole_id}: 深度邏輯錯誤，上限深度應小於下限深度")
                return None
            
            # 選填欄位
            optional_fields = ['sample_id', 'uscs', 'spt_n', 'unit_weight', 'water_content',
                             'gravel_percent', 'sand_percent', 'silt_percent', 'clay_percent',
                             'fines_content', 'plastic_index']
            
            for field in optional_fields:
                if field in self.column_mapping:
                    value = row[self.column_mapping[field]]
                    if pd.notna(value) and str(value).strip():
                        if field == 'spt_n':
                            # 特殊處理 N 值，因為可能是字串格式
                            try:
                                # 嘗試直接轉換
                                soil_layer[field] = float(value)
                            except (ValueError, TypeError):
                                # 如果是字串，嘗試解析
                                value_str = str(value).strip()
                                if value_str.startswith('>'):
                                    try:
                                        soil_layer[field] = float(value_str[1:])
                                    except:
                                        self.warnings.append(f"鑽孔 {borehole_id}: N值格式錯誤 ({value})")
                                else:
                                    # 嘗試從字串中提取數字
                                    import re
                                    numbers = re.findall(r'\d+\.?\d*', value_str)
                                    if numbers:
                                        try:
                                            soil_layer[field] = float(numbers[0])
                                        except:
                                            self.warnings.append(f"鑽孔 {borehole_id}: 無法解析N值 ({value})")
                                    else:
                                        self.warnings.append(f"鑽孔 {borehole_id}: N值格式錯誤 ({value})")
                        elif field in ['unit_weight', 'water_content', 'gravel_percent',
                                    'sand_percent', 'silt_percent', 'clay_percent', 'fines_content',
                                    'plastic_index']:
                            try:
                                soil_layer[field] = float(value)
                            except (ValueError, TypeError):
                                self.warnings.append(f"鑽孔 {borehole_id}: {field} 數值格式錯誤")
                        else:
                            soil_layer[field] = str(value).strip()
            
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