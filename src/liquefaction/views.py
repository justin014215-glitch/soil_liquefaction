from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json
import os
from .models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult


def index(request):
    """首頁視圖"""
    context = {
        'title': '土壤液化分析系統',
        'description': '專業的土壤液化潛能分析工具，支援多種分析方法及標準',
    }
    
    if request.user.is_authenticated:
        # 如果用戶已登入，顯示最近的專案
        recent_projects = AnalysisProject.objects.filter(
            user=request.user
        ).order_by('-updated_at')[:5]
        context['recent_projects'] = recent_projects
        
        # 統計資料
        context['stats'] = {
            'total_projects': AnalysisProject.objects.filter(user=request.user).count(),
            'completed_projects': AnalysisProject.objects.filter(
                user=request.user, status='completed'
            ).count(),
            'processing_projects': AnalysisProject.objects.filter(
                user=request.user, status='processing'
            ).count(),
        }
    
    return render(request, 'liquefaction/index.html', context)


@login_required
def project_list(request):
    """專案列表視圖"""
    projects = AnalysisProject.objects.filter(user=request.user).order_by('-updated_at')
    
    # 搜索功能
    search_query = request.GET.get('search', '')
    if search_query:
        projects = projects.filter(
            Q(name__icontains=search_query) | 
            Q(description__icontains=search_query)
        )
    
    # 狀態篩選
    status_filter = request.GET.get('status', '')
    if status_filter:
        projects = projects.filter(status=status_filter)
    
    # 分頁
    paginator = Paginator(projects, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': AnalysisProject.STATUS_CHOICES,
    }
    
    return render(request, 'liquefaction/project_list.html', context)


@login_required
def project_create(request):
    """創建新專案"""
    if request.method == 'POST':
        try:
            # 處理表單數據
            name = request.POST.get('name')
            description = request.POST.get('description', '')
            analysis_method = request.POST.get('analysis_method', 'HBF')
            em_value = float(request.POST.get('em_value', 72))
            unit_weight_unit = request.POST.get('unit_weight_unit', 't/m3')
            use_fault_data = request.POST.get('use_fault_data') == 'on'
            
            # 創建專案
            project = AnalysisProject.objects.create(
                user=request.user,
                name=name,
                description=description,
                analysis_method=analysis_method,
                em_value=em_value,
                unit_weight_unit=unit_weight_unit,
                use_fault_data=use_fault_data,
            )
            
            # 處理檔案上傳
            if 'source_file' in request.FILES:
                project.source_file = request.FILES['source_file']
            
            if 'fault_shapefile' in request.FILES:
                project.fault_shapefile = request.FILES['fault_shapefile']
            
            project.save()
            
            messages.success(request, f'專案 "{name}" 創建成功！')
            return redirect('liquefaction:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'創建專案時發生錯誤：{str(e)}')
    
    context = {
        'analysis_methods': AnalysisProject._meta.get_field('analysis_method').choices,
        'unit_weight_units': AnalysisProject._meta.get_field('unit_weight_unit').choices,
    }
    
    return render(request, 'liquefaction/project_create.html', context)


@login_required
def project_detail(request, pk):
    """專案詳情視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 獲取鑽孔資料
    boreholes = BoreholeData.objects.filter(project=project).order_by('borehole_id')
    
    # 獲取分析結果統計
    total_layers = SoilLayer.objects.filter(borehole__project=project).count()
    analyzed_layers = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).count()
    
    context = {
        'project': project,
        'boreholes': boreholes,
        'total_layers': total_layers,
        'analyzed_layers': analyzed_layers,
        'analysis_progress': (analyzed_layers / total_layers * 100) if total_layers > 0 else 0,
    }
    
    return render(request, 'liquefaction/project_detail.html', context)


@login_required
def project_update(request, pk):
    """更新專案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            project.name = request.POST.get('name', project.name)
            project.description = request.POST.get('description', project.description)
            project.analysis_method = request.POST.get('analysis_method', project.analysis_method)
            project.em_value = float(request.POST.get('em_value', project.em_value))
            project.unit_weight_unit = request.POST.get('unit_weight_unit', project.unit_weight_unit)
            project.use_fault_data = request.POST.get('use_fault_data') == 'on'
            
            # 處理新檔案上傳
            if 'source_file' in request.FILES:
                project.source_file = request.FILES['source_file']
            
            if 'fault_shapefile' in request.FILES:
                project.fault_shapefile = request.FILES['fault_shapefile']
            
            project.save()
            
            messages.success(request, '專案更新成功！')
            return redirect('liquefaction:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'更新專案時發生錯誤：{str(e)}')
    
    context = {
        'project': project,
        'analysis_methods': AnalysisProject._meta.get_field('analysis_method').choices,
        'unit_weight_units': AnalysisProject._meta.get_field('unit_weight_unit').choices,
    }
    
    return render(request, 'liquefaction/project_update.html', context)


@login_required
def project_delete(request, pk):
    """刪除專案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        project_name = project.name
        project.delete()
        messages.success(request, f'專案 "{project_name}" 已成功刪除！')
        return redirect('liquefaction:project_list')
    
    return render(request, 'liquefaction/project_delete.html', {'project': project})


@login_required
def file_upload(request, pk):
    """檔案上傳處理"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            # 這裡將來會實作 CSV 檔案解析邏輯
            messages.success(request, '檔案上傳成功！')
            return redirect('liquefaction:project_detail', pk=project.pk)
        except Exception as e:
            messages.error(request, f'檔案上傳失敗：{str(e)}')
    
    return render(request, 'liquefaction/file_upload.html', {'project': project})


@login_required
def analyze(request, pk):
    """執行液化分析"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            # 這裡將來會實作液化分析邏輯
            project.status = 'processing'
            project.save()
            
            messages.success(request, '分析已開始執行！')
            return redirect('liquefaction:project_detail', pk=project.pk)
        except Exception as e:
            messages.error(request, f'分析執行失敗：{str(e)}')
    
    return render(request, 'liquefaction/analyze.html', {'project': project})


@login_required
def results(request, pk):
    """查看分析結果"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 獲取所有分析結果
    results = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).select_related('soil_layer', 'soil_layer__borehole').order_by(
        'soil_layer__borehole__borehole_id', 'soil_layer__top_depth'
    )
    
    context = {
        'project': project,
        'results': results,
    }
    
    return render(request, 'liquefaction/results.html', context)


@login_required
def export_results(request, pk):
    """匯出分析結果"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 這裡將來會實作結果匯出邏輯
    return JsonResponse({'message': '匯出功能開發中'})


def api_seismic_data(request):
    """API：獲取地震參數資料"""
    city = request.GET.get('city', '')
    district = request.GET.get('district', '')
    village = request.GET.get('village', '')
    
    # 這裡將來會實作地震參數查詢邏輯
    return JsonResponse({
        'city': city,
        'district': district,
        'village': village,
        'seismic_data': {},
        'message': 'API 開發中'
    })