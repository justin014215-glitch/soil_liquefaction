# src/liquefaction/utils/csv_parser.py (更新版)
import pandas as pd
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class CSVParser:
    """CSV解析器 - 支援擴展的土層參數"""
    
    def __init__(self):
        # 定義欄位映射 - 支援多種可能的欄位名稱
        self.field_mappings = {
            # 基本資訊
            'project_name': ['計畫名稱', 'project_name', '專案名稱', '計劃名稱'],
            'borehole_id': ['鑽孔編號', 'borehole_id', 'HOLE_ID', '井號', '孔號'],
            'test_number': ['試驗編號', 'test_number', '試驗號', '實驗編號'],
            'sample_id': ['取樣編號', 'sample_id', '樣本編號', '取樣號', 'Sample_ID'],
            
            # 深度資訊
            'top_depth': ['上限深度(公尺)', '上限深度', 'top_depth', '深度上限', '上限深度(m)'],
            'bottom_depth': ['下限深度(公尺)', '下限深度', 'bottom_depth', '深度下限', '下限深度(m)'],
            
            # SPT資料
            'spt_n': ['N_value', 'SPT_N', 'N值', 'spt_n', 'N-value', 'SPT-N'],
            'n_value': ['N_value', 'N值', 'n_value'],
            
            # 土壤分類
            'uscs': ['統一土壤分類', 'USCS', 'uscs', '土壤分類', '土壤類別'],
            
            # 物理性質
            'water_content': ['含水量(%)', '含水量', 'water_content', '含水率', 'WC'],
            'liquid_limit': ['液性限度(%)', '液性限度', 'liquid_limit', 'LL', '液限'],
            'plastic_index': ['塑性指數(%)', '塑性指數', 'plastic_index', 'PI', '塑性指标'],
            'specific_gravity': ['比重', 'specific_gravity', 'Gs', '土粒比重'],
            
            # 粒徑分析
            'gravel_percent': ['礫石(%)', '礫石', 'gravel_percent', '礫石含量', 'gravel'],
            'sand_percent': ['砂(%)', '砂', 'sand_percent', '砂土含量', 'sand'],
            'silt_percent': ['粉土(%)', '粉土', 'silt_percent', '粉土含量', 'silt'],
            'clay_percent': ['黏土(%)', '黏土', 'clay_percent', '黏土含量', 'clay'],
            'fines_content': ['細料(%)', '細料', 'fines_content', '細料含量'],
            
            # 密度相關
            'unit_weight': ['統體單位重(t/m3)', '統體單位重', 'unit_weight', '單位重'],
            'bulk_density': ['統體密度(t/m3)', '統體密度', 'bulk_density', '密度'],
            'void_ratio': ['空隙比', 'void_ratio', 'e', '孔隙比'],
            
            # 粒徑分佈參數
            'd10': ['D10(mm)', 'D10', 'd10', 'D_10'],
            'd30': ['D30(mm)', 'D30', 'd30', 'D_30'],
            'd60': ['D60(mm)', 'D60', 'd60', 'D_60'],
            
            # 座標和高程
            'twd97_x': ['TWD97_X', 'TWD97X', 'X座標', 'X', 'twd97_x'],
            'twd97_y': ['TWD97_Y', 'TWD97Y', 'Y座標', 'Y', 'twd97_y'],
            'water_depth': ['water_depth(m)', 'water_depth', '地下水位', '地下水位深度', '水位深度'],
            'ground_elevation': ['鑽孔地表高程', 'ground_elevation', '地表高程', '高程', 'elevation']
        }
        
        # 必需欄位
        self.required_fields = ['borehole_id', 'top_depth', 'bottom_depth']
        
    def parse_csv(self, file_path: str) -> Dict[str, Any]:
        """解析CSV檔案"""
        try:
            # 讀取CSV檔案
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            logger.info(f"成功讀取CSV檔案，共 {len(df)} 行資料")
            
            # 清理欄位名稱
            df.columns = df.columns.str.strip()
            
            # 映射欄位名稱
            mapped_df = self._map_columns(df)
            
            # 驗證必需欄位
            validation_result = self._validate_required_fields(mapped_df)
            if not validation_result['success']:
                return validation_result
            
            # 清理和轉換資料
            cleaned_df = self._clean_data(mapped_df)
            
            # 分組處理資料
            grouped_data = self._group_data(cleaned_df)
            
            return {
                'success': True,
                'data': grouped_data,
                'total_rows': len(df),
                'processed_rows': len(cleaned_df),
                'warnings': [],
                'errors': []
            }
            
        except Exception as e:
            logger.error(f"CSV解析錯誤: {str(e)}")
            return {
                'success': False,
                'error': f'CSV檔案解析失敗: {str(e)}',
                'warnings': [],
                'errors': [str(e)]
            }
    
    def _map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """映射欄位名稱"""
        mapped_df = df.copy()
        column_mapping = {}
        
        for standard_name, possible_names in self.field_mappings.items():
            for col in df.columns:
                if col in possible_names:
                    column_mapping[col] = standard_name
                    break
        
        # 重新命名欄位
        mapped_df = mapped_df.rename(columns=column_mapping)
        
        logger.info(f"欄位映射: {column_mapping}")
        return mapped_df
    
    def _validate_required_fields(self, df: pd.DataFrame) -> Dict[str, Any]:
        """驗證必需欄位"""
        missing_fields = []
        for field in self.required_fields:
            if field not in df.columns:
                missing_fields.append(field)
        
        if missing_fields:
            # 提供可能的欄位名稱建議
            available_columns = list(df.columns)
            suggestions = {}
            for missing_field in missing_fields:
                if missing_field in self.field_mappings:
                    suggestions[missing_field] = self.field_mappings[missing_field]
            
            return {
                'success': False,
                'error': f'缺少必要欄位: {missing_fields}',
                'missing_fields': missing_fields,
                'available_columns': available_columns,
                'suggestions': suggestions,
                'warnings': [],
                'errors': [f'缺少必要欄位: {missing_fields}']
            }
        
        return {'success': True}
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """清理和轉換資料"""
        cleaned_df = df.copy()
        
        # 數值欄位清理
        numeric_fields = [
            'top_depth', 'bottom_depth', 'spt_n', 'n_value',
            'water_content', 'liquid_limit', 'plastic_index', 'specific_gravity',
            'gravel_percent', 'sand_percent', 'silt_percent', 'clay_percent', 'fines_content',
            'unit_weight', 'bulk_density', 'void_ratio',
            'd10', 'd30', 'd60', 'twd97_x', 'twd97_y', 'water_depth', 'ground_elevation'
        ]
        
        for field in numeric_fields:
            if field in cleaned_df.columns:
                cleaned_df[field] = pd.to_numeric(cleaned_df[field], errors='coerce')
        
        # 文字欄位清理
        text_fields = ['project_name', 'borehole_id', 'test_number', 'sample_id', 'uscs']
        for field in text_fields:
            if field in cleaned_df.columns:
                cleaned_df[field] = cleaned_df[field].astype(str).str.strip()
                cleaned_df[field] = cleaned_df[field].replace('nan', '')
        
        # 移除完全空白的行
        cleaned_df = cleaned_df.dropna(subset=self.required_fields, how='all')
        
        return cleaned_df
    
    def _group_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """將資料分組為鑽孔和土層"""
        boreholes = {}
        soil_layers = []
        
        # 按鑽孔分組
        for borehole_id in df['borehole_id'].unique():
            if pd.isna(borehole_id) or borehole_id == '':
                continue
                
            borehole_data = df[df['borehole_id'] == borehole_id].iloc[0]
            
            # 建立鑽孔基本資訊
            boreholes[borehole_id] = {
                'borehole_id': borehole_id,
                'twd97_x': borehole_data.get('twd97_x'),
                'twd97_y': borehole_data.get('twd97_y'),
                'water_depth': borehole_data.get('water_depth', 0),
                'surface_elevation': borehole_data.get('ground_elevation'),
                'project_name': borehole_data.get('project_name', ''),
            }
        
        # 處理每一層土壤資料
        for _, row in df.iterrows():
            if pd.isna(row['borehole_id']) or row['borehole_id'] == '':
                continue
                
            soil_layer = {
                'borehole_id': row['borehole_id'],
                'project_name': row.get('project_name', ''),
                'test_number': row.get('test_number', ''),
                'sample_id': row.get('sample_id', ''),
                'top_depth': row.get('top_depth'),
                'bottom_depth': row.get('bottom_depth'),
                'spt_n': row.get('spt_n'),
                'n_value': row.get('n_value'),
                'uscs': row.get('uscs', ''),
                'water_content': row.get('water_content'),
                'liquid_limit': row.get('liquid_limit'),
                'plastic_index': row.get('plastic_index'),
                'specific_gravity': row.get('specific_gravity'),
                'gravel_percent': row.get('gravel_percent'),
                'sand_percent': row.get('sand_percent'),
                'silt_percent': row.get('silt_percent'),
                'clay_percent': row.get('clay_percent'),
                'fines_content': row.get('fines_content'),
                'unit_weight': row.get('unit_weight'),
                'bulk_density': row.get('bulk_density'),
                'void_ratio': row.get('void_ratio'),
                'd10': row.get('d10'),
                'd30': row.get('d30'),
                'd60': row.get('d60'),
                'twd97_x': row.get('twd97_x'),
                'twd97_y': row.get('twd97_y'),
                'water_depth': row.get('water_depth'),
                'ground_elevation': row.get('ground_elevation'),
            }
            
            soil_layers.append(soil_layer)
        
        return {
            'boreholes': boreholes,
            'soil_layers': soil_layers
        }