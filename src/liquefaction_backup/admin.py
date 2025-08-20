from django.contrib import admin
from .models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult


@admin.register(AnalysisProject)
class AnalysisProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'analysis_method', 'status', 'created_at', 'updated_at')
    list_filter = ('analysis_method', 'status', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本資訊', {
            'fields': ('user', 'name', 'description')
        }),
        ('檔案與設定', {
            'fields': ('source_file', 'analysis_method', 'em_value', 'unit_weight_unit')
        }),
        ('斷層參數', {
            'fields': ('use_fault_data', 'fault_shapefile')
        }),
        ('狀態', {
            'fields': ('status', 'error_message')
        }),
        ('時間戳記', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BoreholeData)
class BoreholeDataAdmin(admin.ModelAdmin):
    list_display = ('borehole_id', 'project', 'city', 'district', 'village', 'twd97_x', 'twd97_y')
    list_filter = ('project', 'city', 'district', 'taipei_basin_zone')
    search_fields = ('borehole_id', 'city', 'district', 'village')
    readonly_fields = ('created_at',)
    fieldsets = (
        ('基本資訊', {
            'fields': ('project', 'borehole_id')
        }),
        ('座標與高程', {
            'fields': ('twd97_x', 'twd97_y', 'surface_elevation', 'water_depth')
        }),
        ('行政區域', {
            'fields': ('city', 'district', 'village', 'taipei_basin_zone')
        }),
        ('地震參數', {
            'fields': ('base_mw', 'sds', 'sms', 'sd1', 'sm1', 'data_source', 'nearby_fault')
        }),
        ('場址參數', {
            'fields': ('vs30', 'site_class')
        }),
        ('時間戳記', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(SoilLayer)
class SoilLayerAdmin(admin.ModelAdmin):
    list_display = ('borehole', 'top_depth', 'bottom_depth', 'uscs', 'spt_n', 'thickness')
    list_filter = ('borehole__project', 'uscs')
    search_fields = ('borehole__borehole_id', 'sample_id', 'uscs')
    readonly_fields = ('created_at',)
    fieldsets = (
        ('基本資訊', {
            'fields': ('borehole', 'top_depth', 'bottom_depth', 'sample_id', 'uscs')
        }),
        ('SPT資料', {
            'fields': ('spt_n',)
        }),
        ('物理性質', {
            'fields': ('unit_weight', 'water_content')
        }),
        ('粒徑分析', {
            'fields': ('gravel_percent', 'sand_percent', 'silt_percent', 'clay_percent', 'fines_content')
        }),
        ('塑性指數', {
            'fields': ('plastic_index',)
        }),
        ('時間戳記', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def thickness(self, obj):
        return f"{obj.thickness:.2f}m"
    thickness.short_description = '土層厚度'


@admin.register(AnalysisResult)
class AnalysisResultAdmin(admin.ModelAdmin):
    list_display = ('soil_layer', 'analysis_depth', 'n1_60cs', 'fs_design', 'fs_mid', 'fs_max')
    list_filter = ('soil_layer__borehole__project',)
    search_fields = ('soil_layer__borehole__borehole_id',)
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('基本資訊', {
            'fields': ('soil_layer', 'soil_depth', 'mid_depth', 'analysis_depth')
        }),
        ('應力計算', {
            'fields': ('sigma_v', 'sigma_v_csr', 'sigma_v_crr')
        }),
        ('SPT參數', {
            'fields': ('n60', 'n1_60', 'n1_60cs')
        }),
        ('剪力波速', {
            'fields': ('vs',)
        }),
        ('液化抗力', {
            'fields': ('crr_7_5',)
        }),
        ('設計地震', {
            'fields': ('mw_design', 'a_value_design', 'sd_s_design', 'sm_s_design', 
                      'msf_design', 'rd_design', 'csr_design', 'crr_design', 'fs_design', 'lpi_design'),
            'classes': ('collapse',)
        }),
        ('中小地震', {
            'fields': ('mw_mid', 'a_value_mid', 'sd_s_mid', 'sm_s_mid',
                      'msf_mid', 'rd_mid', 'csr_mid', 'crr_mid', 'fs_mid', 'lpi_mid'),
            'classes': ('collapse',)
        }),
        ('最大地震', {
            'fields': ('mw_max', 'a_value_max', 'sd_s_max', 'sm_s_max',
                      'msf_max', 'rd_max', 'csr_max', 'crr_max', 'fs_max', 'lpi_max'),
            'classes': ('collapse',)
        }),
        ('時間戳記', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )