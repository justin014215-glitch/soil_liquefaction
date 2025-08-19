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
    
    # 結果查看
    path('projects/<uuid:pk>/results/', views.results, name='results'),
    path('projects/<uuid:pk>/export/', views.export_results, name='export'),
    
    # API 端點
    path('api/seismic-data/', views.api_seismic_data, name='api_seismic_data'),

    
    path('projects/', views.project_list, name='project_list'),
]
