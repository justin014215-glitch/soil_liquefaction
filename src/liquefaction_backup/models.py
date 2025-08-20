from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings
import uuid
import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone



class Project(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


def get_default_shapefile_path():
    """取得預設shapefile路徑"""
    return 'default_shapefiles/110全臺36條活動斷層數值檔(111年編修)_1110727.shp'


class AnalysisProject(models.Model):
    """分析專案模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="使用者")
    name = models.CharField(max_length=200, verbose_name="專案名稱")
    description = models.TextField(blank=True, verbose_name="專案描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新時間")
    
    # 上傳的原始檔案
    source_file = models.FileField(upload_to='uploads/csv/', verbose_name="上傳檔案")
    
    # 分析設定
    analysis_method = models.CharField(
        max_length=10,
        choices=[
            ('HBF', 'HBF (2012)'),
            ('NCEER', 'NCEER'),
            ('AIJ', 'AIJ'),
            ('JRA', 'JRA'),
        ],
        default='HBF',
        verbose_name="分析方法"
    )
    
    # 分析參數
    em_value = models.FloatField(
        default=72,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="錘擊能量效率 Em (%)"
    )
    
    unit_weight_unit = models.CharField(
        max_length=10,
        choices=[
            ('t/m3', 't/m³'),
            ('kN/m3', 'kN/m³'),
        ],
        default='t/m3',
        verbose_name="統體單位重單位"
    )
    
    use_fault_data = models.BooleanField(default=True, verbose_name="使用斷層距離參數")
    fault_shapefile = models.FileField(
        upload_to='uploads/shapefiles/', 
        blank=True, 
        null=True, 
        verbose_name="斷層資料檔案",
        help_text="若不上傳將使用系統預設的活動斷層資料"
    )
    
    # 分析狀態
    STATUS_CHOICES = [
        ('pending', '等待分析'),
        ('processing', '分析中'),
        ('completed', '已完成'),
        ('error', '分析錯誤'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="狀態")
    error_message = models.TextField(blank=True, verbose_name="錯誤訊息")
    
    class Meta:
        verbose_name = "分析專案"
        verbose_name_plural = "分析專案"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.get_analysis_method_display()})"
    
    def get_fault_shapefile_path(self):
        """取得斷層shapefile檔案路徑"""
        if self.fault_shapefile and self.fault_shapefile.name:
            return self.fault_shapefile.path
        else:
            # 使用預設的shapefile
            default_path = os.path.join(settings.MEDIA_ROOT, get_default_shapefile_path())
            if os.path.exists(default_path):
                return default_path
            else:
                raise FileNotFoundError(f"預設斷層檔案不存在: {default_path}")
    
    def get_fault_shapefile_url(self):
        """取得斷層shapefile檔案URL"""
        if self.fault_shapefile and self.fault_shapefile.name:
            return self.fault_shapefile.url
        else:
            # 使用預設的shapefile URL
            return f"{settings.MEDIA_URL}{get_default_shapefile_path()}"

    
    # 新增欄位以支援新的分析引擎
    analysis_result_path = models.CharField(
        max_length=500, 
        blank=True, 
        null=True,
        help_text='分析結果目錄路徑'
    )
    
    analyzed_at = models.DateTimeField(
        blank=True, 
        null=True,
        help_text='分析完成時間'
    )
    
    analysis_duration = models.DurationField(
        blank=True, 
        null=True,
        help_text='分析執行時長'
    )
    
    total_wells = models.PositiveIntegerField(
        default=0,
        help_text='總鑽孔數量'
    )
    
    total_layers = models.PositiveIntegerField(
        default=0,
        help_text='總土層數量'
    )
    
    # 更新狀態選擇
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('ready', '準備就緒'),
        ('processing', '分析中'),
        ('completed', '已完成'),
        ('error', '錯誤'),
        ('cancelled', '已取消'),
    ]
    
    # 更新分析方法選擇
    ANALYSIS_METHOD_CHOICES = [
        ('HBF', 'HBF (2012) 方法'),
        ('NCEER', 'NCEER (2001) 方法'),
        # 未來可以添加更多方法
    ]
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = '液化分析專案'
        verbose_name_plural = '液化分析專案'
    
    def get_analysis_summary(self):
        """獲取分析摘要資訊"""
        if self.status != 'completed':
            return None
        
        summary = {
            'project_name': self.name,
            'analysis_method': self.get_analysis_method_display(),
            'total_wells': self.total_wells,
            'total_layers': self.total_layers,
            'analyzed_at': self.analyzed_at,
            'analysis_duration': self.analysis_duration,
            'em_value': self.em_value,
            'unit_weight_unit': self.unit_weight_unit,
            'used_fault_data': self.use_fault_data,
        }
        
        return summary
    
    def get_result_files(self):
        """獲取分析結果檔案清單"""
        if not self.analysis_result_path:
            return []
        
        import os
        from pathlib import Path
        
        result_files = []
        
        try:
            result_dir = Path(self.analysis_result_path)
            
            # 查找 ZIP 檔案
            zip_files = list(result_dir.parent.glob('*.zip'))
            for zip_file in zip_files:
                result_files.append({
                    'name': zip_file.name,
                    'path': str(zip_file),
                    'size': zip_file.stat().st_size,
                    'type': 'zip',
                    'created': timezone.datetime.fromtimestamp(zip_file.stat().st_ctime)
                })
            
            # 查找子目錄中的檔案
            if result_dir.exists():
                subdirs = ['simplified_reports', 'summary', 'raw_results']
                for subdir in subdirs:
                    subdir_path = result_dir / subdir
                    if subdir_path.exists():
                        for file_path in subdir_path.glob('*.*'):
                            result_files.append({
                                'name': file_path.name,
                                'path': str(file_path),
                                'size': file_path.stat().st_size,
                                'type': subdir,
                                'created': timezone.datetime.fromtimestamp(file_path.stat().st_ctime)
                            })
            
        except Exception as e:
            print(f"獲取結果檔案時發生錯誤：{e}")
        
        return result_files
    
    def clean_analysis_results(self):
        """清理分析結果檔案"""
        if self.analysis_result_path:
            try:
                import shutil
                import os
                
                # 刪除結果目錄
                if os.path.exists(self.analysis_result_path):
                    shutil.rmtree(self.analysis_result_path)
                
                # 刪除ZIP檔案
                from pathlib import Path
                result_dir = Path(self.analysis_result_path)
                zip_files = list(result_dir.parent.glob('*.zip'))
                for zip_file in zip_files:
                    if zip_file.exists():
                        zip_file.unlink()
                
                # 清空相關欄位
                self.analysis_result_path = None
                self.analyzed_at = None
                self.analysis_duration = None
                self.status = 'ready' if self.total_layers > 0 else 'draft'
                self.save()
                
                return True
                
            except Exception as e:
                print(f"清理分析結果時發生錯誤：{e}")
                return False
        
        return True


# 新增分析日誌模型
class AnalysisLog(models.Model):
    """分析執行日誌"""
    
    project = models.ForeignKey(
        AnalysisProject,
        on_delete=models.CASCADE,
        related_name='analysis_logs',
        verbose_name='專案'
    )
    
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='開始時間'
    )
    
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='完成時間'
    )
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('running', '執行中'),
            ('completed', '已完成'),
            ('failed', '失敗'),
            ('cancelled', '已取消'),
        ],
        default='running',
        verbose_name='狀態'
    )
    
    log_message = models.TextField(
        blank=True,
        verbose_name='日誌訊息'
    )
    
    error_message = models.TextField(
        blank=True,
        verbose_name='錯誤訊息'
    )
    
    analysis_parameters = models.JSONField(
        default=dict,
        verbose_name='分析參數'
    )
    
    result_summary = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='結果摘要'
    )
    
    class Meta:
        ordering = ['-started_at']
        verbose_name = '分析日誌'
        verbose_name_plural = '分析日誌'
    
    def __str__(self):
        return f"{self.project.name} - {self.get_status_display()} ({self.started_at})"
    
    @property
    def duration(self):
        """計算執行時長"""
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None
    


# 其他模型保持不變...
class BoreholeData(models.Model):
    """鑽孔資料模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(AnalysisProject, on_delete=models.CASCADE, related_name='boreholes', verbose_name="所屬專案")
    
    # 基本資訊
    borehole_id = models.CharField(max_length=100, verbose_name="鑽孔編號")
    
    # 座標資訊
    twd97_x = models.FloatField(verbose_name="TWD97 X座標")
    twd97_y = models.FloatField(verbose_name="TWD97 Y座標")
    surface_elevation = models.FloatField(null=True, blank=True, verbose_name="地表高程 (m)")
    
    # 地下水位
    water_depth = models.FloatField(default=0, verbose_name="地下水位深度 (m)")
    
    # 地震參數查詢結果
    city = models.CharField(max_length=50, blank=True, verbose_name="縣市")
    district = models.CharField(max_length=50, blank=True, verbose_name="鄉鎮區")
    village = models.CharField(max_length=50, blank=True, verbose_name="里")
    taipei_basin_zone = models.CharField(max_length=20, blank=True, verbose_name="台北盆地微分區")
    
    # 地震參數
    base_mw = models.FloatField(null=True, blank=True, verbose_name="基準地震規模 Mw")
    sds = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度係數 SDS")
    sms = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度係數 SMS")
    sd1 = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度係數 SD1")
    sm1 = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度係數 SM1")
    
    # 資料來源
    data_source = models.CharField(max_length=100, blank=True, verbose_name="地震參數來源")
    nearby_fault = models.CharField(max_length=200, blank=True, verbose_name="鄰近斷層")
    
    # 場址參數
    vs30 = models.FloatField(null=True, blank=True, verbose_name="平均剪力波速 Vs30 (m/s)")
    site_class = models.CharField(max_length=20, blank=True, verbose_name="地盤分類")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    
    class Meta:
        verbose_name = "鑽孔資料"
        verbose_name_plural = "鑽孔資料"
        unique_together = ['project', 'borehole_id']
        ordering = ['borehole_id']
    
    def __str__(self):
        return f"{self.project.name} - {self.borehole_id}"


class SoilLayer(models.Model):
    """土層資料模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    borehole = models.ForeignKey(BoreholeData, on_delete=models.CASCADE, related_name='soil_layers', verbose_name="所屬鑽孔")
    
    # 深度資訊
    top_depth = models.FloatField(verbose_name="上限深度 (m)")
    bottom_depth = models.FloatField(verbose_name="下限深度 (m)")
    
    # 取樣資訊
    sample_id = models.CharField(max_length=50, blank=True, verbose_name="取樣編號")
    
    # 土壤分類
    uscs = models.CharField(max_length=10, blank=True, verbose_name="統一土壤分類")
    
    # SPT資料
    spt_n = models.FloatField(null=True, blank=True, verbose_name="SPT-N值")
    
    # 物理性質
    unit_weight = models.FloatField(null=True, blank=True, verbose_name="統體單位重 (t/m³)")
    water_content = models.FloatField(null=True, blank=True, verbose_name="含水量 (%)")
    
    # 粒徑分析
    gravel_percent = models.FloatField(null=True, blank=True, verbose_name="礫石含量 (%)")
    sand_percent = models.FloatField(null=True, blank=True, verbose_name="砂土含量 (%)")
    silt_percent = models.FloatField(null=True, blank=True, verbose_name="粉土含量 (%)")
    clay_percent = models.FloatField(null=True, blank=True, verbose_name="黏土含量 (%)")
    fines_content = models.FloatField(null=True, blank=True, verbose_name="細料含量 (%)")
    
    # 塑性指數
    plastic_index = models.FloatField(null=True, blank=True, verbose_name="塑性指數 (%)")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    
    class Meta:
        verbose_name = "土層資料"
        verbose_name_plural = "土層資料"
        ordering = ['borehole', 'top_depth']
    
    def __str__(self):
        return f"{self.borehole.borehole_id} - {self.top_depth}~{self.bottom_depth}m"
    
    @property
    def thickness(self):
        """土層厚度"""
        return self.bottom_depth - self.top_depth


class AnalysisResult(models.Model):
    """液化分析結果模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soil_layer = models.OneToOneField(SoilLayer, on_delete=models.CASCADE, related_name='analysis_result', verbose_name="所屬土層")
    
    # 計算的基本參數
    soil_depth = models.FloatField(null=True, blank=True, verbose_name="土層深度 (m)")
    mid_depth = models.FloatField(null=True, blank=True, verbose_name="土層中點深度 (m)")
    analysis_depth = models.FloatField(null=True, blank=True, verbose_name="分析點深度 (m)")
    
    # 應力計算
    sigma_v = models.FloatField(null=True, blank=True, verbose_name="總垂直應力 σv (t/m²)")
    sigma_v_csr = models.FloatField(null=True, blank=True, verbose_name="有效垂直應力 σ'v (t/m²)")
    sigma_v_crr = models.FloatField(null=True, blank=True, verbose_name="CRR有效垂直應力 (t/m²)")
    
    # SPT相關參數
    n60 = models.FloatField(null=True, blank=True, verbose_name="N60")
    n1_60 = models.FloatField(null=True, blank=True, verbose_name="N1_60")
    n1_60cs = models.FloatField(null=True, blank=True, verbose_name="N1_60cs")
    
    # 剪力波速
    vs = models.FloatField(null=True, blank=True, verbose_name="剪力波速 Vs (m/s)")
    
    # 液化抗力
    crr_7_5 = models.FloatField(null=True, blank=True, verbose_name="CRR7.5")
    
    # 設計地震結果
    mw_design = models.FloatField(null=True, blank=True, verbose_name="設計地震規模")
    a_value_design = models.FloatField(null=True, blank=True, verbose_name="設計地表加速度")
    sd_s_design = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度 SD_S")
    sm_s_design = models.FloatField(null=True, blank=True, verbose_name="設計譜加速度 SM_S")
    msf_design = models.FloatField(null=True, blank=True, verbose_name="設計規模修正因子")
    rd_design = models.FloatField(null=True, blank=True, verbose_name="設計應力折減係數")
    csr_design = models.FloatField(null=True, blank=True, verbose_name="設計反覆剪應力比")
    crr_design = models.FloatField(null=True, blank=True, verbose_name="設計液化抗力")
    fs_design = models.FloatField(null=True, blank=True, verbose_name="設計安全係數")
    lpi_design = models.FloatField(null=True, blank=True, verbose_name="設計液化潛能指數")
    
    # 中小地震結果
    mw_mid = models.FloatField(null=True, blank=True, verbose_name="中小地震規模")
    a_value_mid = models.FloatField(null=True, blank=True, verbose_name="中小地表加速度")
    sd_s_mid = models.FloatField(null=True, blank=True, verbose_name="中小譜加速度 SD_S")
    sm_s_mid = models.FloatField(null=True, blank=True, verbose_name="中小譜加速度 SM_S")
    msf_mid = models.FloatField(null=True, blank=True, verbose_name="中小規模修正因子")
    rd_mid = models.FloatField(null=True, blank=True, verbose_name="中小應力折減係數")
    csr_mid = models.FloatField(null=True, blank=True, verbose_name="中小反覆剪應力比")
    crr_mid = models.FloatField(null=True, blank=True, verbose_name="中小液化抗力")
    fs_mid = models.FloatField(null=True, blank=True, verbose_name="中小安全係數")
    lpi_mid = models.FloatField(null=True, blank=True, verbose_name="中小液化潛能指數")
    
    # 最大地震結果
    mw_max = models.FloatField(null=True, blank=True, verbose_name="最大地震規模")
    a_value_max = models.FloatField(null=True, blank=True, verbose_name="最大地表加速度")
    sd_s_max = models.FloatField(null=True, blank=True, verbose_name="最大譜加速度 SD_S")
    sm_s_max = models.FloatField(null=True, blank=True, verbose_name="最大譜加速度 SM_S")
    msf_max = models.FloatField(null=True, blank=True, verbose_name="最大規模修正因子")
    rd_max = models.FloatField(null=True, blank=True, verbose_name="最大應力折減係數")
    csr_max = models.FloatField(null=True, blank=True, verbose_name="最大反覆剪應力比")
    crr_max = models.FloatField(null=True, blank=True, verbose_name="最大液化抗力")
    fs_max = models.FloatField(null=True, blank=True, verbose_name="最大安全係數")
    lpi_max = models.FloatField(null=True, blank=True, verbose_name="最大液化潛能指數")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    
    class Meta:
        verbose_name = "分析結果"
        verbose_name_plural = "分析結果"
    
    def __str__(self):
        return f"{self.soil_layer} - 分析結果"
    


