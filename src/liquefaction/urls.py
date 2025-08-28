from django.urls import path
from . import views

app_name = 'liquefaction'

urlpatterns = [
    # 首頁
    path('', views.index, name='index'),
    
    # 專案管理
    path('projects/', views.project_list, name='project_list'),
    path('projects/create/', views.project_create, name='project_create'),
    path('projects/<uuid:pk>/', views.project_detail, name='project_detail'),
    path('projects/<uuid:pk>/update/', views.project_update, name='project_update'),
    path('projects/<uuid:pk>/delete/', views.project_delete, name='project_delete'),
    
    # 檔案上傳與處理
    path('projects/<uuid:pk>/upload/', views.file_upload, name='file_upload'),
    path('projects/<uuid:pk>/analyze/', views.analyze, name='analyze'),
    
    # 新增：重新分析
    path('projects/<uuid:pk>/reanalyze/', views.reanalyze, name='reanalyze'),
     
    # 結果查看
    path('projects/<uuid:pk>/results/', views.results, name='results'),
    path('projects/<uuid:pk>/export/', views.export_results, name='export'),
    
    # API 端點
    path('api/seismic-data/', views.api_seismic_data, name='api_seismic_data'),    
    path('projects/', views.project_list, name='project_list'),
    
    # 新增：下載分析輸出資料夾
    path('projects/<uuid:pk>/download-outputs/', views.download_analysis_outputs, name='download_outputs'),
    path('projects/<uuid:pk>/outputs-info/', views.get_analysis_outputs_info, name='outputs_info'),
  
    # 鑽孔資料
    path('projects/<uuid:pk>/borehole-data/', views.borehole_data, name='borehole_data'),
    path('projects/<uuid:pk>/borehole/<str:borehole_id>/', views.borehole_detail, name='borehole_detail'),

    # 新增：單獨資料夾下載
    path('projects/<uuid:pk>/download-dir/<str:dir_name>/', views.download_single_directory, name='download_single_dir'),
  
    # 新增：下載鑽孔報表
    path('projects/<uuid:pk>/borehole/<str:borehole_id>/download-report/', 
    views.download_borehole_report, name='download_borehole_report'),
]