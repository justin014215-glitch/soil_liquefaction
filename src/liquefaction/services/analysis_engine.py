# src/liquefaction/services/analysis_engine.py
import logging
import sys
import os
import pandas as pd
import tempfile
from typing import Dict, Any, List, Optional
from django.db import transaction
from ..models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult
import os
from django.conf import settings
from datetime import datetime
print("=== 開始載入 analysis_engine.py ===")

logger = logging.getLogger(__name__)

# 嘗試導入自定義的分析方法
print("嘗試導入分析方法...")
HBF_AVAILABLE = False
NCEER_AVAILABLE = False
AIJ_AVAILABLE = False
JRA_AVAILABLE = False

try:
    print("正在導入 HBF...")
    from .HBF import HBF
    HBF_AVAILABLE = True
    print("✅ 成功載入 HBF 分析方法")
except ImportError as e:
    print(f"❌ 無法載入 HBF 分析方法: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ 載入 HBF 時發生其他錯誤: {e}")
    import traceback
    traceback.print_exc()

try:
    print("正在導入 NCEER...")
    from .NCEER import NCEER
    NCEER_AVAILABLE = True
    print("✅ 成功載入 NCEER 分析方法")
except ImportError as e:
    print(f"❌ 無法載入 NCEER 分析方法: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ 載入 NCEER 時發生其他錯誤: {e}")
    import traceback
    traceback.print_exc()

try:
    print("正在導入 AIJ...")
    from .AIJ import AIJ
    AIJ_AVAILABLE = True
    print("✅ 成功載入 AIJ 分析方法")
except ImportError as e:
    print(f"❌ 無法載入 AIJ 分析方法: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ 載入 AIJ 時發生其他錯誤: {e}")
    import traceback
    traceback.print_exc()

try:
    print("正在導入 JRA...")
    from .JRA import JRA
    JRA_AVAILABLE = True
    print("✅ 成功載入 JRA 分析方法")
except ImportError as e:
    print(f"❌ 無法載入 JRA 分析方法: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ 載入 JRA 時發生其他錯誤: {e}")
    import traceback
    traceback.print_exc()

print(f"分析方法可用狀態: HBF={HBF_AVAILABLE}, NCEER={NCEER_AVAILABLE}, AIJ={AIJ_AVAILABLE}, JRA={JRA_AVAILABLE}")

