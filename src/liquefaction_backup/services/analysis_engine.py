import os
import tempfile
import zipfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import pandas as pd
import geopandas as gpd
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from .HBF import HBF
from .NCEER import NCEER

class LiquefactionAnalyzer:
    """液化分析引擎 - 整合 HBF 和 NCEER 方法"""
    
    def __init__(self):
        self.supported_methods = {
            'HBF': 'HBF (2012) 方法',
            'NCEER': 'NCEER (2001) 方法'
        }
        self.results_base_dir = getattr(settings, 'LIQUEFACTION_RESULTS_DIR', 
                                       os.path.join(settings.MEDIA_ROOT, 'liquefaction_results'))
        
    def create_analysis_directory(self, method: str, timestamp: str = None) -> str:
        """創建分析結果目錄"""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 創建主目錄結構：liquefaction_results/method_timestamp/
        analysis_dir = os.path.join(
            self.results_base_dir,
            f"{method}_{timestamp}"
        )
        
        # 確保目錄存在
        os.makedirs(analysis_dir, exist_ok=True)
        
        # 創建子目錄
        subdirs = [
            'raw_results',      # 原始分析結果
            'simplified_reports', # 簡化報表
            'individual_wells',  # 個別鑽孔資料夾
            'charts',           # 圖表
            'summary'           # 摘要報表
        ]
        
        for subdir in subdirs:
            os.makedirs(os.path.join(analysis_dir, subdir), exist_ok=True)
            
        return analysis_dir

    def prepare_input_data(self, csv_content: bytes, method: str) -> Tuple[str, Optional[str]]:
        """準備輸入資料並進行初步驗證"""
        try:
            # 創建臨時檔案
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as temp_file:
                temp_file.write(csv_content)
                temp_csv_path = temp_file.name
            
            # 驗證CSV格式
            try:
                df = pd.read_csv(temp_csv_path)
                print(f"成功讀取CSV檔案，共 {len(df)} 筆資料")
                
                # 基本欄位檢查
                required_columns = ['鑽孔編號', 'TWD97_X', 'TWD97_Y']
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    error_msg = f"CSV檔案缺少必要欄位：{missing_columns}"
                    print(f"❌ {error_msg}")
                    os.unlink(temp_csv_path)
                    return None, error_msg
                
                print(f"✅ CSV檔案格式驗證通過")
                return temp_csv_path, None
                
            except Exception as e:
                error_msg = f"CSV檔案格式錯誤：{str(e)}"
                print(f"❌ {error_msg}")
                os.unlink(temp_csv_path)
                return None, error_msg
                
        except Exception as e:
            error_msg = f"處理輸入檔案時發生錯誤：{str(e)}"
            print(f"❌ {error_msg}")
            return None, error_msg

    def prepare_fault_data(self, shapefile_content: bytes = None) -> Optional[gpd.GeoDataFrame]:
        """準備斷層資料"""
        if shapefile_content is None:
            print("未提供斷層資料，跳過斷層分析")
            return None
            
        try:
            # 創建臨時目錄來解壓縮shapefile
            with tempfile.TemporaryDirectory() as temp_dir:
                # 假設傳入的是zip檔案包含完整的shapefile
                zip_path = os.path.join(temp_dir, 'fault_data.zip')
                with open(zip_path, 'wb') as f:
                    f.write(shapefile_content)
                
                # 解壓縮
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # 尋找.shp檔案
                shp_files = list(Path(temp_dir).glob('**/*.shp'))
                if not shp_files:
                    print("❌ 在上傳的檔案中找不到.shp檔案")
                    return None
                
                shp_path = str(shp_files[0])
                fault_gdf = gpd.read_file(shp_path)
                print(f"✅ 成功載入斷層資料：{len(fault_gdf)} 個記錄")
                return fault_gdf
                
        except Exception as e:
            print(f"❌ 載入斷層資料失敗：{e}")
            return None

    def analyze_hbf(self, 
                   csv_path: str, 
                   output_dir: str,
                   fault_gdf: Optional[gpd.GeoDataFrame] = None,
                   em_value: float = 72,
                   unit_weight_unit: str = "t/m3") -> Tuple[Optional[pd.DataFrame], Optional[Dict], Optional[str]]:
        """執行 HBF 分析"""
        print("\n" + "="*60)
        print("開始 HBF (2012) 液化分析")
        print("="*60)
        
        try:
            # 初始化HBF分析器
            if unit_weight_unit.lower() == "kn/m3":
                unit_weight_conversion_factor = 1.0/9.81
            else:
                unit_weight_conversion_factor = 1.0
                
            hbf_analyzer = HBF(
                default_em=em_value,
                unit_weight_conversion_factor=unit_weight_conversion_factor
            )
            
            # 執行分析
            final_df, lpi_summary, _ = hbf_analyzer.HBF_main(
                show_gui=False,
                input_file_path=csv_path,
                output_file_path=os.path.join(output_dir, 'raw_results', 'HBF_complete_results.csv'),
                use_fault_data=(fault_gdf is not None),
                fault_shapefile_path=None,
                custom_em=em_value,
                unit_weight_unit=unit_weight_unit
            )
            
            if final_df is not None:
                print("✅ HBF 分析完成")
                return final_df, lpi_summary, None
            else:
                error_msg = "HBF 分析失敗：未產生分析結果"
                print(f"❌ {error_msg}")
                return None, None, error_msg
                
        except Exception as e:
            error_msg = f"HBF 分析過程中發生錯誤：{str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            print(f"詳細錯誤：{traceback.format_exc()}")
            return None, None, error_msg

    def analyze_nceer(self, 
                     csv_path: str, 
                     output_dir: str,
                     fault_gdf: Optional[gpd.GeoDataFrame] = None,
                     em_value: float = 72) -> Tuple[Optional[pd.DataFrame], Optional[Dict], Optional[str]]:
        """執行 NCEER 分析"""
        print("\n" + "="*60)
        print("開始 NCEER (2001) 液化分析")
        print("="*60)
        
        try:
            # 初始化NCEER分析器
            nceer_analyzer = NCEER(default_em=em_value)
            
            # 執行分析
            final_df, lpi_summary, _ = nceer_analyzer.NCEER_main(
                show_gui=False,
                input_file_path=csv_path,
                output_file_path=os.path.join(output_dir, 'raw_results', 'NCEER_complete_results.csv'),
                use_fault_data=(fault_gdf is not None),
                fault_shapefile_path=None,
                custom_em=em_value
            )
            
            if final_df is not None:
                print("✅ NCEER 分析完成")
                return final_df, lpi_summary, None
            else:
                error_msg = "NCEER 分析失敗：未產生分析結果"
                print(f"❌ {error_msg}")
                return None, None, error_msg
                
        except Exception as e:
            error_msg = f"NCEER 分析過程中發生錯誤：{str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            print(f"詳細錯誤：{traceback.format_exc()}")
            return None, None, error_msg

    def generate_simplified_reports(self, 
                                  analyzer, 
                                  final_df: pd.DataFrame, 
                                  output_dir: str) -> Dict[str, str]:
        """生成簡化報表"""
        print("\n=== 生成簡化報表 ===")
        
        simplified_reports = {}
        scenarios = ["Design", "MidEq", "MaxEq"]
        
        simplified_dir = os.path.join(output_dir, 'simplified_reports')
        
        for scenario in scenarios:
            try:
                report_file = analyzer.generate_simplified_report(
                    final_df, 
                    output_dir=simplified_dir, 
                    scenario=scenario
                )
                if report_file:
                    simplified_reports[scenario] = report_file
                    print(f"✅ {scenario} 情境簡化報表生成完成")
            except Exception as e:
                print(f"❌ 生成 {scenario} 情境簡化報表時發生錯誤：{e}")
        
        return simplified_reports

    def generate_individual_well_reports(self, 
                                       final_df: pd.DataFrame, 
                                       output_dir: str) -> Dict[str, str]:
        """為每個鑽孔生成獨立報表和圖表"""
        print("\n=== 生成個別鑽孔報表 ===")
        
        well_reports = {}
        well_ids = final_df['鑽孔編號'].unique()
        individual_dir = os.path.join(output_dir, 'individual_wells')
        
        try:
            # 導入報表生成模組
            from .report import create_liquefaction_excel_from_dataframe, LiquefactionChartGenerator
            
            chart_generator = LiquefactionChartGenerator(
                n_chart_size=(5, 10),
                fs_chart_size=(5, 10)
            )
            
            for i, well_id in enumerate(well_ids, 1):
                print(f"進度 [{i}/{len(well_ids)}] 處理鑽孔：{well_id}")
                
                try:
                    # 建立鑽孔資料夾
                    well_dir = os.path.join(individual_dir, str(well_id))
                    os.makedirs(well_dir, exist_ok=True)
                    
                    # 篩選該鑽孔的資料
                    well_data = final_df[final_df['鑽孔編號'] == well_id].copy()
                    
                    if len(well_data) == 0:
                        print(f"  ⚠️ 鑽孔 {well_id} 沒有資料，跳過")
                        continue
                    
                    # 生成Excel報表
                    current_date = datetime.now().strftime("%m%d")
                    excel_filename = f"{well_id}_液化分析報表_{current_date}.xlsx"
                    excel_filepath = os.path.join(well_dir, excel_filename)
                    
                    create_liquefaction_excel_from_dataframe(well_data, excel_filepath)
                    
                    # 生成圖表
                    charts = []
                    chart1 = chart_generator.generate_depth_n_chart(well_data, well_id, well_dir)
                    if chart1:
                        charts.append(chart1)
                    
                    chart2 = chart_generator.generate_depth_fs_chart(well_data, well_id, well_dir)
                    if chart2:
                        charts.append(chart2)
                    
                    chart3 = chart_generator.generate_soil_column_chart(well_data, well_id, well_dir)
                    if chart3:
                        charts.append(chart3)
                    
                    well_reports[well_id] = {
                        'excel_report': excel_filepath,
                        'charts': charts,
                        'directory': well_dir
                    }
                    
                    print(f"  ✅ 鑽孔 {well_id} 處理完成")
                    
                except Exception as e:
                    print(f"  ❌ 處理鑽孔 {well_id} 時發生錯誤：{e}")
                    continue
            
            return well_reports
            
        except ImportError as e:
            print(f"❌ 無法導入報表生成模組：{e}")
            return {}
        except Exception as e:
            print(f"❌ 生成個別鑽孔報表時發生錯誤：{e}")
            return {}

    def generate_summary_report(self, 
                              analyzer, 
                              final_df: pd.DataFrame, 
                              output_dir: str) -> Optional[str]:
        """生成LPI摘要報表"""
        print("\n=== 生成LPI摘要報表 ===")
        
        try:
            summary_dir = os.path.join(output_dir, 'summary')
            lpi_summary_file = analyzer.generate_lpi_summary_report(final_df, summary_dir)
            
            if lpi_summary_file:
                print("✅ LPI摘要報表生成完成")
                return lpi_summary_file
            else:
                print("❌ LPI摘要報表生成失敗")
                return None
                
        except Exception as e:
            print(f"❌ 生成LPI摘要報表時發生錯誤：{e}")
            return None

    def create_analysis_package(self, analysis_dir: str, method: str) -> str:
        """將分析結果打包成ZIP檔案"""
        print("\n=== 打包分析結果 ===")
        
        try:
            # 創建ZIP檔案
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{method}_analysis_results_{timestamp}.zip"
            zip_path = os.path.join(os.path.dirname(analysis_dir), zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(analysis_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, analysis_dir)
                        zipf.write(file_path, arcname)
            
            print(f"✅ 分析結果已打包至：{zip_filename}")
            return zip_path
            
        except Exception as e:
            print(f"❌ 打包分析結果時發生錯誤：{e}")
            return None

    def analyze(self, 
               method: str,
               csv_content: bytes,
               shapefile_content: bytes = None,
               em_value: float = 72,
               unit_weight_unit: str = "t/m3") -> Dict[str, Any]:
        """
        主要分析函數
        
        Args:
            method: 分析方法 ('HBF' 或 'NCEER')
            csv_content: CSV檔案內容
            shapefile_content: Shapefile檔案內容 (可選)
            em_value: SPT錘擊能量效率
            unit_weight_unit: 統體單位重單位 ('t/m3' 或 'kN/m3')
            
        Returns:
            Dict: 包含分析結果和檔案路徑的字典
        """
        
        print(f"\n{'='*80}")
        print(f"開始 {self.supported_methods.get(method, method)} 液化分析")
        print(f"{'='*80}")
        
        result = {
            'success': False,
            'method': method,
            'error_message': None,
            'analysis_directory': None,
            'zip_file_path': None,
            'summary': {}
        }
        
        try:
            # 1. 驗證分析方法
            if method not in self.supported_methods:
                result['error_message'] = f"不支援的分析方法：{method}"
                return result
            
            # 2. 準備輸入資料
            csv_path, error_msg = self.prepare_input_data(csv_content, method)
            if error_msg:
                result['error_message'] = error_msg
                return result
            
            # 3. 準備斷層資料
            fault_gdf = self.prepare_fault_data(shapefile_content)
            
            # 4. 創建分析目錄
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            analysis_dir = self.create_analysis_directory(method, timestamp)
            result['analysis_directory'] = analysis_dir
            
            print(f"分析結果將儲存至：{analysis_dir}")
            
            # 5. 執行對應的分析方法
            final_df = None
            lpi_summary = None
            analyzer = None
            
            if method == 'HBF':
                final_df, lpi_summary, error_msg = self.analyze_hbf(
                    csv_path, analysis_dir, fault_gdf, em_value, unit_weight_unit
                )
                if final_df is not None:
                    analyzer = HBF(default_em=em_value)
                    
            elif method == 'NCEER':
                final_df, lpi_summary, error_msg = self.analyze_nceer(
                    csv_path, analysis_dir, fault_gdf, em_value
                )
                if final_df is not None:
                    analyzer = NCEER(default_em=em_value)
            
            if error_msg:
                result['error_message'] = error_msg
                return result
            
            if final_df is None or analyzer is None:
                result['error_message'] = "分析失敗：未產生有效結果"
                return result
            
            # 6. 生成各種報表
            print("\n" + "="*60)
            print("=== 後處理：生成報表和圖表 ===")
            print("="*60)
            
            # 簡化報表
            simplified_reports = self.generate_simplified_reports(analyzer, final_df, analysis_dir)
            
            # 個別鑽孔報表
            individual_reports = self.generate_individual_well_reports(final_df, analysis_dir)
            
            # 摘要報表
            summary_report = self.generate_summary_report(analyzer, final_df, analysis_dir)
            
            # 7. 打包結果
            zip_path = self.create_analysis_package(analysis_dir, method)
            if zip_path:
                result['zip_file_path'] = zip_path
            
            # 8. 整理分析摘要
            well_count = len(final_df['鑽孔編號'].unique()) if '鑽孔編號' in final_df.columns else 0
            layer_count = len(final_df)
            
            result['summary'] = {
                'well_count': well_count,
                'layer_count': layer_count,
                'analysis_method': self.supported_methods[method],
                'em_value': em_value,
                'unit_weight_unit': unit_weight_unit,
                'fault_data_used': fault_gdf is not None,
                'simplified_reports': list(simplified_reports.keys()),
                'individual_reports_count': len(individual_reports),
                'has_summary_report': summary_report is not None,
                'lpi_summary': lpi_summary
            }
            
            # 9. 清理臨時檔案
            try:
                os.unlink(csv_path)
            except:
                pass
            
            result['success'] = True
            
            print(f"\n{'='*80}")
            print(f"🎉 {self.supported_methods[method]} 分析完成！")
            print(f"{'='*80}")
            print(f"分析摘要：")
            print(f"  鑽孔數量：{well_count}")
            print(f"  土層數量：{layer_count}")
            print(f"  Em值：{em_value}%")
            print(f"  統體單位重單位：{unit_weight_unit}")
            print(f"  使用斷層資料：{'是' if fault_gdf is not None else '否'}")
            print(f"  結果目錄：{analysis_dir}")
            if zip_path:
                print(f"  打包檔案：{os.path.basename(zip_path)}")
            print(f"{'='*80}")
            
            return result
            
        except Exception as e:
            result['error_message'] = f"分析過程中發生未預期的錯誤：{str(e)}"
            print(f"❌ {result['error_message']}")
            import traceback
            print(f"詳細錯誤：{traceback.format_exc()}")
            
            # 清理臨時檔案
            try:
                if 'csv_path' in locals() and csv_path:
                    os.unlink(csv_path)
            except:
                pass
                
            return result

    def get_analysis_status(self, analysis_dir: str) -> Dict[str, Any]:
        """取得分析狀態和結果摘要"""
        try:
            if not os.path.exists(analysis_dir):
                return {'exists': False}
            
            status = {'exists': True}
            
            # 檢查各子目錄的檔案
            subdirs = ['raw_results', 'simplified_reports', 'individual_wells', 'summary']
            for subdir in subdirs:
                subdir_path = os.path.join(analysis_dir, subdir)
                if os.path.exists(subdir_path):
                    files = [f for f in os.listdir(subdir_path) if os.path.isfile(os.path.join(subdir_path, f))]
                    status[f'{subdir}_files'] = files
                else:
                    status[f'{subdir}_files'] = []
            
            return status
            
        except Exception as e:
            return {'exists': False, 'error': str(e)}

    def cleanup_old_results(self, days_old: int = 7):
        """清理舊的分析結果"""
        try:
            if not os.path.exists(self.results_base_dir):
                return
            
            import time
            current_time = time.time()
            cutoff_time = current_time - (days_old * 24 * 60 * 60)
            
            for item in os.listdir(self.results_base_dir):
                item_path = os.path.join(self.results_base_dir, item)
                if os.path.isdir(item_path):
                    if os.path.getctime(item_path) < cutoff_time:
                        shutil.rmtree(item_path)
                        print(f"已清理舊結果目錄：{item}")
                elif item.endswith('.zip'):
                    if os.path.getctime(item_path) < cutoff_time:
                        os.remove(item_path)
                        print(f"已清理舊ZIP檔案：{item}")
                        
        except Exception as e:
            print(f"清理舊結果時發生錯誤：{e}")


# 建議的Django設定
"""
在 settings.py 中加入：

# 液化分析結果儲存目錄
LIQUEFACTION_RESULTS_DIR = os.path.join(MEDIA_ROOT, 'liquefaction_results')

# 確保目錄存在
os.makedirs(LIQUEFACTION_RESULTS_DIR, exist_ok=True)

# 可下載檔案的URL設定
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

在 urls.py 中加入：
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ... 其他URL模式
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

目錄結構建議：
project_root/
├── media/
│   └── liquefaction_results/
│       ├── HBF_20241219_143022/
│       │   ├── raw_results/
│       │   ├── simplified_reports/
│       │   ├── individual_wells/
│       │   ├── charts/
│       │   └── summary/
│       ├── NCEER_20241219_143155/
│       └── analysis_results.zip
"""