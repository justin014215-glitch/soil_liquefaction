# src/liquefaction/services/analysis_engine.py
import math
import logging
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from django.db import transaction
from ..models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult

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
    """液化分析計算引擎"""
    
    def __init__(self, project: AnalysisProject):
        self.project = project
        self.analysis_method = project.analysis_method
        self.em_value = project.em_value
        self.unit_weight_unit = project.unit_weight_unit
        self.results = []
        self.errors = []
        self.warnings = []
        self._is_running = False  # 添加執行標記
    
    def run_analysis(self) -> Dict[str, Any]:
        """執行液化分析"""
        # 檢查是否已在執行中
        if self._is_running:
            print("⚠️ 分析已在執行中，跳過重複執行")
            return {
                'success': False,
                'error': '分析已在執行中',
                'warnings': [],
                'errors': []
            }
        
        self._is_running = True
        print(f"🔵 開始執行分析，項目狀態: {self.project.status}")
        
        try:
            # 更新專案狀態
            self.project.status = 'processing'
            self.project.save()
            
            # 根據選擇的分析方法決定使用哪個引擎
            if self.analysis_method == 'HBF' and HBF_AVAILABLE:
                result = self._run_custom_analysis('HBF', HBF)
            elif self.analysis_method == 'NCEER' and NCEER_AVAILABLE:
                result = self._run_custom_analysis('NCEER', NCEER)
            elif self.analysis_method == 'AIJ' and AIJ_AVAILABLE:
                result = self._run_custom_analysis('AIJ', AIJ)
            elif self.analysis_method == 'JRA' and JRA_AVAILABLE:
                result = self._run_custom_analysis('JRA', JRA)
            else:
                # 使用原有的內建分析方法
                print(f"使用內建分析方法: {self.analysis_method}")
                result = self._run_builtin_analysis()
            
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

    def _run_custom_analysis(self, method_name: str, analyzer_class) -> Dict[str, Any]:
        """使用自定義分析方法"""
        try:
            print(f"開始 {method_name} 分析...")
            
            # 準備資料
            df = self._prepare_dataframe_for_analysis()
            print(f"準備的資料筆數: {len(df)}")
            
            if len(df) == 0:
                raise Exception("沒有可分析的資料")
            
            # 建立分析器
            analyzer = analyzer_class(
                default_em=self.em_value,
                unit_weight_conversion_factor=1.0 if self.unit_weight_unit == 't/m3' else 1.0/9.81
            )
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
            if hasattr(analyzer, f'{method_name}_main'):
                main_method = getattr(analyzer, f'{method_name}_main')
            elif hasattr(analyzer, 'HBF_main'):  # HBF 的情況
                main_method = analyzer.HBF_main
            elif hasattr(analyzer, 'main'):
                main_method = analyzer.main
            else:
                raise Exception(f"找不到 {method_name} 的主要分析方法")
            
            results_df, lpi_summary, input_file = main_method(
                show_gui=False,
                input_file_path=temp_csv_path,
                use_fault_data=self.project.use_fault_data,
                fault_shapefile_path=self.project.get_fault_shapefile_path() if self.project.use_fault_data else None,
                custom_em=self.em_value,
                unit_weight_unit=self.unit_weight_unit
            )
            
            print(f"{method_name} 分析完成")
            print(f"結果筆數: {len(results_df) if results_df is not None else 'None'}")
            
            return results_df, lpi_summary, input_file
            
        finally:
            # 清理臨時檔案
            if os.path.exists(temp_csv_path):
                os.unlink(temp_csv_path)
                print(f"已清理臨時檔案: {temp_csv_path}")
    @transaction.atomic
    def _analyze_soil_layer(self, borehole: BoreholeData, layer: SoilLayer) -> Optional[AnalysisResult]:
        """分析單個土層"""
        try:
            # 檢查是否為可液化土層
            if not self._is_liquefiable_soil(layer):

                return None
            
            # 檢查必要參數
            if layer.spt_n is None:
                self.warnings.append(f"鑽孔 {borehole.borehole_id} 深度 {layer.top_depth}-{layer.bottom_depth}m: 缺少 SPT-N 值")
                return None
            
            # 計算基本參數
            analysis_depth = (layer.top_depth + layer.bottom_depth) / 2
            soil_depth = layer.bottom_depth - layer.top_depth
            
            # 計算應力
            sigma_v = self._calculate_total_stress(borehole, layer, analysis_depth)
            sigma_v_prime = self._calculate_effective_stress(borehole, layer, analysis_depth)
            
            # 計算 SPT 相關參數
            n60 = self._calculate_n60(layer.spt_n)
            n1_60 = self._calculate_n1_60(n60, sigma_v_prime)
            n1_60cs = self._calculate_n1_60cs(n1_60, layer)
            
            # 估算剪力波速
            vs = self._estimate_vs(layer, n1_60)
            
            # 計算液化抗力
            crr_7_5 = self._calculate_crr_7_5(n1_60cs, layer)
            
            # 計算不同地震情境的結果
            design_result = self._calculate_earthquake_scenario(
                borehole, layer, analysis_depth, sigma_v_prime, crr_7_5, 'design'
            )
            
            mid_result = self._calculate_earthquake_scenario(
                borehole, layer, analysis_depth, sigma_v_prime, crr_7_5, 'mid'
            )
            
            max_result = self._calculate_earthquake_scenario(
                borehole, layer, analysis_depth, sigma_v_prime, crr_7_5, 'max'
            )
            
            # 創建分析結果
            analysis_result = AnalysisResult.objects.create(
                soil_layer=layer,
                soil_depth=soil_depth,
                mid_depth=analysis_depth,
                analysis_depth=analysis_depth,
                sigma_v=sigma_v,
                sigma_v_csr=sigma_v_prime,
                sigma_v_crr=sigma_v_prime,
                n60=n60,
                n1_60=n1_60,
                n1_60cs=n1_60cs,
                vs=vs,
                crr_7_5=crr_7_5,
                
                # 設計地震
                mw_design=design_result['mw'],
                a_value_design=design_result['a_value'],
                sd_s_design=design_result['sd_s'],
                sm_s_design=design_result['sm_s'],
                msf_design=design_result['msf'],
                rd_design=design_result['rd'],
                csr_design=design_result['csr'],
                crr_design=design_result['crr'],
                fs_design=design_result['fs'],
                lpi_design=design_result['lpi'],
                
                # 中小地震
                mw_mid=mid_result['mw'],
                a_value_mid=mid_result['a_value'],
                sd_s_mid=mid_result['sd_s'],
                sm_s_mid=mid_result['sm_s'],
                msf_mid=mid_result['msf'],
                rd_mid=mid_result['rd'],
                csr_mid=mid_result['csr'],
                crr_mid=mid_result['crr'],
                fs_mid=mid_result['fs'],
                lpi_mid=mid_result['lpi'],
                
                # 最大地震
                mw_max=max_result['mw'],
                a_value_max=max_result['a_value'],
                sd_s_max=max_result['sd_s'],
                sm_s_max=max_result['sm_s'],
                msf_max=max_result['msf'],
                rd_max=max_result['rd'],
                csr_max=max_result['csr'],
                crr_max=max_result['crr'],
                fs_max=max_result['fs'],
                lpi_max=max_result['lpi']
            )
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"土層分析錯誤: {str(e)}")
            raise
    
    def _is_liquefiable_soil(self, layer: SoilLayer) -> bool:
        """判斷是否為可液化土層"""
        # 根據 USCS 分類判斷
        if not layer.uscs:
            return False
        
        uscs = layer.uscs.upper()
        
        if self.analysis_method == 'HBF':
            # HBF 方法的液化敏感性判斷
            liquefiable_types = ['SM', 'SP', 'SW', 'SC', 'ML', 'CL']
            non_liquefiable_types = ['CH', 'MH', 'OH', 'PT', 'GW', 'GP', 'GM', 'GC']
            
            if any(uscs.startswith(t) for t in non_liquefiable_types):
                return False
            
            if any(uscs.startswith(t) for t in liquefiable_types):
                # HBF 特殊判斷標準
                if layer.fines_content is not None and layer.fines_content > 35:
                    if layer.plastic_index is not None and layer.plastic_index > 12:
                        return False
                return True
        
        elif self.analysis_method == 'AIJ' or self.analysis_method == 'JRA':
            # 日本方法較嚴格的判斷標準
            liquefiable_types = ['SM', 'SP', 'SW', 'ML']
            non_liquefiable_types = ['CH', 'MH', 'OH', 'PT', 'GW', 'GP', 'GM', 'GC', 'CL', 'SC']
            
            if any(uscs.startswith(t) for t in non_liquefiable_types):
                return False
            
            if any(uscs.startswith(t) for t in liquefiable_types):
                # 日本方法的額外檢查
                if layer.fines_content is not None and layer.fines_content > 35:
                    return False
                if layer.plastic_index is not None and layer.plastic_index > 15:
                    return False
                return True
        
        else:
            # NCEER 和預設方法
            liquefiable_types = ['SM', 'SP', 'SW', 'SC', 'ML', 'CL']
            non_liquefiable_types = ['CH', 'MH', 'OH', 'PT', 'GW', 'GP', 'GM', 'GC']
            
            if any(uscs.startswith(t) for t in non_liquefiable_types):
                return False
            
            if any(uscs.startswith(t) for t in liquefiable_types):
                # NCEER 標準檢查
                if layer.fines_content is not None and layer.fines_content > 35:
                    return False
                if layer.plastic_index is not None and layer.plastic_index > 18:
                    return False
                return True
        
        return False
    
    def _calculate_total_stress(self, borehole: BoreholeData, layer: SoilLayer, depth: float) -> float:
        """計算總垂直應力"""
        # 簡化計算，假設統一單位重
        unit_weight = layer.unit_weight if layer.unit_weight else 1.8
        
        # 單位轉換
        if self.unit_weight_unit == 'kN/m3':
            unit_weight = unit_weight / 9.81  # 轉換為 t/m³
        
        return unit_weight * depth
    
    def _calculate_effective_stress(self, borehole: BoreholeData, layer: SoilLayer, depth: float) -> float:
        """計算有效垂直應力"""
        total_stress = self._calculate_total_stress(borehole, layer, depth)
        
        # 考慮地下水位影響
        water_depth = borehole.water_depth
        
        if depth > water_depth:
            # 在地下水位以下，需扣除孔隙水壓
            submerged_depth = depth - water_depth
            unit_weight_water = 1.0  # 水的單位重 t/m³
            effective_stress = total_stress - unit_weight_water * submerged_depth
        else:
            effective_stress = total_stress
        
        return max(0.1, effective_stress)  # 避免負值或過小值
    
    def _calculate_n60(self, spt_n: float) -> float:
        """計算 N60 值"""
        # 根據錘擊效率修正
        return spt_n * (self.em_value / 60.0)
    
    def _calculate_n1_60(self, n60: float, sigma_v_prime: float) -> float:
        """計算 (N1)60 值"""
        # 垂直有效應力修正
        cn = min(1.7, (100 / sigma_v_prime) ** 0.5)
        return n60 * cn
    
    def _calculate_n1_60cs(self, n1_60: float, layer: SoilLayer) -> float:
        """計算 (N1)60cs 值"""
        if self.analysis_method == 'HBF':
            # HBF (2012) 方法的細料含量修正
            if layer.fines_content is not None:
                fc = layer.fines_content
                if fc <= 5:
                    delta_n = 0
                elif fc <= 15:
                    delta_n = 2.0 * (fc - 5) / 10
                elif fc <= 35:
                    delta_n = 2.0 + 3.0 * (fc - 15) / 20
                else:
                    delta_n = 5.0
                
                return n1_60 + delta_n
            else:
                return n1_60
        
        elif self.analysis_method == 'NCEER':
            # NCEER 方法的細料含量修正
            if layer.fines_content is not None:
                fc = layer.fines_content
                if fc <= 5:
                    delta_n = 0
                elif fc <= 35:
                    delta_n = math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01))**2)
                else:
                    delta_n = 5.0
                
                return n1_60 + delta_n
            else:
                return n1_60
        
        elif self.analysis_method == 'AIJ':
            # AIJ 方法 - 簡化的細料含量修正
            if layer.fines_content is not None:
                fc = layer.fines_content
                if fc > 10:
                    delta_n = 3.0 * (fc - 10) / 40
                    return n1_60 + min(delta_n, 3.0)
                else:
                    return n1_60
            else:
                return n1_60
        
        elif self.analysis_method == 'JRA':
            # JRA 方法 - 類似 AIJ 但係數不同
            if layer.fines_content is not None:
                fc = layer.fines_content
                if fc > 15:
                    delta_n = 2.5 * (fc - 15) / 20
                    return n1_60 + min(delta_n, 2.5)
                else:
                    return n1_60
            else:
                return n1_60
        
        else:
            # 預設使用 NCEER 方法
            if layer.fines_content is not None:
                fc = layer.fines_content
                if fc <= 5:
                    delta_n = 0
                elif fc <= 35:
                    delta_n = math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01))**2)
                else:
                    delta_n = 5.0
                
                return n1_60 + delta_n
            else:
                return n1_60
    
    def _estimate_vs(self, layer: SoilLayer, n1_60: float) -> float:
        """估算剪力波速"""
        # 使用經驗公式估算 Vs
        # Vs = 114.4 * (N1_60)^0.302 (Andrus et al., 2007)
        vs = 114.4 * (n1_60 ** 0.302)
        return round(vs, 1)
    
    def _calculate_crr_7_5(self, n1_60cs: float, layer: SoilLayer) -> float:
        """計算 CRR7.5 值"""
        if self.analysis_method == 'HBF':
            # HBF (2012) 方法 - Hwang et al. (2012)
            if n1_60cs < 2:
                crr = 0.0
            elif n1_60cs <= 30:
                # HBF 修正公式
                crr = 0.0104 * (n1_60cs + 1)**2.32 / 1000
                crr = min(crr, 0.25)
            else:
                crr = 0.25
        
        elif self.analysis_method == 'NCEER':
            # NCEER 方法 (Youd et al., 2001)
            if n1_60cs < 2:
                crr = 0.0
            elif n1_60cs <= 30:
                crr = (1 / (34 - n1_60cs)) + (n1_60cs / 135) - (1 / 200)
            else:
                crr = 0.25
        
        elif self.analysis_method == 'AIJ':
            # AIJ (日本建築學會) 方法
            if n1_60cs < 4:
                crr = 0.0
            elif n1_60cs <= 14:
                crr = 0.0882 * math.sqrt(n1_60cs / 1.7)
            else:
                crr = 0.0882 * math.sqrt(14 / 1.7)
        
        elif self.analysis_method == 'JRA':
            # JRA (日本道路協會) 方法
            if n1_60cs < 4:
                crr = 0.0
            elif n1_60cs <= 14:
                crr = 0.0882 * math.sqrt(n1_60cs / 1.7)
            else:
                crr = 0.25
        
        else:
            # 預設使用 NCEER 方法
            if n1_60cs < 2:
                crr = 0.0
            elif n1_60cs <= 30:
                crr = (1 / (34 - n1_60cs)) + (n1_60cs / 135) - (1 / 200)
            else:
                crr = 0.25
        
        return max(0.01, crr)
    
    def _calculate_earthquake_scenario(self, borehole: BoreholeData, layer: SoilLayer, 
                                     depth: float, sigma_v_prime: float, crr_7_5: float, 
                                     scenario: str) -> Dict[str, float]:
        """計算地震情境結果"""
        
        # 根據情境設定地震參數
        if scenario == 'design':
            mw = borehole.base_mw if borehole.base_mw else 6.5
            sd_s = borehole.sds if borehole.sds else 0.6
            sm_s = borehole.sms if borehole.sms else 1.0
        elif scenario == 'mid':
            mw = (borehole.base_mw - 0.5) if borehole.base_mw else 6.0
            sd_s = (borehole.sds * 0.7) if borehole.sds else 0.42
            sm_s = (borehole.sms * 0.7) if borehole.sms else 0.7
        else:  # max
            mw = (borehole.base_mw + 0.5) if borehole.base_mw else 7.0
            sd_s = (borehole.sds * 1.3) if borehole.sds else 0.78
            sm_s = (borehole.sms * 1.3) if borehole.sms else 1.3
        
        # 計算地表加速度
        a_value = sd_s * 2.5 / 9.81  # 轉換為 g
        
        # 計算規模修正因子 (MSF)
        msf = 6.9 * math.exp(-mw / 4) - 0.058 if mw < 7.5 else 0.84
        
        # 計算應力折減係數 (rd)
        if depth <= 9.15:
            rd = 1.0 - 0.00765 * depth
        elif depth <= 23:
            rd = 1.174 - 0.0267 * depth
        else:
            rd = 0.744 - 0.008 * depth
        
        rd = max(0.1, rd)
        
        # 計算循環剪應力比 (CSR)
        csr = 0.65 * (a_value * sigma_v_prime / sigma_v_prime) * rd
        
        # 修正液化抗力
        crr = crr_7_5 * msf
        
        # 計算安全係數
        fs = crr / csr if csr > 0 else 999
        
        # 計算液化潛能指數 (LPI) 貢獻
        if depth <= 20:
            if fs < 1:
                lpi_contribution = (1 - fs) * (10 - 0.5 * depth)
            else:
                lpi_contribution = 0
        else:
            lpi_contribution = 0
        
        return {
            'mw': round(mw, 1),
            'a_value': round(a_value, 3),
            'sd_s': round(sd_s, 3),
            'sm_s': round(sm_s, 3),
            'msf': round(msf, 3),
            'rd': round(rd, 3),
            'csr': round(csr, 3),
            'crr': round(crr, 3),
            'fs': round(fs, 2),
            'lpi': round(lpi_contribution, 2)
        }
    
    def run_analysis(self) -> Dict[str, Any]:
        """執行液化分析"""
        try:
            # 更新專案狀態
            self.project.status = 'processing'
            self.project.save()
            
            # 根據選擇的分析方法決定使用哪個引擎
            if self.analysis_method == 'HBF' and HBF_AVAILABLE:
                return self._run_hbf_analysis()
            else:
                # 使用原有的內建分析方法
                return self._run_builtin_analysis()
                
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

    def _run_hbf_analysis(self) -> Dict[str, Any]:
        """使用你的 HBF 分析方法"""
        try:
            # 準備資料
            df = self._prepare_dataframe_for_hbf()
            
            if len(df) == 0:
                raise Exception("沒有可分析的資料")
            
            # 建立 HBF 分析器
            hbf_analyzer = HBF(
                default_em=self.em_value,
                unit_weight_conversion_factor=1.0 if self.unit_weight_unit == 't/m3' else 1.0/9.81
            )
            
            # 臨時保存 DataFrame 到 CSV 檔案
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as temp_file:
                df.to_csv(temp_file.name, index=False, encoding='utf-8-sig')
                temp_csv_path = temp_file.name
            
            try:
                # 執行分析（不使用 GUI）
                results_df, lpi_summary, _ = hbf_analyzer.HBF_main(
                    show_gui=False,
                    input_file_path=temp_csv_path,
                    use_fault_data=self.project.use_fault_data,
                    fault_shapefile_path=self.project.get_fault_shapefile_path() if self.project.use_fault_data else None,
                    custom_em=self.em_value,
                    unit_weight_unit=self.unit_weight_unit
                )
                
            finally:
                # 清理臨時檔案
                if os.path.exists(temp_csv_path):
                    os.unlink(temp_csv_path)
            
            if results_df is not None and len(results_df) > 0:
                # 將結果儲存到資料庫
                self._save_hbf_results_to_database(results_df)
                
                self.project.status = 'completed'
                self.project.error_message = ''
                self.project.save()
                
                return {
                    'success': True,
                    'total_layers': len(results_df),
                    'analyzed_layers': len(results_df),
                    'warnings': self.warnings,
                    'errors': self.errors,
                    'analysis_method': self.analysis_method
                }
            else:
                raise Exception("HBF 分析沒有產生結果")
                
        except Exception as e:
            logger.error(f"HBF 分析錯誤: {str(e)}")
            raise

    def _prepare_dataframe_for_hbf(self) -> pd.DataFrame:
        """準備給 HBF 分析器使用的 DataFrame"""
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

    def _save_hbf_results_to_database(self, results_df: pd.DataFrame):
        """將 HBF 分析結果儲存到資料庫"""
        with transaction.atomic():
            # 清除舊的分析結果
            AnalysisResult.objects.filter(soil_layer__borehole__project=self.project).delete()
            
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

    def _run_builtin_analysis(self):
        """使用原有的內建分析方法"""
        # 保留原來的分析邏輯
        boreholes = BoreholeData.objects.filter(project=self.project)
        
        if not boreholes.exists():
            raise ValueError("專案中沒有鑽孔資料")
        
        total_layers = 0
        analyzed_layers = 0
        
        # 清除舊的分析結果
        AnalysisResult.objects.filter(soil_layer__borehole__project=self.project).delete()
        
        # 對每個鑽孔進行分析
        for borehole in boreholes:
            soil_layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')
            total_layers += soil_layers.count()
            
            if not soil_layers.exists():
                self.warnings.append(f"鑽孔 {borehole.borehole_id} 沒有土層資料")
                continue
            
            # 分析每個土層
            for layer in soil_layers:
                try:
                    result = self._analyze_soil_layer(borehole, layer)
                    if result:
                        self.results.append(result)
                        analyzed_layers += 1
                except Exception as e:
                    error_msg = f"土層分析錯誤 ({borehole.borehole_id}, {layer.top_depth}-{layer.bottom_depth}m): {str(e)}"
                    self.errors.append(error_msg)
                    logger.error(error_msg)
        
        # 更新專案狀態
        if self.errors:
            self.project.status = 'error'
            self.project.error_message = f"分析過程中發生 {len(self.errors)} 個錯誤"
        else:
            self.project.status = 'completed'
            self.project.error_message = ''
        
        self.project.save()
        
        return {
            'success': len(self.errors) == 0,
            'total_layers': total_layers,
            'analyzed_layers': analyzed_layers,
            'warnings': self.warnings,
            'errors': self.errors,
            'analysis_method': self.analysis_method
        }