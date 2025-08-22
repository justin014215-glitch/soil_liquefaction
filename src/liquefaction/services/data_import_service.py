# src/liquefaction/services/data_import_service.py
import os
import tempfile
from typing import Dict, Any, List
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile
import logging
from django.db import models 
from ..models import AnalysisProject, BoreholeData, SoilLayer
from ..utils.csv_parser import CSVParser
from django.db import models, transaction
logger = logging.getLogger(__name__)
from .seismic_service import SeismicParameterService

class DataImportService:
    """資料匯入服務"""
    
    def __init__(self, project: AnalysisProject):
        self.project = project
        self.parser = CSVParser()
        self.import_summary = {}
    
    def import_csv_data(self, csv_file: UploadedFile) -> Dict[str, Any]:
        """
        匯入 CSV 資料
        
        Args:
            csv_file: 上傳的 CSV 檔案
            
        Returns:
            匯入結果
        """
        try:
            # 建立臨時檔案
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as temp_file:
                for chunk in csv_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name
            
            try:
                # 解析 CSV 檔案
                parse_result = self.parser.parse_csv(temp_file_path)
                
                if not parse_result['success']:
                    return {
                        'success': False,
                        'error': parse_result['error'],
                        'warnings': parse_result.get('warnings', []),
                        'errors': parse_result.get('errors', [])
                    }
                
                # 匯入資料到資料庫
                import_result = self._import_to_database(parse_result['data'])
                
                # 更新專案狀態
                if import_result['success']:
                    self.project.status = 'pending'  # 等待分析
                else:
                    self.project.status = 'error'
                    self.project.error_message = import_result.get('error', '資料匯入失敗')
                
                self.project.save()
                
                # 合併結果
                result = {
                    'success': import_result['success'],
                    'summary': self.import_summary,
                    'warnings': parse_result.get('warnings', []),
                    'errors': parse_result.get('errors', []) + import_result.get('errors', [])
                }
                
                if not import_result['success']:
                    result['error'] = import_result['error']
                
                return result
                
            finally:
                # 清理臨時檔案
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    
        except Exception as e:
            logger.error(f"CSV 匯入錯誤: {str(e)}")
            return {
                'success': False,
                'error': f'檔案處理錯誤: {str(e)}',
                'warnings': [],
                'errors': []
            }
    
    # 在 data_import_service.py 中的 _import_to_database 方法更新版本

    @transaction.atomic
    def _import_to_database(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        將解析的資料匯入資料庫 - 支援擴展字段
        """
        try:
            # 清除專案的舊資料
            BoreholeData.objects.filter(project=self.project).delete()
            
            imported_boreholes = 0
            imported_layers = 0
            errors = []
            
            # 匯入鑽孔資料
            for borehole_id, borehole_data in parsed_data['boreholes'].items():
                try:
                    # 先查詢地震參數
                    seismic_service = SeismicParameterService()
                    seismic_result = seismic_service.query_seismic_parameters(
                        borehole_data['twd97_x'], 
                        borehole_data['twd97_y']
                    )
                    
                    # 準備創建鑽孔的資料
                    create_data = {
                        'project': self.project,
                        'borehole_id': borehole_data['borehole_id'],
                        'twd97_x': borehole_data['twd97_x'],
                        'twd97_y': borehole_data['twd97_y'],
                        'surface_elevation': borehole_data.get('surface_elevation'),
                        'water_depth': borehole_data.get('water_depth', 0),
                        'city': borehole_data.get('city', ''),
                        'district': borehole_data.get('district', ''),
                        'village': borehole_data.get('village', '')
                    }
                    
                    # 如果查詢地震參數成功，添加地震參數
                    if seismic_result['success']:
                        seismic_params = seismic_result['seismic_parameters']
                        site_params = seismic_result['site_parameters']
                        admin_info = seismic_result['administrative']
                        
                        create_data.update({
                            'sds': seismic_params['sds'],
                            'sms': seismic_params['sms'],
                            'sd1': seismic_params['sd1'],
                            'sm1': seismic_params['sm1'],
                            'base_mw': seismic_params['base_mw'],
                            'nearby_fault': seismic_params['nearby_faults'],
                            'vs30': site_params['vs30'],
                            'site_class': site_params['site_class'],
                            'data_source': seismic_result['data_source']
                        })
                        
                        # 如果原本沒有行政區域資料，使用查詢到的
                        if not create_data['city']:
                            create_data['city'] = admin_info['city']
                        if not create_data['district']:
                            create_data['district'] = admin_info['district']
                        if not create_data['village']:
                            create_data['village'] = admin_info['village']
                    
                    # 創建鑽孔物件
                    borehole = BoreholeData.objects.create(**create_data)
                    imported_boreholes += 1
                    logger.info(f"成功匯入鑽孔: {borehole_id}")
                    
                except Exception as e:
                    error_msg = f"鑽孔 {borehole_id} 匯入失敗: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
            # 匯入土層資料 - 支援新字段
            for layer_data in parsed_data['soil_layers']:
                try:
                    borehole = BoreholeData.objects.get(
                        project=self.project,
                        borehole_id=layer_data['borehole_id']
                    )
                    
                    # 準備土層資料，包含所有新字段
                    soil_layer_data = {
                        'borehole': borehole,
                        # 基本資訊
                        'project_name': layer_data.get('project_name', ''),
                        'borehole_id_ref': layer_data.get('borehole_id', ''),
                        'test_number': layer_data.get('test_number', ''),
                        'sample_id': layer_data.get('sample_id', ''),
                        # 深度資訊
                        'top_depth': layer_data.get('top_depth'),
                        'bottom_depth': layer_data.get('bottom_depth'),
                        # SPT資料
                        'spt_n': layer_data.get('spt_n'),
                        'n_value': layer_data.get('n_value') or layer_data.get('spt_n'),  # n_value優先，否則使用spt_n
                        # 土壤分類
                        'uscs': layer_data.get('uscs', ''),
                        # 物理性質
                        'water_content': layer_data.get('water_content'),
                        'liquid_limit': layer_data.get('liquid_limit'),
                        'plastic_index': layer_data.get('plastic_index'),
                        'specific_gravity': layer_data.get('specific_gravity'),
                        # 粒徑分析
                        'gravel_percent': layer_data.get('gravel_percent'),
                        'sand_percent': layer_data.get('sand_percent'),
                        'silt_percent': layer_data.get('silt_percent'),
                        'clay_percent': layer_data.get('clay_percent'),
                        'fines_content': layer_data.get('fines_content'),
                        # 密度相關
                        'unit_weight': layer_data.get('unit_weight'),
                        'bulk_density': layer_data.get('bulk_density'),
                        'void_ratio': layer_data.get('void_ratio'),
                        # 粒徑分佈參數
                        'd10': layer_data.get('d10'),
                        'd30': layer_data.get('d30'),
                        'd60': layer_data.get('d60'),
                        # 座標和高程（冗餘資料，會在save()中自動填充）
                        'twd97_x': layer_data.get('twd97_x'),
                        'twd97_y': layer_data.get('twd97_y'),
                        'water_depth': layer_data.get('water_depth'),
                        'ground_elevation': layer_data.get('ground_elevation'),
                    }
                    
                    # 創建土層物件
                    soil_layer = SoilLayer.objects.create(**soil_layer_data)
                    imported_layers += 1
                    
                except BoreholeData.DoesNotExist:
                    error_msg = f"找不到鑽孔 {layer_data['borehole_id']}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    
                except Exception as e:
                    error_msg = f"土層資料匯入失敗 ({layer_data['borehole_id']}): {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
            # 建立匯入摘要
            self.import_summary = {
                'imported_boreholes': imported_boreholes,
                'imported_layers': imported_layers,
                'total_boreholes': len(parsed_data['boreholes']),
                'total_layers': len(parsed_data['soil_layers']),
                'success_rate_boreholes': (imported_boreholes / len(parsed_data['boreholes']) * 100) if parsed_data['boreholes'] else 0,
                'success_rate_layers': (imported_layers / len(parsed_data['soil_layers']) * 100) if parsed_data['soil_layers'] else 0
            }
            
            # 檢查是否有嚴重錯誤
            if imported_boreholes == 0:
                raise Exception("沒有成功匯入任何鑽孔資料")
            
            if imported_layers == 0:
                raise Exception("沒有成功匯入任何土層資料")
            
            logger.info(f"資料匯入完成: {imported_boreholes} 個鑽孔, {imported_layers} 個土層")
            
            return {
                'success': True,
                'summary': self.import_summary,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"資料庫匯入錯誤: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'errors': errors
            }  
    def validate_imported_data(self) -> Dict[str, Any]:
        """
        驗證已匯入的資料
        
        Returns:
            驗證結果
        """
        validation_results = {
            'is_valid': True,
            'warnings': [],
            'errors': [],
            'statistics': {}
        }
        
        try:
            boreholes = BoreholeData.objects.filter(project=self.project)
            
            if not boreholes.exists():
                validation_results['is_valid'] = False
                validation_results['errors'].append("專案中沒有鑽孔資料")
                return validation_results
            
            # 統計資訊
            total_boreholes = boreholes.count()
            total_layers = SoilLayer.objects.filter(borehole__project=self.project).count()
            
            validation_results['statistics'] = {
                'total_boreholes': total_boreholes,
                'total_layers': total_layers,
                'average_layers_per_borehole': total_layers / total_boreholes if total_boreholes > 0 else 0
            }
            
            # 驗證每個鑽孔
            for borehole in boreholes:
                borehole_validation = self._validate_borehole(borehole)
                validation_results['warnings'].extend(borehole_validation['warnings'])
                validation_results['errors'].extend(borehole_validation['errors'])
                
                if borehole_validation['errors']:
                    validation_results['is_valid'] = False
            
            return validation_results
            
        except Exception as e:
            logger.error(f"資料驗證錯誤: {str(e)}")
            validation_results['is_valid'] = False
            validation_results['errors'].append(f"驗證過程發生錯誤: {str(e)}")
            return validation_results
    
    def _validate_borehole(self, borehole: BoreholeData) -> Dict[str, List[str]]:
        """驗證單個鑽孔資料"""
        warnings = []
        errors = []
        
        # 檢查座標
        if not (160000 <= borehole.twd97_x <= 380000) or not (2420000 <= borehole.twd97_y <= 2800000):
            warnings.append(f"鑽孔 {borehole.borehole_id}: 座標可能超出台灣地區範圍")
        
        # 檢查土層資料
        soil_layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')
        
        if not soil_layers.exists():
            errors.append(f"鑽孔 {borehole.borehole_id}: 沒有土層資料")
            return {'warnings': warnings, 'errors': errors}
        
        # 檢查土層連續性
        prev_bottom = None
        for layer in soil_layers:
            # 檢查深度邏輯
            if layer.top_depth >= layer.bottom_depth:
                errors.append(f"鑽孔 {borehole.borehole_id}: 土層深度邏輯錯誤 ({layer.top_depth}m - {layer.bottom_depth}m)")
            
            # 檢查土層連續性
            if prev_bottom is not None and abs(prev_bottom - layer.top_depth) > 0.1:
                warnings.append(f"鑽孔 {borehole.borehole_id}: 深度 {prev_bottom}m 與 {layer.top_depth}m 之間可能有間隙")
            
            prev_bottom = layer.bottom_depth
            
            # 檢查 SPT-N 值
            if layer.spt_n is not None:
                if layer.spt_n < 0 or layer.spt_n > 100:
                    warnings.append(f"鑽孔 {borehole.borehole_id}: SPT-N 值異常 ({layer.spt_n})")
            else:
                warnings.append(f"鑽孔 {borehole.borehole_id}: 深度 {layer.top_depth}m-{layer.bottom_depth}m 缺少 SPT-N 值")
            
            # 檢查土壤分類
            if not layer.uscs:
                warnings.append(f"鑽孔 {borehole.borehole_id}: 深度 {layer.top_depth}m-{layer.bottom_depth}m 缺少土壤分類")
        
        return {'warnings': warnings, 'errors': errors}
    
    def get_preview_data(self, limit: int = 10) -> Dict[str, Any]:
        """
        取得預覽資料
        
        Args:
            limit: 預覽筆數限制
            
        Returns:
            預覽資料
        """
        try:
            boreholes = BoreholeData.objects.filter(project=self.project)[:limit]
            preview_data = []
            
            for borehole in boreholes:
                layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')[:5]
                
                borehole_data = {
                    'borehole_id': borehole.borehole_id,
                    'twd97_x': borehole.twd97_x,
                    'twd97_y': borehole.twd97_y,
                    'surface_elevation': borehole.surface_elevation,
                    'water_depth': borehole.water_depth,
                    'layers_count': layers.count(),
                    'max_depth': max([layer.bottom_depth for layer in layers]) if layers else 0,
                    'sample_layers': []
                }
                
                for layer in layers:
                    layer_data = {
                        'top_depth': layer.top_depth,
                        'bottom_depth': layer.bottom_depth,
                        'uscs': layer.uscs,
                        'spt_n': layer.spt_n,
                        'thickness': layer.thickness
                    }
                    borehole_data['sample_layers'].append(layer_data)
                
                preview_data.append(borehole_data)
            
            return {
                'success': True,
                'data': preview_data,
                'total_boreholes': BoreholeData.objects.filter(project=self.project).count()
            }
            
        except Exception as e:
            logger.error(f"預覽資料取得錯誤: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }