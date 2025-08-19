# src/liquefaction/services/analysis_engine.py
import math
import logging
from typing import Dict, Any, List, Optional
from django.db import transaction
from ..models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult

logger = logging.getLogger(__name__)


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
    
    def run_analysis(self) -> Dict[str, Any]:
        """執行液化分析"""
        try:
            # 更新專案狀態
            self.project.status = 'processing'
            self.project.save()
            
            # 獲取所有鑽孔資料
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
        
        # 液化敏感土壤類型
        liquefiable_types = ['SM', 'SP', 'SW', 'SC', 'ML', 'CL']
        
        # 非液化土壤類型
        non_liquefiable_types = ['CH', 'MH', 'OH', 'PT', 'GW', 'GP', 'GM', 'GC']
        
        if any(uscs.startswith(t) for t in non_liquefiable_types):
            return False
        
        if any(uscs.startswith(t) for t in liquefiable_types):
            # 額外檢查細料含量
            if layer.fines_content is not None:
                if layer.fines_content > 35:  # 細料含量過高
                    return False
            
            # 檢查塑性指數
            if layer.plastic_index is not None:
                if layer.plastic_index > 18:  # 塑性指數過高
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
        
        # 其他方法的簡化處理
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
            # HBF (2012) 方法
            if n1_60cs <= 30:
                crr = (1 / (34 - n1_60cs)) + (n1_60cs / 135) - (1 / 200)
            else:
                crr = 0.25
        
        elif self.analysis_method == 'NCEER':
            # NCEER 方法 (Youd et al., 2001)
            if n1_60cs <= 30:
                crr = (1 / (34 - n1_60cs)) + (n1_60cs / 135) - (1 / 200)
            else:
                crr = 0.25
        
        else:
            # 預設使用 NCEER 方法
            if n1_60cs <= 30:
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