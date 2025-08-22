from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings
import uuid
import os
from datetime import datetime


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
    
    # 分析設定 - 修改為可選，預設為空
    analysis_method = models.CharField(
        max_length=10,
        choices=[
            ('HBF', 'HBF (2012)'),
            ('NCEER', 'NCEER'),
            ('AIJ', 'AIJ'),
            ('JRA', 'JRA'),
        ],
        blank=True,  # 新增：允許為空
        null=True,   # 新增：數據庫可為 NULL
        verbose_name="預設分析方法",
        help_text="可在分析時選擇其他方法"
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
        if self.analysis_method:
            return f"{self.name} ({self.get_analysis_method_display()})"
        else:
            return f"{self.name} (未設定方法)"
    
    def get_display_method(self):
        """獲取顯示用的分析方法"""
        if self.analysis_method:
            return self.get_analysis_method_display()
        else:
            return "待選擇"
    # 在類別的最後添加這個方法
    def get_fault_shapefile_path(self):
        """取得斷層 Shapefile 檔案路徑"""
        if self.fault_shapefile and self.fault_shapefile.name:
            # 如果有上傳自訂的斷層檔案，使用自訂檔案
            return self.fault_shapefile.path
        else:
            # 使用預設的斷層檔案
            from django.conf import settings
            import os
            default_shapefile = get_default_shapefile_path()
            default_path = os.path.join(settings.MEDIA_ROOT, default_shapefile)
            
            # 檢查預設檔案是否存在
            if os.path.exists(default_path):
                return default_path
            else:
                # 如果預設檔案不存在，返回 None
                print(f"⚠️ 預設斷層檔案不存在：{default_path}")
                return None
    
    def has_fault_data(self):
        """檢查是否有可用的斷層數據"""
        return self.get_fault_shapefile_path() is not None
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
    """土層資料模型 - 擴展版本"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    borehole = models.ForeignKey(BoreholeData, on_delete=models.CASCADE, related_name='soil_layers', verbose_name="所屬鑽孔")
    
    # 基本資訊
    project_name = models.CharField(max_length=200, blank=True, verbose_name="計畫名稱")
    borehole_id_ref = models.CharField(max_length=100, blank=True, verbose_name="鑽孔編號參考")  # 冗餘，但方便查詢
    test_number = models.CharField(max_length=50, blank=True, verbose_name="試驗編號")
    sample_id = models.CharField(max_length=50, blank=True, verbose_name="取樣編號")
    
    # 深度資訊
    top_depth = models.FloatField(verbose_name="上限深度 (m)")
    bottom_depth = models.FloatField(verbose_name="下限深度 (m)")
    
    # SPT資料
    spt_n = models.FloatField(null=True, blank=True, verbose_name="SPT-N值")
    n_value = models.FloatField(null=True, blank=True, verbose_name="N_value")  # 可能與spt_n相同
    
    # 土壤分類
    uscs = models.CharField(max_length=10, blank=True, verbose_name="統一土壤分類")
    
    # 物理性質
    water_content = models.FloatField(null=True, blank=True, verbose_name="含水量 (%)")
    liquid_limit = models.FloatField(null=True, blank=True, verbose_name="液性限度 (%)")
    plastic_index = models.FloatField(null=True, blank=True, verbose_name="塑性指數 (%)")
    specific_gravity = models.FloatField(null=True, blank=True, verbose_name="比重")
    
    # 粒徑分析
    gravel_percent = models.FloatField(null=True, blank=True, verbose_name="礫石含量 (%)")
    sand_percent = models.FloatField(null=True, blank=True, verbose_name="砂土含量 (%)")
    silt_percent = models.FloatField(null=True, blank=True, verbose_name="粉土含量 (%)")
    clay_percent = models.FloatField(null=True, blank=True, verbose_name="黏土含量 (%)")
    fines_content = models.FloatField(null=True, blank=True, verbose_name="細料含量 (%)")  # 保留原有
    
    # 密度相關
    unit_weight = models.FloatField(null=True, blank=True, verbose_name="統體單位重 (t/m³)")
    bulk_density = models.FloatField(null=True, blank=True, verbose_name="統體密度 (t/m³)")
    void_ratio = models.FloatField(null=True, blank=True, verbose_name="空隙比")
    
    # 粒徑分佈參數
    d10 = models.FloatField(null=True, blank=True, verbose_name="D10 (mm)")
    d30 = models.FloatField(null=True, blank=True, verbose_name="D30 (mm)")
    d60 = models.FloatField(null=True, blank=True, verbose_name="D60 (mm)")
    
    # 座標和高程資訊（冗餘，但方便查詢）
    twd97_x = models.FloatField(null=True, blank=True, verbose_name="TWD97_X")
    twd97_y = models.FloatField(null=True, blank=True, verbose_name="TWD97_Y")
    water_depth = models.FloatField(null=True, blank=True, verbose_name="地下水位深度 (m)")
    ground_elevation = models.FloatField(null=True, blank=True, verbose_name="鑽孔地表高程 (m)")
    
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
    
    def save(self, *args, **kwargs):
        """保存時自動填充一些冗餘字段"""
        # 若 n_value 尚未設定但 spt_n 有值，自動將 n_value 設為 spt_n
        if self.n_value is None and self.spt_n is not None:
            self.n_value = self.spt_n
        if self.borehole:
            # 自動填充計畫名稱
            if not self.project_name:
                self.project_name = self.borehole.project.name
            
            # 自動填充鑽孔編號參考
            if not self.borehole_id_ref:
                self.borehole_id_ref = self.borehole.borehole_id
            
            # 自動填充座標資訊
            if not self.twd97_x:
                self.twd97_x = self.borehole.twd97_x
            if not self.twd97_y:
                self.twd97_y = self.borehole.twd97_y
            if not self.water_depth:
                self.water_depth = self.borehole.water_depth
            if not self.ground_elevation:
                self.ground_elevation = self.borehole.surface_elevation
        
        super().save(*args, **kwargs)

class AnalysisResult(models.Model):
    """液化分析結果模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    soil_layer = models.OneToOneField(SoilLayer, on_delete=models.CASCADE, related_name='analysis_result', verbose_name="所屬土層")
    
    # 新增：分析方法欄位
    analysis_method = models.CharField(
        max_length=10,
        choices=[
            ('HBF', 'HBF (2012)'),
            ('NCEER', 'NCEER'),
            ('AIJ', 'AIJ'),
            ('JRA', 'JRA'),
        ],
        verbose_name="分析方法"
    )

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
    
    def get_output_directory(self):
        """獲取專案輸出目錄"""
        from django.conf import settings
        safe_name = "".join(c for c in self.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        dir_name = f"{self.id}_{safe_name}_{self.analysis_method}"
        return os.path.join(settings.ANALYSIS_OUTPUT_ROOT, dir_name)
    
    def list_output_files(self):
        """列出專案的所有輸出檔案"""
        output_dir = self.get_output_directory()
        if not os.path.exists(output_dir):
            return []
        
        files = []
        for filename in os.listdir(output_dir):
            if filename.startswith(str(self.id)):
                file_path = os.path.join(output_dir, filename)
                file_info = {
                    'name': filename,
                    'path': file_path,
                    'size': os.path.getsize(file_path),
                    'modified': datetime.fromtimestamp(os.path.getmtime(file_path))
                }
                files.append(file_info)
        
        return sorted(files, key=lambda x: x['modified'], reverse=True)
    
    def cleanup_output_files(self):
        """清理專案的輸出檔案"""
        output_dir = self.get_output_directory()
        if os.path.exists(output_dir):
            import shutil
            shutil.rmtree(output_dir)    

    class Meta:
        verbose_name = "分析結果"
        verbose_name_plural = "分析結果"
        # 確保同一土層的同一分析方法只有一個結果
        unique_together = ['soil_layer', 'analysis_method']
    
    def __str__(self):
        return f"{self.soil_layer} - {self.get_analysis_method_display()}"