class LiquefactionAnalysisEngine:
    """液化分析計算引擎 - 專門用於調用外部分析方法"""
    
    def __init__(self, project: AnalysisProject):
        self.project = project
        self.analysis_method = project.analysis_method
        self.em_value = project.em_value
        self.unit_weight_unit = project.unit_weight_unit
        self.use_fault_data = project.use_fault_data
        self.warnings = []
        self.errors = []
        self._is_running = False  # 添加執行標記
        # 創建專案專用的輸出目錄
        self.project_output_dir = self._create_project_output_dir()
    def _create_project_output_dir(self) -> str:
        """創建專案專用的輸出目錄"""
        # 使用專案ID和名稱創建目錄
        safe_project_name = "".join(c for c in self.project.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        dir_name = f"{self.project.id}_{safe_project_name}_{self.analysis_method}"
        
        project_dir = os.path.join(settings.ANALYSIS_OUTPUT_ROOT, dir_name)
        os.makedirs(project_dir, exist_ok=True)
        
        return project_dir
    
    def _get_output_filename(self, base_name: str, extension: str = 'csv') -> str:
        """生成唯一的輸出檔案名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.project.id}_{self.analysis_method}_{base_name}_{timestamp}.{extension}"
        return os.path.join(self.project_output_dir, filename)

    def _execute_analysis(self, analyzer, df: pd.DataFrame, method_name: str):
        """執行具體的分析方法"""
        import tempfile
        
        # 臨時保存 DataFrame 到 CSV 檔案
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as temp_file:
            df.to_csv(temp_file.name, index=False, encoding='utf-8-sig')
            temp_csv_path = temp_file.name
            print(f"臨時 CSV 檔案: {temp_csv_path}")
        
        try:
            print(f"開始執行 {method_name} 分析...")
            
            # 根據不同的分析方法調用相應的主函數
            if method_name == 'HBF' and hasattr(analyzer, 'HBF_main'):
                main_method = analyzer.HBF_main
            elif method_name == 'NCEER' and hasattr(analyzer, 'NCEER_main'):
                main_method = analyzer.NCEER_main
            elif method_name == 'JRA' and hasattr(analyzer, 'JRA_main'):
                main_method = analyzer.JRA_main
            elif method_name == 'AIJ' and hasattr(analyzer, 'AIJ_main'):
                main_method = analyzer.AIJ_main
            elif hasattr(analyzer, f'{method_name}_main'):
                main_method = getattr(analyzer, f'{method_name}_main')
            else:
                raise Exception(f"找不到 {method_name} 的主要分析方法")
            
            results_df, lpi_summary, input_file = main_method(
                show_gui=False,
                input_file_path=temp_csv_path,
                use_fault_data=self.project.use_fault_data,
                fault_shapefile_path=self.project.get_fault_shapefile_path() if self.project.use_fault_data else None,
                custom_em=self.em_value,
                unit_weight_unit=self.unit_weight_unit,
                output_dir=self.project_output_dir,  # 傳遞專案輸出目錄
                project_id=str(self.project.id)      # 傳遞專案ID
            )
            
            print(f"{method_name} 分析完成")
            print(f"結果筆數: {len(results_df) if results_df is not None else 'None'}")
            
            return results_df, lpi_summary, input_file
            
        finally:
            # 清理臨時檔案
            if os.path.exists(temp_csv_path):
                os.unlink(temp_csv_path)
                print(f"已清理臨時檔案: {temp_csv_path}")

    def run_analysis(self) -> Dict[str, Any]:
        """執行液化分析 - 僅調用外部分析方法"""
        # 檢查是否已在執行中
        if self._is_running:
            print("⚠️ 分析已在執行中，跳過重複執行")
            return {
                'success': False,
                'error': '分析已在執行中',
                'warnings': [],
                'errors': []
            }
        
        # 檢查專案狀態，如果已經在處理中則直接返回
        if self.project.status == 'processing':
            print("⚠️ 專案已在處理中，跳過重複執行")
            return {
                'success': False,
                'error': '專案已在處理中，請稍候...',
                'warnings': [],
                'errors': []
            }
        
        self._is_running = True
        print(f"🔵 開始執行分析，項目狀態: {self.project.status}")
        
        try:
            # 更新專案狀態
            self.project.status = 'processing'
            self.project.save()
            
            # 根據選擇的分析方法調用對應的外部分析方法
            if self.analysis_method == 'HBF' and HBF_AVAILABLE:
                result = self._run_external_analysis('HBF', HBF)
            elif self.analysis_method == 'NCEER' and NCEER_AVAILABLE:
                result = self._run_external_analysis('NCEER', NCEER)
            elif self.analysis_method == 'AIJ' and AIJ_AVAILABLE:
                result = self._run_external_analysis('AIJ', AIJ)
            elif self.analysis_method == 'JRA' and JRA_AVAILABLE:
                result = self._run_external_analysis('JRA', JRA)
            else:
                # 分析方法不可用
                error_msg = f"分析方法 {self.analysis_method} 不可用或未正確載入"
                print(f"❌ {error_msg}")
                raise Exception(error_msg)
            
            return result
                
        except Exception as e:
            self.project.status = 'error'
            self.project.error_message = str(e)
            self.project.save()
            
            logger.error(f"液化分析錯誤: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'warnings': self.warnings,
                'errors': self.errors
            }
        finally:
            self._is_running = False
            print(f"🔵 分析執行結束")

    def _run_external_analysis(self, method_name: str, analyzer_class) -> Dict[str, Any]:
        """使用外部分析方法（您提供的 HBF, NCEER, AIJ, JRA 等）"""
        try:
            print(f"開始 {method_name} 分析...")
            
            # 準備資料
            df = self._prepare_dataframe_for_analysis()
            print(f"準備的資料筆數: {len(df)}")
            
            if len(df) == 0:
                raise Exception("沒有可分析的資料")
            
            # 建立分析器 - 根據不同分析方法使用不同的初始化參數
            if method_name in ['HBF']:
                # HBF 支援 unit_weight_conversion_factor 參數
                analyzer = analyzer_class(
                    default_em=self.em_value,
                    unit_weight_conversion_factor=1.0 if self.unit_weight_unit == 't/m3' else 1.0/9.81
                )
            else:
                # NCEER, JRA, AIJ 只需要 default_em 參數
                analyzer = analyzer_class(default_em=self.em_value)
            print(f"{method_name} 分析器設定完成")
            
            # 執行分析
            results_df, lpi_summary, _ = self._execute_analysis(analyzer, df, method_name)
            
            if results_df is not None and len(results_df) > 0:
                print("開始儲存結果到資料庫...")
                self._save_analysis_results_to_database(results_df)
                
                self.project.status = 'completed'
                self.project.error_message = ''
                self.project.save()
                
                print(f"{method_name} 分析成功完成!")
                return {
                    'success': True,
                    'total_layers': len(results_df),
                    'analyzed_layers': len(results_df),
                    'warnings': self.warnings,
                    'errors': self.errors,
                    'analysis_method': self.analysis_method
                }
            else:
                raise Exception(f"{method_name} 分析沒有產生結果")
                
        except Exception as e:
            print(f"{method_name} 分析錯誤: {str(e)}")
            logger.error(f"{method_name} 分析錯誤: {str(e)}")
            import traceback
            print("完整錯誤追蹤:")
            print(traceback.format_exc())
            raise


    def _prepare_dataframe_for_analysis(self) -> pd.DataFrame:
        """準備給外部分析器使用的 DataFrame"""
        # 從資料庫取得資料
        boreholes = BoreholeData.objects.filter(project=self.project)
        
        data_list = []
        for borehole in boreholes:
            soil_layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')
            
            for layer in soil_layers:
                row_data = {
                    '鑽孔編號': borehole.borehole_id,
                    'TWD97_X': borehole.twd97_x,
                    'TWD97_Y': borehole.twd97_y,
                    '上限深度(公尺)': layer.top_depth,
                    '下限深度(公尺)': layer.bottom_depth,
                    'water_depth(m)': borehole.water_depth,
                    'N_value': str(layer.spt_n) if layer.spt_n is not None else '',  # 轉為字串
                    '統一土壤分類': layer.uscs,
                    '統體單位重(t/m3)': layer.unit_weight,
                    '含水量(%)': layer.water_content,
                    '細料(%)': layer.fines_content,
                    '塑性指數(%)': layer.plastic_index,
                    '取樣編號': layer.sample_id or f'S-{layer.top_depth}',
                    
                    # 地震參數
                    'SDS': borehole.sds,
                    'SMS': borehole.sms,
                    '基準Mw': borehole.base_mw,
                    '資料來源': borehole.data_source or '',
                }
                data_list.append(row_data)
        
        return pd.DataFrame(data_list)

    @transaction.atomic

    def _save_analysis_results_to_database(self, results_df: pd.DataFrame):
        """將外部分析方法的結果儲存到資料庫 - 支援多方法"""
        with transaction.atomic():
            # 只清除當前分析方法的舊結果，保留其他方法的結果
            AnalysisResult.objects.filter(
                soil_layer__borehole__project=self.project,
                analysis_method=self.analysis_method  # 新增：只刪除當前方法的結果
            ).delete()
            for _, row in results_df.iterrows():
                try:
                    # 找到對應的土層
                    borehole = BoreholeData.objects.get(
                        project=self.project,
                        borehole_id=row['鑽孔編號']
                    )
                    
                    soil_layer = SoilLayer.objects.filter(
                        borehole=borehole,
                        top_depth=float(row['上限深度(公尺)']),
                        bottom_depth=float(row['下限深度(公尺)'])
                    ).first()
                    
                    if not soil_layer:
                        continue
                    
                    # 安全地獲取數值
                    def safe_float(val):
                        if pd.isna(val) or val == '-' or val == '':
                            return None
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return None
                    
                    # 創建分析結果
                    AnalysisResult.objects.create(
                        soil_layer=soil_layer,
                        analysis_method=self.analysis_method,
                        soil_depth=safe_float(row.get('土層深度')),
                        mid_depth=safe_float(row.get('土層中點深度')),
                        analysis_depth=safe_float(row.get('分析點深度')),
                        sigma_v=safe_float(row.get('累計sigmav')),
                        sigma_v_csr=safe_float(row.get('sigma_v_CSR')),
                        sigma_v_crr=safe_float(row.get('sigma_v_CRR')),
                        n60=safe_float(row.get('N_60')),
                        n1_60=safe_float(row.get('N1_60')),
                        n1_60cs=safe_float(row.get('N1_60cs')),
                        vs=safe_float(row.get('Vs')),
                        crr_7_5=safe_float(row.get('CRR_7_5')),
                        
                        # 設計地震
                        mw_design=safe_float(row.get('Mw_Design')),
                        a_value_design=safe_float(row.get('A_value_Design')),
                        sd_s_design=safe_float(row.get('SD_S_Design')),
                        sm_s_design=safe_float(row.get('SM_S_Design')),
                        msf_design=safe_float(row.get('MSF_Design')),
                        rd_design=safe_float(row.get('rd_Design')),
                        csr_design=safe_float(row.get('CSR_Design')),
                        crr_design=safe_float(row.get('CRR_Design')),
                        fs_design=safe_float(row.get('FS_Design')),
                        lpi_design=safe_float(row.get('LPI_Design')),
                        
                        # 中小地震
                        mw_mid=safe_float(row.get('Mw_MidEq')),
                        a_value_mid=safe_float(row.get('A_value_MidEq')),
                        sd_s_mid=safe_float(row.get('SD_S_MidEq')),
                        sm_s_mid=safe_float(row.get('SM_S_MidEq')),
                        msf_mid=safe_float(row.get('MSF_MidEq')),
                        rd_mid=safe_float(row.get('rd_MidEq')),
                        csr_mid=safe_float(row.get('CSR_MidEq')),
                        crr_mid=safe_float(row.get('CRR_MidEq')),
                        fs_mid=safe_float(row.get('FS_MidEq')),
                        lpi_mid=safe_float(row.get('LPI_MidEq')),
                        
                        # 最大地震
                        mw_max=safe_float(row.get('Mw_MaxEq')),
                        a_value_max=safe_float(row.get('A_value_MaxEq')),
                        sd_s_max=safe_float(row.get('SD_S_MaxEq')),
                        sm_s_max=safe_float(row.get('SM_S_MaxEq')),
                        msf_max=safe_float(row.get('MSF_MaxEq')),
                        rd_max=safe_float(row.get('rd_MaxEq')),
                        csr_max=safe_float(row.get('CSR_MaxEq')),
                        crr_max=safe_float(row.get('CRR_MaxEq')),
                        fs_max=safe_float(row.get('FS_MaxEq')),
                        lpi_max=safe_float(row.get('LPI_MaxEq'))
                    )
                    
                except Exception as e:
                    logger.error(f"儲存分析結果時發生錯誤: {str(e)}")
                    continue