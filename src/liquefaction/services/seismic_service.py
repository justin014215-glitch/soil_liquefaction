# src/liquefaction/services/seismic_service.py
import math
import os
from typing import Dict, Any, Optional, Tuple
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class SeismicParameterService:
    """地震參數查詢服務"""
    
    def __init__(self):
        self.seismic_data = self._load_seismic_data()
    
    def _load_seismic_data(self) -> Dict[str, Any]:
        """載入台灣地震參數資料"""
        # 這裡使用簡化的地震參數資料
        # 實際應用中應該從官方資料庫或 shapefile 中讀取
        return {
            # 台北市
            'taipei': {
                'regions': [
                    {
                        'name': '台北市',
                        'bounds': {'x_min': 290000, 'x_max': 310000, 'y_min': 2760000, 'y_max': 2780000},
                        'sds': 0.8, 'sms': 1.2, 'sd1': 0.5, 'sm1': 0.75,
                        'base_mw': 6.5, 'nearby_faults': '山腳斷層'
                    }
                ]
            },
            # 新北市
            'new_taipei': {
                'regions': [
                    {
                        'name': '新北市',
                        'bounds': {'x_min': 280000, 'x_max': 320000, 'y_min': 2740000, 'y_max': 2790000},
                        'sds': 0.75, 'sms': 1.15, 'sd1': 0.48, 'sm1': 0.72,
                        'base_mw': 6.4, 'nearby_faults': '山腳斷層、新莊斷層'
                    }
                ]
            },
            # 桃園市
            'taoyuan': {
                'regions': [
                    {
                        'name': '桃園市',
                        'bounds': {'x_min': 270000, 'x_max': 310000, 'y_min': 2720000, 'y_max': 2760000},
                        'sds': 0.7, 'sms': 1.1, 'sd1': 0.45, 'sm1': 0.68,
                        'base_mw': 6.3, 'nearby_faults': '新城斷層'
                    }
                ]
            },
            # 台中市
            'taichung': {
                'regions': [
                    {
                        'name': '台中市',
                        'bounds': {'x_min': 190000, 'x_max': 230000, 'y_min': 2660000, 'y_max': 2700000},
                        'sds': 0.85, 'sms': 1.25, 'sd1': 0.52, 'sm1': 0.78,
                        'base_mw': 6.6, 'nearby_faults': '車籠埔斷層'
                    }
                ]
            },
            # 高雄市
            'kaohsiung': {
                'regions': [
                    {
                        'name': '高雄市',
                        'bounds': {'x_min': 180000, 'x_max': 220000, 'y_min': 2500000, 'y_max': 2540000},
                        'sds': 0.9, 'sms': 1.3, 'sd1': 0.55, 'sm1': 0.82,
                        'base_mw': 6.7, 'nearby_faults': '旗山斷層'
                    }
                ]
            },
            # 預設值（台灣其他地區）
            'default': {
                'regions': [
                    {
                        'name': '台灣地區',
                        'bounds': {'x_min': 160000, 'x_max': 380000, 'y_min': 2420000, 'y_max': 2800000},
                        'sds': 0.6, 'sms': 1.0, 'sd1': 0.4, 'sm1': 0.6,
                        'base_mw': 6.2, 'nearby_faults': '未指定'
                    }
                ]
            }
        }
    
    def query_seismic_parameters(self, twd97_x: float, twd97_y: float) -> Dict[str, Any]:
        """
        查詢指定座標的地震參數
        
        Args:
            twd97_x: TWD97 X座標
            twd97_y: TWD97 Y座標
            
        Returns:
            地震參數字典
        """
        try:
            # 檢查座標是否在台灣範圍內
            if not self._is_in_taiwan(twd97_x, twd97_y):
                return {
                    'success': False,
                    'error': '座標超出台灣地區範圍',
                    'coordinates': {'x': twd97_x, 'y': twd97_y}
                }
            
            # 查詢對應的地震參數
            seismic_params = self._find_seismic_parameters(twd97_x, twd97_y)
            
            if seismic_params:
                # 計算場址相關參數
                vs30 = self._estimate_vs30(twd97_x, twd97_y)
                site_class = self._determine_site_class(vs30)
                
                # 取得行政區域資訊
                admin_info = self._get_administrative_info(twd97_x, twd97_y)
                
                result = {
                    'success': True,
                    'coordinates': {'x': twd97_x, 'y': twd97_y},
                    'seismic_parameters': seismic_params,
                    'site_parameters': {
                        'vs30': vs30,
                        'site_class': site_class
                    },
                    'administrative': admin_info,
                    'data_source': '台灣地震參數資料庫（簡化版）'
                }
                
                return result
            else:
                return {
                    'success': False,
                    'error': '無法找到對應的地震參數',
                    'coordinates': {'x': twd97_x, 'y': twd97_y}
                }
                
        except Exception as e:
            logger.error(f"地震參數查詢錯誤: {str(e)}")
            return {
                'success': False,
                'error': f'查詢過程發生錯誤: {str(e)}',
                'coordinates': {'x': twd97_x, 'y': twd97_y}
            }
    
    def _is_in_taiwan(self, x: float, y: float) -> bool:
        """檢查座標是否在台灣範圍內"""
        return (160000 <= x <= 380000) and (2420000 <= y <= 2800000)
    
    def _find_seismic_parameters(self, x: float, y: float) -> Optional[Dict[str, Any]]:
        """根據座標查找地震參數"""
        # 依序檢查各地區
        for region_key, region_data in self.seismic_data.items():
            if region_key == 'default':
                continue
                
            for region in region_data['regions']:
                bounds = region['bounds']
                if (bounds['x_min'] <= x <= bounds['x_max'] and 
                    bounds['y_min'] <= y <= bounds['y_max']):
                    return {
                        'region_name': region['name'],
                        'sds': region['sds'],
                        'sms': region['sms'],
                        'sd1': region['sd1'],
                        'sm1': region['sm1'],
                        'base_mw': region['base_mw'],
                        'nearby_faults': region['nearby_faults']
                    }
        
        # 如果沒有找到特定地區，使用預設值
        default_region = self.seismic_data['default']['regions'][0]
        return {
            'region_name': default_region['name'],
            'sds': default_region['sds'],
            'sms': default_region['sms'],
            'sd1': default_region['sd1'],
            'sm1': default_region['sm1'],
            'base_mw': default_region['base_mw'],
            'nearby_faults': default_region['nearby_faults']
        }
    
    def _estimate_vs30(self, x: float, y: float) -> float:
        """估算 Vs30 值"""
        # 簡化的 Vs30 估算，實際應該使用地質資料
        # 這裡基於地理位置做簡單估算
        
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
    
    def _get_administrative_info(self, x: float, y: float) -> Dict[str, str]:
        """取得行政區域資訊"""
        # 簡化的行政區域判定
        admin_regions = {
            # 台北市
            (290000, 310000, 2760000, 2780000): {'city': '台北市', 'district': '信義區', 'village': ''},
            # 新北市
            (280000, 320000, 2740000, 2790000): {'city': '新北市', 'district': '板橋區', 'village': ''},
            # 桃園市
            (270000, 310000, 2720000, 2760000): {'city': '桃園市', 'district': '桃園區', 'village': ''},
            # 台中市
            (190000, 230000, 2660000, 2700000): {'city': '台中市', 'district': '西屯區', 'village': ''},
            # 高雄市
            (180000, 220000, 2500000, 2540000): {'city': '高雄市', 'district': '前金區', 'village': ''},
        }
        
        for bounds, admin_info in admin_regions.items():
            x_min, x_max, y_min, y_max = bounds
            if x_min <= x <= x_max and y_min <= y <= y_max:
                return admin_info
        
        # 預設值
        return {'city': '台灣', 'district': '', 'village': ''}
    
    def batch_query_seismic_parameters(self, coordinates: list) -> Dict[str, Any]:
        """
        批次查詢多個座標的地震參數
        
        Args:
            coordinates: 座標列表 [{'x': float, 'y': float, 'borehole_id': str}, ...]
            
        Returns:
            批次查詢結果
        """
        results = {}
        errors = []
        
        for coord in coordinates:
            try:
                borehole_id = coord.get('borehole_id', 'unknown')
                result = self.query_seismic_parameters(coord['x'], coord['y'])
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