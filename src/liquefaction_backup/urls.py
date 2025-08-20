from django.urls import path
from . import views

app_name = 'liquefaction'

urlpatterns = [
    # 主要頁面
    path('', views.index, name='index'),
    
    # 專案管理
    path('projects/', views.project_list, name='project_list'),
    path('project/create/', views.project_create, name='project_create'),
    path('project/<int:pk>/', views.project_detail, name='project_detail'),
    path('project/<int:pk>/update/', views.project_update, name='project_update'),
    path('project/<int:pk>/delete/', views.project_delete, name='project_delete'),
    
    # 檔案操作
    path('project/<int:pk>/upload/', views.file_upload, name='file_upload'),
    path('project/<int:pk>/download/<str:filename>/', views.download_analysis_result, name='download_result'),
    
    # 分析相關
    path('project/<int:pk>/analyze/', views.analyze, name='analyze'),
    path('project/<int:pk>/status/', views.analysis_status, name='analysis_status'),
    path('project/<int:pk>/results/', views.results, name='results'),
    path('project/<int:pk>/export/', views.export_results, name='export_results'),
    
    # 分析表單（獨立使用）
    path('analysis/', views.analysis_form, name='analysis_form'),
    
    # 管理功能
    path('cleanup/', views.cleanup_old_results, name='cleanup_results'),
    
    # API 端點
    path('api/analyze/', views.api_liquefaction_analysis, name='api_analyze'),
    path('api/download/<str:filename>/', views.api_download_result, name='api_download'),
    path('api/seismic-data/', views.api_seismic_data, name='api_seismic_data'),
    
    # 舊版相容性
    path('project/<int:pk>/legacy-results/', views.legacy_results, name='legacy_results'),
    path('project/<int:pk>/legacy-export/', views.legacy_export_results, name='legacy_export'),
]