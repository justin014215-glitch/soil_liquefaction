from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json
import os
from .models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult, Project
from django.http import FileResponse, Http404
from django.contrib.auth.decorators import login_required
from datetime import datetime
import glob
from django.conf import settings

def project_list(request):
    projects = Project.objects.all().order_by('-created_at')
    return render(request, 'liquefaction/project_list.html', {'projects': projects})

def index(request):
    """首頁視圖"""
    context = {
        'title': '土壤液化分析系統',
        'description': '土壤液化潛能分析工具',
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
            em_value = float(request.POST.get('em_value', 72))
            unit_weight_unit = request.POST.get('unit_weight_unit', 't/m3')
            use_fault_data = request.POST.get('use_fault_data') == 'on'
            
            # 創建專案
            project = AnalysisProject.objects.create(
                user=request.user,
                name=name,
                analysis_method='HBF',
                description=description,
                em_value=em_value,
                unit_weight_unit=unit_weight_unit,
                use_fault_data=use_fault_data,
            )
            
            # 處理檔案上傳並立即處理
            csv_processed = False

            if 'source_file' in request.FILES:
                project.source_file = request.FILES['source_file']
                project.save()  # 先保存檔案路徑
                
                # 立即處理 CSV 檔案
                from .services.data_import_service import DataImportService
                import_service = DataImportService(project)

                import_result = import_service.import_csv_data(request.FILES['source_file'],
                                                               unit_weight_unit=unit_weight_unit )
                
                if import_result['success']:
                    summary = import_result['summary']
                    messages.success(
                        request, 
                        f'專案 "{name}" 創建成功！已匯入 {summary["imported_boreholes"]} 個鑽孔，{summary["imported_layers"]} 個土層。'
                    )
                    
                    # 顯示警告訊息
                    for warning in import_result.get('warnings', []):
                        messages.warning(request, f'警告：{warning}')
                        
                    csv_processed = True
                else:
                    messages.error(request, f'CSV 檔案處理失敗：{import_result["error"]}')
                    project.status = 'error'
                    project.error_message = import_result["error"]

            if 'fault_shapefile' in request.FILES:
                project.fault_shapefile = request.FILES['fault_shapefile']

            project.save()

            if not csv_processed:
                messages.success(request, f'專案 "{name}" 創建成功！請上傳 CSV 檔案以開始分析。')
            
            messages.success(request, f'專案 "{name}" 創建成功！')
            return redirect('liquefaction:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'創建專案時發生錯誤：{str(e)}')
    
    context = {
        'unit_weight_units': AnalysisProject._meta.get_field('unit_weight_unit').choices,
    }
    
    return render(request, 'liquefaction/project_create.html', context)


@login_required
def project_detail(request, pk):
    """專案詳情視圖 - 新增快速分析功能"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 處理快速分析請求
    if request.method == 'POST':
        selected_methods = request.POST.getlist('analysis_methods')
        if not selected_methods:
            messages.error(request, '請至少選擇一種分析方法')
            return redirect('liquefaction:project_detail', pk=project.pk)
        
        # 檢查是否有資料
        boreholes_count = BoreholeData.objects.filter(project=project).count()
        if boreholes_count == 0:
            messages.error(request, '專案中沒有鑽孔資料，請先上傳 CSV 檔案')
            return redirect('liquefaction:project_detail', pk=project.pk)
        
        # 執行分析
        try:
            from .services.analysis_engine import LiquefactionAnalysisEngine
            
            total_success = 0
            total_errors = []
            
            for method in selected_methods:
                # 暫時更新專案的分析方法
                original_method = project.analysis_method
                project.analysis_method = method
                project.save()
                
                # 執行分析
                analysis_engine = LiquefactionAnalysisEngine(project)
                analysis_result = analysis_engine.run_analysis()
                
                if analysis_result['success']:
                    total_success += 1
                    messages.success(request, f'{method} 分析完成！')
                else:
                    total_errors.append(f'{method}: {analysis_result["error"]}')
                    messages.error(request, f'{method} 分析失敗：{analysis_result["error"]}')
                
                # 恢復原始分析方法
                project.analysis_method = original_method
                project.save()
            
            if total_success > 0:
                project.status = 'completed'
                project.save()
                messages.success(request, f'分析完成！成功完成 {total_success} 種方法的分析')
                return redirect('liquefaction:results', pk=project.pk)
            else:
                project.status = 'error'
                project.error_message = '; '.join(total_errors)
                project.save()
                
        except Exception as e:
            messages.error(request, f'分析過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
    
    # 獲取鑽孔資料
    boreholes = BoreholeData.objects.filter(project=project).prefetch_related('soil_layers').order_by('borehole_id')
    
    # 為每個鑽孔計算最大深度
    boreholes_with_stats = []
    for borehole in boreholes:
        soil_layers = borehole.soil_layers.all()
        max_depth = max([layer.bottom_depth for layer in soil_layers]) if soil_layers else 0
        
        borehole_data = {
            'borehole': borehole,
            'layers_count': soil_layers.count(),
            'max_depth': max_depth
        }
        boreholes_with_stats.append(borehole_data)
    
    # 獲取分析結果統計
    total_layers = SoilLayer.objects.filter(borehole__project=project).count()
    
    # 統計各方法的分析結果
    analysis_methods_stats = {}
    for method_code, method_name in AnalysisProject._meta.get_field('analysis_method').choices:
        analyzed_count = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project,
            analysis_method=method_code
        ).count()
        analysis_methods_stats[method_code] = {
            'name': method_name,
            'count': analyzed_count,
            'progress': (analyzed_count / total_layers * 100) if total_layers > 0 else 0
        }
    
    context = {
        'project': project,
        'boreholes': boreholes,
        'boreholes_with_stats': boreholes_with_stats,
        'total_layers': total_layers,
        'analysis_methods_stats': analysis_methods_stats,
        'available_methods': AnalysisProject._meta.get_field('analysis_method').choices,
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
            if 'csv_file' not in request.FILES:
                messages.error(request, '請選擇要上傳的 CSV 檔案')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            csv_file = request.FILES['csv_file']
            
            # 檢查檔案類型
            if not csv_file.name.endswith('.csv'):
                messages.error(request, '請上傳 CSV 格式的檔案')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查檔案大小 (限制 10MB)
            if csv_file.size > 10 * 1024 * 1024:
                messages.error(request, '檔案大小不能超過 10MB')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 使用 DataImportService 匯入資料
            from .services.data_import_service import DataImportService
            import_service = DataImportService(project)
            import_result = import_service.import_csv_data(
                csv_file,
                unit_weight_unit=project.unit_weight_unit)
            
            if import_result['success']:
                # 匯入成功
                summary = import_result['summary']
                messages.success(
                    request, 
                    f'CSV 檔案上傳成功！已匯入 {summary["imported_boreholes"]} 個鑽孔，{summary["imported_layers"]} 個土層。'
                )
                # 新增：顯示單位檢測結果
                if 'detected_unit' in import_result and import_result['detected_unit']:
                    if import_result.get('unit_consistency', True):
                        messages.info(request, f'✓ 統體單位重單位檢測：{import_result["detected_unit"]}（與專案設定一致）')
                    else:
                        messages.warning(request, f'⚠️ 統體單位重單位檢測：{import_result["detected_unit"]}（與專案設定 {project.unit_weight_unit} 不一致）')
                
                # 顯示警告訊息
                for warning in import_result.get('warnings', []):
                    messages.warning(request, f'警告：{warning}')
                # 顯示警告訊息（如果有）
                for warning in import_result.get('warnings', []):
                    messages.warning(request, f'警告：{warning}')
                
                # 顯示錯誤訊息（如果有）
                for error in import_result.get('errors', []):
                    messages.error(request, f'錯誤：{error}')
                
                # 更新專案狀態
                project.status = 'pending'  # 等待分析
                project.error_message = ''
                project.save()
                
            else:
                # 匯入失敗
                messages.error(request, f'CSV 檔案處理失敗：{import_result["error"]}')
                # 如果是缺少欄位的問題，提供詳細資訊
                if 'missing_fields' in import_result:
                    messages.info(request, f'可用的欄位：{", ".join(import_result["available_columns"])}')
                    messages.info(request, '請確保 CSV 檔案包含所有必要欄位，或使用相應的中文欄位名稱')

                # 顯示詳細錯誤訊息
                for error in import_result.get('errors', []):
                    messages.error(request, f'詳細錯誤：{error}')
                
                # 更新專案狀態
                project.status = 'error'
                project.error_message = import_result["error"]
                project.save()
                
        except Exception as e:
            messages.error(request, f'檔案上傳過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
    
    return redirect('liquefaction:project_detail', pk=project.pk)

# views.py 修復專案狀態卡住的問題

@login_required
def analyze(request, pk):
    """執行液化分析 - 支援多方法分析"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            # 獲取選擇的分析方法
            selected_methods = request.POST.getlist('analysis_methods')
            if not selected_methods:
                messages.error(request, '請至少選擇一種分析方法')
                return redirect('liquefaction:analyze', pk=project.pk)
            
            print(f"=== 開始分析專案 {project.name}，方法：{selected_methods} ===")
            
            # 檢查專案狀態
            if project.status == 'processing':
                from django.utils import timezone
                import datetime
                
                time_diff = timezone.now() - project.updated_at
                if time_diff > datetime.timedelta(minutes=10):
                    print(f"⚠️ 專案處理超時 ({time_diff})，重置狀態")
                    project.status = 'pending'
                    project.error_message = ''
                    project.save()
                    messages.warning(request, '檢測到之前的分析可能中斷，已重置狀態。')
                else:
                    print(f"⚠️ 專案正在處理中，等待時間: {time_diff}")
                    messages.warning(request, f'專案正在分析中，已執行 {time_diff}，請稍候...')
                    return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查是否有鑽孔資料
            boreholes_count = BoreholeData.objects.filter(project=project).count()
            if boreholes_count == 0:
                messages.error(request, '專案中沒有鑽孔資料，請先上傳 CSV 檔案')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查是否有土層資料
            layers_count = SoilLayer.objects.filter(borehole__project=project).count()
            if layers_count == 0:
                messages.error(request, '專案中沒有土層資料')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            print("正在載入分析引擎...")
            from .services.analysis_engine import LiquefactionAnalysisEngine
            
            total_success = 0
            total_errors = []
            original_method = project.analysis_method
            
            for method in selected_methods:
                print(f"開始執行 {method} 分析...")
                
                # 只建立一次分析引擎，並傳入指定的方法
                analysis_engine = LiquefactionAnalysisEngine(project, analysis_method=method)
                analysis_result = analysis_engine.run_analysis()
                
                print(f"{method} 分析結果: {analysis_result}")
                
                if analysis_result['success']:
                    total_success += 1
                    messages.success(
                        request, 
                        f'{method} 分析完成！共分析 {analysis_result["analyzed_layers"]} 個土層。'
                    )
                    
                    # 顯示警告訊息
                    for warning in analysis_result.get('warnings', []):
                        messages.warning(request, f'{method} 警告：{warning}')
                else:
                    total_errors.append(f'{method}: {analysis_result["error"]}')
                    messages.error(request, f'{method} 分析失敗：{analysis_result["error"]}')
                    
                    # 顯示詳細錯誤
                    for error in analysis_result.get('errors', []):
                        messages.error(request, f'{method} 錯誤：{error}')
                
                print(f"{method} 分析結果: {analysis_result}")
                
                if analysis_result['success']:
                    total_success += 1
                    messages.success(
                        request, 
                        f'{method} 分析完成！共分析 {analysis_result["analyzed_layers"]} 個土層。'
                    )
                    
                    # 顯示警告訊息
                    for warning in analysis_result.get('warnings', []):
                        messages.warning(request, f'{method} 警告：{warning}')
                else:
                    total_errors.append(f'{method}: {analysis_result["error"]}')
                    messages.error(request, f'{method} 分析失敗：{analysis_result["error"]}')
                    
                    # 顯示詳細錯誤
                    for error in analysis_result.get('errors', []):
                        messages.error(request, f'{method} 錯誤：{error}')
            
            # 恢復原始分析方法
            project.analysis_method = original_method
            
            # 更新專案狀態
            if total_success > 0:
                project.status = 'completed'
                project.error_message = ''
                project.save()
                messages.success(request, f'多方法分析完成！成功完成 {total_success}/{len(selected_methods)} 種方法的分析')
                return redirect('liquefaction:results', pk=project.pk)
            else:
                project.status = 'error'
                project.error_message = '; '.join(total_errors)
                project.save()
                return redirect('liquefaction:project_detail', pk=project.pk)
                
        except Exception as e:
            messages.error(request, f'分析過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
            
            return redirect('liquefaction:project_detail', pk=project.pk)
    
    # GET 請求，顯示分析確認頁面
    context = {
        'project': project,
        'boreholes_count': BoreholeData.objects.filter(project=project).count(),
        'layers_count': SoilLayer.objects.filter(borehole__project=project).count(),
        'available_methods': AnalysisProject._meta.get_field('analysis_method').choices,
    }
    
    return render(request, 'liquefaction/analyze.html', context)

# 添加一個新的 view 用於重置專案狀態
@login_required
def reset_project_status(request, pk):
    """重置專案狀態"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        old_status = project.status
        project.status = 'pending'
        project.error_message = ''
        project.save()
        
        messages.success(request, f'專案狀態已從 "{project.get_status_display()}" 重置為 "等待分析"')
        print(f"專案 {project.name} 狀態已從 {old_status} 重置為 pending")
        
    return redirect('liquefaction:project_detail', pk=project.pk)


@login_required
def results(request, pk):
    """查看分析結果 - 新增方法篩選"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查是否有分析結果
    total_results = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).count()
    
    if total_results == 0:
        messages.warning(request, '專案尚未有分析結果')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    # 使用更可靠的方法獲取可用分析方法
    available_methods_raw = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).values_list('analysis_method', flat=True).distinct().order_by('analysis_method')

    # 轉換為列表並過濾空值
    available_methods_list = [method for method in available_methods_raw if method]

    # 如果上面的方法失敗，手動檢查每個方法
    if not available_methods_list:
        all_methods = ['HBF', 'NCEER', 'AIJ', 'JRA']
        available_methods_list = []
        for method in all_methods:
            if AnalysisResult.objects.filter(
                soil_layer__borehole__project=project,
                analysis_method=method
            ).exists():
                available_methods_list.append(method)
    
    # 獲取方法名稱對應
    method_choices = dict(AnalysisProject._meta.get_field('analysis_method').choices)
    available_methods_display = [
        (method, method_choices.get(method, method)) 
        for method in available_methods_raw
    ]
    
    print(f"🔍 顯示用的方法對應: {available_methods_display}")
    
    # 獲取所有分析結果
    results = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).select_related('soil_layer', 'soil_layer__borehole').order_by(
        'soil_layer__borehole__borehole_id', 'soil_layer__top_depth', 'analysis_method'
    )
    
    # 應用篩選條件
    borehole_filter = request.GET.get('borehole', '')
    if borehole_filter:
        results = results.filter(soil_layer__borehole__borehole_id=borehole_filter)
    
    # 新增：分析方法篩選
    method_filter = request.GET.get('method', '')
    if method_filter:
        results = results.filter(analysis_method=method_filter)
        print(f"🔍 篩選方法: {method_filter}, 結果數量: {results.count()}")
    
    lpi_filter = request.GET.get('lpi', '')
    if lpi_filter == 'low':
        results = results.filter(lpi_design__lt=5.0)
    elif lpi_filter == 'medium':
        results = results.filter(lpi_design__gte=5.0, lpi_design__lte=15.0)
    elif lpi_filter == 'high':
        results = results.filter(lpi_design__gt=15.0)
    
    print(f"🔍 最終結果數量: {results.count()}")
    
    context = {
        'project': project,
        'results': results,
        'available_methods': available_methods_display,
        'method_filter': method_filter,
        'lpi_filter': lpi_filter,  
    }
    
    return render(request, 'liquefaction/results.html', context)

from django.db.models.fields.related import ForeignKey, OneToOneField, ManyToOneRel

@login_required
def export_results(request, pk):
    """匯出分析結果 - 支援多方法 - 包含所有計算參數"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查是否有分析結果
    total_results = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).count()
    
    if total_results == 0:
        messages.error(request, '專案尚未有分析結果，無法匯出')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    try:
        import csv
        from django.http import HttpResponse
        from datetime import datetime
        
        # 獲取選擇的方法（如果有）
        method_filter = request.GET.get('method', '')
        export_type = request.GET.get('type', 'csv')
        
        # 創建 HTTP 響應
        if method_filter:
            filename = f"{project.name}_{method_filter}_detailed_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        else:
            filename = f"{project.name}_all_methods_detailed_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # 添加 BOM 以確保 Excel 正確顯示中文
        response.write('\ufeff')
        
        writer = csv.writer(response)
        
        # ===== 修改：包含所有計算參數的完整標題行 =====
        headers = [
            # 基本資訊
            '鑽孔編號', '分析方法', '深度上限(m)', '深度下限(m)', '土層厚度(m)',
            '土壤分類(USCS)', 'SPT-N', '塑性指數(%)', '細料含量(%)', '取樣編號',
            
            # 座標和基本參數
            'TWD97_X', 'TWD97_Y', '地表高程(m)', '地下水位深度(m)',
            
            # 地震參數
            '城市', '基準Mw', 'SDS', 'SMS', '資料來源', '鄰近斷層',
            
            # 中間計算參數
            '土層深度(m)', '土層中點深度(m)', '分析點深度(m)',
            '總垂直應力σv(t/m²)', '有效垂直應力σ\'v_CSR(t/m²)', '有效垂直應力σ\'v_CRR(t/m²)',
            'N60', 'N1_60', 'N1_60cs', '剪力波速Vs(m/s)', 'CRR_7.5',
            
            # 設計地震詳細參數
            '設計地震_Mw', '設計地震_A_value(g)', '設計地震_SD_S', '設計地震_SM_S',
            '設計地震_MSF', '設計地震_rd', '設計地震_CSR', '設計地震_CRR', 
            '設計地震_FS', '設計地震_LPI',
            
            # 中小地震詳細參數
            '中小地震_Mw', '中小地震_A_value(g)', '中小地震_SD_S', '中小地震_SM_S',
            '中小地震_MSF', '中小地震_rd', '中小地震_CSR', '中小地震_CRR', 
            '中小地震_FS', '中小地震_LPI',
            
            # 最大地震詳細參數
            '最大地震_Mw', '最大地震_A_value(g)', '最大地震_SD_S', '最大地震_SM_S',
            '最大地震_MSF', '最大地震_rd', '最大地震_CSR', '最大地震_CRR', 
            '最大地震_FS', '最大地震_LPI',
            
            # 額外資訊
            '單位重(t/m³)', '含水量(%)', '液性限度(%)', '分析時間'
        ]
        writer.writerow(headers)
        
        # 獲取分析結果
        results = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project
        ).select_related('soil_layer', 'soil_layer__borehole').order_by(
            'soil_layer__borehole__borehole_id', 'soil_layer__top_depth', 'analysis_method'
        )
        
        # 應用方法篩選
        if method_filter:
            results = results.filter(analysis_method=method_filter)
        
        # ===== 修改：寫入包含所有參數的詳細資料行 =====
        for result in results:
            soil_layer = result.soil_layer
            borehole = soil_layer.borehole
            
            # 安全取值函數
            def safe_value(val):
                if val is None:
                    return ''
                elif isinstance(val, float):
                    return f"{val:.6f}" if abs(val) < 1000 else f"{val:.2f}"
                else:
                    return str(val)
            
            row = [
                # 基本資訊
                borehole.borehole_id,
                result.analysis_method,
                safe_value(soil_layer.top_depth),
                safe_value(soil_layer.bottom_depth),
                safe_value(soil_layer.thickness) if hasattr(soil_layer, 'thickness') else safe_value(soil_layer.bottom_depth - soil_layer.top_depth),
                soil_layer.uscs or '',
                safe_value(soil_layer.spt_n),
                safe_value(soil_layer.plastic_index),
                safe_value(soil_layer.fines_content),
                soil_layer.sample_id or '',
                
                # 座標和基本參數
                safe_value(borehole.twd97_x),
                safe_value(borehole.twd97_y),
                safe_value(borehole.surface_elevation),
                safe_value(borehole.water_depth),
                
                # 地震參數
                borehole.city or '',
                safe_value(borehole.base_mw),
                safe_value(borehole.sds),
                safe_value(borehole.sms),
                borehole.data_source or '',
                borehole.nearby_fault or '',
                
                # 中間計算參數
                safe_value(result.soil_depth),
                safe_value(result.mid_depth),
                safe_value(result.analysis_depth),
                safe_value(result.sigma_v),
                safe_value(result.sigma_v_csr),
                safe_value(result.sigma_v_crr),
                safe_value(result.n60),
                safe_value(result.n1_60),
                safe_value(result.n1_60cs),
                safe_value(result.vs),
                safe_value(result.crr_7_5),
                
                # 設計地震詳細參數
                safe_value(result.mw_design),
                safe_value(result.a_value_design),
                safe_value(result.sd_s_design),
                safe_value(result.sm_s_design),
                safe_value(result.msf_design),
                safe_value(result.rd_design),
                safe_value(result.csr_design),
                safe_value(result.crr_design),
                safe_value(result.fs_design),
                safe_value(result.lpi_design),
                
                # 中小地震詳細參數
                safe_value(result.mw_mid),
                safe_value(result.a_value_mid),
                safe_value(result.sd_s_mid),
                safe_value(result.sm_s_mid),
                safe_value(result.msf_mid),
                safe_value(result.rd_mid),
                safe_value(result.csr_mid),
                safe_value(result.crr_mid),
                safe_value(result.fs_mid),
                safe_value(result.lpi_mid),
                
                # 最大地震詳細參數
                safe_value(result.mw_max),
                safe_value(result.a_value_max),
                safe_value(result.sd_s_max),
                safe_value(result.sm_s_max),
                safe_value(result.msf_max),
                safe_value(result.rd_max),
                safe_value(result.csr_max),
                safe_value(result.crr_max),
                safe_value(result.fs_max),
                safe_value(result.lpi_max),
                
                # 額外資訊
                safe_value(soil_layer.unit_weight),
                safe_value(soil_layer.water_content),
                safe_value(soil_layer.liquid_limit),
                result.created_at.strftime('%Y-%m-%d %H:%M:%S') if result.created_at else ''
            ]
            writer.writerow(row)
        
        return response
        
    except Exception as e:
        messages.error(request, f'匯出結果時發生錯誤：{str(e)}')
        return redirect('liquefaction:results', pk=project.pk)
    
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


@login_required
def reanalyze(request, pk):
    """重新執行液化分析 - 支援多方法"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            # 取得選擇的分析方法
            selected_methods = request.POST.getlist('analysis_methods')
            if not selected_methods:
                messages.error(request, '請至少選擇一種分析方法')
                return redirect('liquefaction:reanalyze', pk=project.pk)
            
            print(f"=== 開始重新分析專案 {project.name}，方法：{selected_methods} ===")
            
            # 檢查專案狀態
            if project.status == 'processing':
                messages.warning(request, '專案正在分析中，請稍候...')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查是否有鑽孔資料
            boreholes_count = BoreholeData.objects.filter(project=project).count()
            if boreholes_count == 0:
                messages.error(request, '專案中沒有鑽孔資料，無法進行分析')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查是否有土層資料
            layers_count = SoilLayer.objects.filter(borehole__project=project).count()
            if layers_count == 0:
                messages.error(request, '專案中沒有土層資料，無法進行分析')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 清除選中方法的現有分析結果
            for method in selected_methods:
                deleted_count = AnalysisResult.objects.filter(
                    soil_layer__borehole__project=project,
                    analysis_method=method
                ).count()
                
                AnalysisResult.objects.filter(
                    soil_layer__borehole__project=project,
                    analysis_method=method
                ).delete()
                
                print(f"已清除 {method} 方法的 {deleted_count} 個現有分析結果")
            
            # 重設錯誤訊息
            project.error_message = ''
            project.save()
            
            print("正在載入分析引擎...")
            from .services.analysis_engine import LiquefactionAnalysisEngine
            
            total_success = 0
            total_errors = []
            
            for method in selected_methods:
                print(f"開始重新執行 {method} 分析...")
                
                # 建立專門針對該方法的分析引擎實例
                analysis_engine = LiquefactionAnalysisEngine(project, analysis_method=method)
                analysis_result = analysis_engine.run_analysis()
                
                print(f"{method} 重新分析結果: {analysis_result}")
                
                if analysis_result['success']:
                    total_success += 1
                    messages.success(
                        request, 
                        f'{method} 重新分析完成！共分析 {analysis_result["analyzed_layers"]} 個土層。'
                    )
                    
                    # 顯示警告訊息
                    for warning in analysis_result.get('warnings', []):
                        messages.warning(request, f'{method} 警告：{warning}')
                else:
                    total_errors.append(f'{method}: {analysis_result["error"]}')
                    messages.error(request, f'{method} 重新分析失敗：{analysis_result["error"]}')
                    
                    # 顯示詳細錯誤
                    for error in analysis_result.get('errors', []):
                        messages.error(request, f'{method} 錯誤：{error}')
            
            # 更新專案狀態
            if total_success > 0:
                project.status = 'completed'
                project.error_message = ''
                project.save()
                messages.success(request, f'重新分析完成！成功完成 {total_success}/{len(selected_methods)} 種方法的分析')
                return redirect('liquefaction:results', pk=project.pk)
            else:
                project.status = 'error'
                project.error_message = '; '.join(total_errors)
                project.save()
                return redirect('liquefaction:project_detail', pk=project.pk)
                
        except Exception as e:
            messages.error(request, f'重新分析過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
            
            return redirect('liquefaction:project_detail', pk=project.pk)
    
    # GET 請求，顯示重新分析確認頁面
    # 取得現有的分析結果統計
    existing_results_by_method = {}
    for method_code, method_name in AnalysisProject._meta.get_field('analysis_method').choices:
        count = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project,
            analysis_method=method_code
        ).count()
        if count > 0:
            existing_results_by_method[method_code] = {
                'name': method_name,
                'count': count
            }
    
    context = {
        'project': project,
        'boreholes_count': BoreholeData.objects.filter(project=project).count(),
        'layers_count': SoilLayer.objects.filter(borehole__project=project).count(),
        'existing_results_by_method': existing_results_by_method,
        'available_methods': AnalysisProject._meta.get_field('analysis_method').choices,
    }
    
    return render(request, 'liquefaction/reanalyze.html', context)

@login_required
def download_analysis_file(request, pk, filename):
    """下載分析結果檔案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    file_path = os.path.join(project.get_output_directory(), filename)
    
    if not os.path.exists(file_path) or not filename.startswith(str(project.id)):
        raise Http404("檔案不存在")
    
    return FileResponse(
        open(file_path, 'rb'),
        as_attachment=True,
        filename=filename
    )

@login_required
def project_files(request, pk):
    """查看專案檔案列表"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    files = project.list_output_files()
    
    context = {
        'project': project,
        'files': files,
    }
    
    return render(request, 'liquefaction/project_files.html', context)


# 在 src/liquefaction/views.py 中新增以下視圖

@login_required
def borehole_data(request, pk):
    """鑽井數據總覽視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 取得所有鑽孔數據
    boreholes = BoreholeData.objects.filter(project=project).prefetch_related('soil_layers').order_by('borehole_id')
    
    # 搜尋和篩選
    search_query = request.GET.get('search', '')
    if search_query:
        boreholes = boreholes.filter(borehole_id__icontains=search_query)
    
    # 為每個鑽孔計算統計資訊
    borehole_stats = []
    for borehole in boreholes:
        soil_layers = borehole.soil_layers.all().order_by('top_depth')
        
        # 計算統計數據
        total_layers = soil_layers.count()
        max_depth = max([layer.bottom_depth for layer in soil_layers]) if soil_layers else 0
        min_n_value = min([layer.spt_n for layer in soil_layers if layer.spt_n is not None]) if soil_layers else None
        max_n_value = max([layer.spt_n for layer in soil_layers if layer.spt_n is not None]) if soil_layers else None
        avg_n_value = sum([layer.spt_n for layer in soil_layers if layer.spt_n is not None]) / total_layers if total_layers > 0 else None
        
        # 土壤類型分布
        soil_types = list(set([layer.uscs for layer in soil_layers if layer.uscs]))
        
        # 檢查是否有分析結果
        has_analysis = AnalysisResult.objects.filter(soil_layer__borehole=borehole).exists()
        analysis_methods = list(set(AnalysisResult.objects.filter(
            soil_layer__borehole=borehole
        ).values_list('analysis_method', flat=True)))
        
        borehole_stats.append({
            'borehole': borehole,
            'total_layers': total_layers,
            'max_depth': max_depth,
            'min_n_value': min_n_value,
            'max_n_value': max_n_value,
            'avg_n_value': avg_n_value,
            'soil_types': soil_types,
            'has_analysis': has_analysis,
            'analysis_methods': analysis_methods,
        })
    
    # 分頁
    from django.core.paginator import Paginator
    paginator = Paginator(borehole_stats, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'project': project,
        'page_obj': page_obj,
        'search_query': search_query,
        'total_boreholes': boreholes.count(),
    }
    
    return render(request, 'liquefaction/borehole_data.html', context)


@login_required
def borehole_detail(request, pk, borehole_id):
    """單個鑽孔詳細數據視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    borehole = get_object_or_404(BoreholeData, project=project, borehole_id=borehole_id)
    
    # 取得土層數據
    soil_layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')
    
    # 根據你的實際模型處理數據
    for layer in soil_layers:
        # FC值處理 - 優先使用 FC 欄位，其次是 fines_content
        if layer.FC is not None:
            layer.fc_value = layer.FC
        elif layer.fines_content is not None:
            layer.fc_value = layer.fines_content
        # 如果沒有細料欄位，用粉土+黏土計算
        elif (layer.silt_percent is not None and layer.clay_percent is not None):
            layer.fc_value = layer.silt_percent + layer.clay_percent
        else:
            layer.fc_value = None
        
        # 處理N值 - 優先使用 spt_n，其次是 n_value
        if layer.spt_n is not None:
            layer.n_val = layer.spt_n
        elif layer.n_value is not None:
            layer.n_val = layer.n_value
        else:
            layer.n_val = None
        
        # 統一土壤分類已經直接可用
        layer.soil_class = layer.uscs if layer.uscs else None
        
        # 單位重處理
        layer.unit_wt = layer.unit_weight if layer.unit_weight is not None else None
        
        # 厚度已經在模型的property中定義了，直接使用
        # layer.thickness 已經可以直接使用
        
        # Debug輸出（可選，用於排查問題）
        print(f"Layer {layer.id}: FC={layer.fc_value}, N={layer.n_val}, USCS={layer.soil_class}")
    
    # 取得分析結果（如果有）
    analysis_results = {}
    if hasattr(AnalysisProject, '_meta'):
        try:
            for method_code, method_name in AnalysisProject._meta.get_field('analysis_method').choices:
                results = AnalysisResult.objects.filter(
                    soil_layer__borehole=borehole,
                    analysis_method=method_code
                ).order_by('soil_layer__top_depth')
                
                if results.exists():
                    analysis_results[method_code] = {
                        'name': method_name,
                        'results': results
                    }
        except:
            # 如果沒有analysis_method欄位或AnalysisResult模型，跳過
            pass
    
    # 計算鑽孔統計
    total_layers = soil_layers.count()
    max_depth = 0
    if soil_layers:
        depth_values = []
        for layer in soil_layers:
            if hasattr(layer, 'bottom_depth') and layer.bottom_depth is not None:
                depth_values.append(layer.bottom_depth)
        max_depth = max(depth_values) if depth_values else 0
    
    # N值統計
    n_values = [layer.n_val for layer in soil_layers if layer.n_val is not None]
    n_stats = {
        'count': len(n_values),
        'min': min(n_values) if n_values else None,
        'max': max(n_values) if n_values else None,
        'avg': sum(n_values) / len(n_values) if n_values else None,
    }
    
    # FC值統計
    fc_values = [layer.fc_value for layer in soil_layers if layer.fc_value is not None]
    fc_stats = {
        'count': len(fc_values),
        'min': min(fc_values) if fc_values else None,
        'max': max(fc_values) if fc_values else None,
        'avg': sum(fc_values) / len(fc_values) if fc_values else None,
    }
    
    # 土壤類型分布
    soil_type_counts = {}
    for layer in soil_layers:
        if layer.soil_class:
            soil_type_counts[layer.soil_class] = soil_type_counts.get(layer.soil_class, 0) + 1
    
    # 深度分布（每5米一組）
    depth_distribution = {}
    for layer in soil_layers:
        if hasattr(layer, 'top_depth') and layer.top_depth is not None:
            depth_group = int(layer.top_depth // 5) * 5
            key = f"{depth_group}-{depth_group + 5}m"
            depth_distribution[key] = depth_distribution.get(key, 0) + 1
    
    # FC含量分布統計 (用於分析液化潛能)
    fc_distribution = {
        '低FC(<15%)': 0,
        '中FC(15-35%)': 0, 
        '高FC(>35%)': 0
    }
    
    for layer in soil_layers:
        if layer.fc_value is not None:
            if layer.fc_value < 15:
                fc_distribution['低FC(<15%)'] += 1
            elif layer.fc_value <= 35:
                fc_distribution['中FC(15-35%)'] += 1
            else:
                fc_distribution['高FC(>35%)'] += 1
    
    context = {
        'project': project,
        'borehole': borehole,
        'soil_layers': soil_layers,
        'analysis_results': analysis_results,
        'total_layers': total_layers,
        'max_depth': max_depth,
        'n_stats': n_stats,
        'fc_stats': fc_stats,  # FC 統計
        'soil_type_counts': soil_type_counts,
        'depth_distribution': depth_distribution,
        'fc_distribution': fc_distribution,  # FC 分布統計
    }
    
    return render(request, 'liquefaction/borehole_detail.html', context)
@login_required
def borehole_data(request, pk):
    """鑽井數據總覽視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 取得所有鑽孔數據
    boreholes = BoreholeData.objects.filter(project=project).prefetch_related('soil_layers').order_by('borehole_id')
    
    # 搜尋和篩選
    search_query = request.GET.get('search', '')
    if search_query:
        boreholes = boreholes.filter(borehole_id__icontains=search_query)
    
    # 為每個鑽孔計算統計資訊
    borehole_stats = []
    for borehole in boreholes:
        soil_layers = borehole.soil_layers.all().order_by('top_depth')
        
        # 計算統計數據
        total_layers = soil_layers.count()
        max_depth = max([layer.bottom_depth for layer in soil_layers]) if soil_layers else 0
        n_values = [layer.spt_n for layer in soil_layers if layer.spt_n is not None]
        min_n_value = min(n_values) if n_values else None
        max_n_value = max(n_values) if n_values else None
        avg_n_value = sum(n_values) / len(n_values) if n_values else None
        
        # 土壤類型分布
        soil_types = list(set([layer.uscs for layer in soil_layers if layer.uscs]))
        
        # 檢查是否有分析結果
        has_analysis = AnalysisResult.objects.filter(soil_layer__borehole=borehole).exists()
        analysis_methods = list(set(AnalysisResult.objects.filter(
            soil_layer__borehole=borehole
        ).values_list('analysis_method', flat=True)))
        
        borehole_stats.append({
            'borehole': borehole,
            'total_layers': total_layers,
            'max_depth': max_depth,
            'min_n_value': min_n_value,
            'max_n_value': max_n_value,
            'avg_n_value': avg_n_value,
            'soil_types': soil_types,
            'has_analysis': has_analysis,
            'analysis_methods': analysis_methods,
        })
    
    # 分頁
    from django.core.paginator import Paginator
    paginator = Paginator(borehole_stats, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'project': project,
        'page_obj': page_obj,
        'search_query': search_query,
        'total_boreholes': boreholes.count(),
    }
    
    return render(request, 'liquefaction/borehole_data.html', context)


@login_required
def borehole_detail(request, pk, borehole_id):
    """單個鑽孔詳細數據視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    borehole = get_object_or_404(BoreholeData, project=project, borehole_id=borehole_id)
    
    # 取得土層數據
    soil_layers = SoilLayer.objects.filter(borehole=borehole).order_by('top_depth')
    
    # 取得分析結果（如果有）
    analysis_results = {}
    for method_code, method_name in AnalysisProject._meta.get_field('analysis_method').choices:
        results = AnalysisResult.objects.filter(
            soil_layer__borehole=borehole,
            analysis_method=method_code
        ).order_by('soil_layer__top_depth')
        
        if results.exists():
            analysis_results[method_code] = {
                'name': method_name,
                'results': results
            }
    
    # 計算鑽孔統計
    total_layers = soil_layers.count()
    max_depth = max([layer.bottom_depth for layer in soil_layers]) if soil_layers else 0
    
    # N值統計
    n_values = [layer.spt_n for layer in soil_layers if layer.spt_n is not None]
    n_stats = {
        'count': len(n_values),
        'min': min(n_values) if n_values else None,
        'max': max(n_values) if n_values else None,
        'avg': sum(n_values) / len(n_values) if n_values else None,
    }
    
    context = {
        'project': project,
        'borehole': borehole,
        'soil_layers': soil_layers,
        'analysis_results': analysis_results,
        'total_layers': total_layers,
        'max_depth': max_depth,
        'n_stats': n_stats,
    }
    
    return render(request, 'liquefaction/borehole_detail.html', context)

# 在 views.py 中加入以下函數

@login_required
def download_analysis_outputs(request, pk):
    """下載專案的分析輸出資料夾"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        import tempfile
        import zipfile
        import shutil
        import glob
        from datetime import datetime
        from django.http import FileResponse, Http404
        from django.conf import settings
        
        # 尋找專案的輸出目錄
        output_dirs = _find_project_output_directories(project)
        
        if not output_dirs:
            messages.error(request, '找不到分析輸出檔案')
            return redirect('liquefaction:results', pk=project.pk)
        
        # 創建臨時ZIP檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            temp_zip_path = temp_zip.name
        
        try:
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                total_files = 0
                
                for output_dir in output_dirs:
                    if os.path.exists(output_dir):
                        print(f"正在打包目錄：{output_dir}")
                        
                        # 取得目錄名稱作為ZIP內的根目錄
                        dir_name = os.path.basename(output_dir)
                        
                        # 遞歸添加目錄中的所有檔案
                        for root, dirs, files in os.walk(output_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # 計算在ZIP中的相對路徑
                                arcname = os.path.relpath(file_path, os.path.dirname(output_dir))
                                zipf.write(file_path, arcname)
                                total_files += 1
                                print(f"  添加檔案：{arcname}")
                
                if total_files == 0:
                    messages.warning(request, '分析輸出目錄中沒有檔案')
                    os.unlink(temp_zip_path)
                    return redirect('liquefaction:results', pk=project.pk)
                
                print(f"總共打包了 {total_files} 個檔案")
            
            # 生成下載檔名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            download_filename = f"{project.name}_分析輸出_{timestamp}.zip"
            
            # 返回檔案響應
            response = FileResponse(
                open(temp_zip_path, 'rb'),
                as_attachment=True,
                filename=download_filename
            )
            response['Content-Type'] = 'application/zip'
            
            # 註冊清理函數（當響應完成後刪除臨時檔案）
            def cleanup_temp_file():
                try:
                    os.unlink(temp_zip_path)
                    print(f"已清理臨時檔案：{temp_zip_path}")
                except:
                    pass
            
            # 這裡我們不能直接清理，因為檔案還在使用中
            # 可以考慮使用後台任務來清理，或者依賴系統的臨時檔案清理
            
            return response
            
        except Exception as e:
            # 清理臨時檔案
            if os.path.exists(temp_zip_path):
                os.unlink(temp_zip_path)
            raise e
            
    except Exception as e:
        messages.error(request, f'下載分析輸出時發生錯誤：{str(e)}')
        return redirect('liquefaction:results', pk=project.pk)



def _find_project_output_directories(project):
    """直接搜尋專案相關檔案 - 簡化版本"""
    import glob
    from django.conf import settings
    
    output_dirs = []
    found_files = []
    
    try:
        analysis_output_root = getattr(settings, 'ANALYSIS_OUTPUT_ROOT', 
                                      os.path.join(settings.MEDIA_ROOT, 'analysis_outputs'))
        
        print(f"🔍 直接搜尋檔案，根路徑：{analysis_output_root}")
        
        if not os.path.exists(analysis_output_root):
            print(f"❌ 分析輸出根目錄不存在：{analysis_output_root}")
            return []
        
        # 取得專案ID的前8位字符用於匹配
        project_id_short = str(project.id)[:8]
        
        print(f"🔍 搜尋專案ID開頭：{project_id_short}")
        
        # 直接遞歸搜尋所有相關檔案
        search_patterns = [
            f"**/*{project_id_short}*",  # 包含專案ID的任何檔案
            f"**/*HBF*.csv",            # HBF相關CSV檔案  
            f"**/*LPI*.csv",            # LPI相關CSV檔案
            f"**/*{project.name}*",     # 包含專案名稱的檔案
        ]
        
        for pattern in search_patterns:
            search_path = os.path.join(analysis_output_root, pattern)
            matching_files = glob.glob(search_path, recursive=True)
            
            for file_path in matching_files:
                if os.path.isfile(file_path):
                    # 檢查檔案名是否真的與專案相關
                    file_name = os.path.basename(file_path)
                    
                    # 更寬鬆的匹配條件
                    is_relevant = any([
                        project_id_short in file_name,
                        project.name in file_name,
                        any(keyword in file_name.lower() for keyword in ['hbf', 'lpi', 'design', 'mideq', 'maxeq'])
                    ])
                    
                    if is_relevant:
                        found_files.append(file_path)
                        parent_dir = os.path.dirname(file_path)
                        
                        if parent_dir not in output_dirs:
                            output_dirs.append(parent_dir)
                            print(f"✅ 找到相關檔案：{file_name}")
                            print(f"   所在目錄：{parent_dir}")
        
        # 去重並排序
        output_dirs = list(set(output_dirs))
        
        print(f"🎯 總共找到 {len(found_files)} 個相關檔案")
        print(f"🎯 涉及 {len(output_dirs)} 個目錄")
        
        # 如果沒找到任何目錄但有檔案，至少返回根目錄
        if not output_dirs and found_files:
            output_dirs = [analysis_output_root]
        
        return output_dirs
        
    except Exception as e:
        print(f"❌ 搜尋檔案時發生錯誤：{e}")
        import traceback
        print(traceback.format_exc())
        return []

# 同時簡化 get_analysis_outputs_info 函數

@login_required 
def get_analysis_outputs_info(request, pk):
    """取得分析輸出資訊 - 直接檔案搜尋版本"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        print(f"🔍 開始直接搜尋專案檔案：{project.name} (ID前8位: {str(project.id)[:8]})")
        
        from django.conf import settings
        import glob
        
        analysis_output_root = getattr(settings, 'ANALYSIS_OUTPUT_ROOT', 
                                      os.path.join(settings.MEDIA_ROOT, 'analysis_outputs'))
        
        project_id_short = str(project.id)[:8]
        all_found_files = []
        
        # 直接搜尋相關檔案
        search_patterns = [
            f"**/*{project_id_short}*",
            f"**/*HBF*{datetime.now().strftime('%m%d')}*.csv",  # 今天產生的HBF檔案
            f"**/*LPI*{datetime.now().strftime('%m%d')}*.csv",  # 今天產生的LPI檔案
        ]
        
        for pattern in search_patterns:
            search_path = os.path.join(analysis_output_root, pattern)
            matching_files = glob.glob(search_path, recursive=True)
            
            for file_path in matching_files:
                if os.path.isfile(file_path):
                    file_name = os.path.basename(file_path)
                    
                    # 檢查是否為相關檔案
                    is_relevant = any([
                        project_id_short in file_name,
                        any(keyword in file_name.lower() for keyword in ['hbf', 'lpi', 'design', 'mideq', 'maxeq'])
                    ])
                    
                    if is_relevant and file_path not in all_found_files:
                        all_found_files.append(file_path)
                        print(f"📄 找到檔案：{file_name}")
        
        output_info = {
            'has_outputs': len(all_found_files) > 0,
            'directories': [],
            'total_files': len(all_found_files),
            'total_size': 0,
            'debug_info': {
                'project_id': str(project.id),
                'project_id_short': project_id_short,
                'project_name': project.name,
                'found_files_count': len(all_found_files),
                'analysis_output_root': analysis_output_root
            }
        }
        
        if all_found_files:
            # 按目錄分組檔案
            dirs_dict = {}
            
            for file_path in all_found_files:
                dir_path = os.path.dirname(file_path)
                dir_name = os.path.basename(dir_path) if dir_path != analysis_output_root else "根目錄"
                
                if dir_name not in dirs_dict:
                    dirs_dict[dir_name] = {
                        'path': dir_path,
                        'name': dir_name,
                        'files': [],
                        'file_count': 0,
                        'size': 0
                    }
                
                try:
                    file_size = os.path.getsize(file_path)
                    file_modified = os.path.getmtime(file_path)
                    
                    dirs_dict[dir_name]['files'].append({
                        'name': os.path.basename(file_path),
                        'path': os.path.relpath(file_path, dir_path),
                        'size': file_size,
                        'modified': datetime.fromtimestamp(file_modified).strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                    dirs_dict[dir_name]['size'] += file_size
                    dirs_dict[dir_name]['file_count'] += 1
                    output_info['total_size'] += file_size
                    
                except OSError as e:
                    print(f"⚠️ 無法讀取檔案 {file_path}: {e}")
                    continue
            
            output_info['directories'] = list(dirs_dict.values())
        
        print(f"🎯 API回應：找到 {output_info['total_files']} 個檔案")
        
        return JsonResponse(output_info)
        
    except Exception as e:
        print(f"❌ 取得輸出資訊時發生錯誤：{e}")
        import traceback
        print(traceback.format_exc())
        
        return JsonResponse({
            'error': str(e),
            'has_outputs': False,
            'debug_info': {
                'project_id': str(project.id),
                'project_name': project.name,
                'error_details': str(e)
            }
        })
# 同時修改 get_analysis_outputs_info 函數，增加更詳細的偵錯資訊

@login_required 
def get_analysis_outputs_info(request, pk):
    """取得分析輸出資訊的API端點 - 增強版本"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        print(f"🔍 開始查找專案輸出檔案：{project.name} (ID: {project.id})")
        
        output_dirs = _find_project_output_directories(project)
        
        output_info = {
            'has_outputs': len(output_dirs) > 0,
            'directories': [],
            'total_files': 0,
            'total_size': 0,
            'debug_info': {
                'project_id': str(project.id),
                'project_name': project.name,
                'searched_dirs': len(output_dirs),
                'analysis_output_root': getattr(settings, 'ANALYSIS_OUTPUT_ROOT', 'Not set')
            }
        }
        
        for output_dir in output_dirs:
            if os.path.exists(output_dir):
                print(f"📁 處理目錄：{output_dir}")
                
                dir_info = {
                    'path': output_dir,
                    'name': os.path.basename(output_dir),
                    'files': [],
                    'file_count': 0,
                    'size': 0
                }
                
                # 列出目錄中的檔案
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, output_dir)
                        
                        try:
                            file_size = os.path.getsize(file_path)
                            file_modified = os.path.getmtime(file_path)
                            
                            dir_info['files'].append({
                                'name': file,
                                'path': relative_path,
                                'size': file_size,
                                'modified': datetime.fromtimestamp(file_modified).strftime('%Y-%m-%d %H:%M:%S')
                            })
                            
                            dir_info['size'] += file_size
                            dir_info['file_count'] += 1
                            print(f"📄 找到檔案：{file} ({file_size} bytes)")
                            
                        except OSError as e:
                            print(f"⚠️ 無法讀取檔案 {file}: {e}")
                            continue
                
                if dir_info['file_count'] > 0:
                    output_info['directories'].append(dir_info)
                    output_info['total_files'] += dir_info['file_count']
                    output_info['total_size'] += dir_info['size']
                    print(f"✅ 目錄 {output_dir} 包含 {dir_info['file_count']} 個檔案")
                else:
                    print(f"⚠️ 目錄 {output_dir} 沒有檔案")
        
        print(f"🎯 總結果：{output_info['total_files']} 個檔案，總大小 {output_info['total_size']} bytes")
        
        return JsonResponse(output_info)
        
    except Exception as e:
        print(f"❌ 取得輸出資訊時發生錯誤：{e}")
        import traceback
        print(traceback.format_exc())
        
        return JsonResponse({
            'error': str(e),
            'has_outputs': False,
            'debug_info': {
                'project_id': str(project.id),
                'project_name': project.name,
                'error_details': traceback.format_exc()
            }
        })

# 也修改 download_analysis_outputs 函數，增加更好的錯誤處理

@login_required
def download_analysis_outputs(request, pk):
    """下載專案的分析輸出資料夾 - 改進版本"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        import tempfile
        import zipfile
        from datetime import datetime
        from django.http import FileResponse
        
        print(f"🔍 開始準備下載專案輸出：{project.name}")
        
        # 尋找專案的輸出目錄
        output_dirs = _find_project_output_directories(project)
        
        if not output_dirs:
            messages.error(request, '找不到分析輸出檔案。請檢查分析是否已完成，或檔案是否已被清理。')
            return redirect('liquefaction:results', pk=project.pk)
        
        # 創建臨時ZIP檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            temp_zip_path = temp_zip.name
        
        try:
            total_files = 0
            
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for output_dir in output_dirs:
                    if os.path.exists(output_dir):
                        print(f"📁 正在打包目錄：{output_dir}")
                        
                        # 取得目錄名稱作為ZIP內的根目錄
                        dir_name = os.path.basename(output_dir) if output_dir != os.path.dirname(output_dir) else "analysis_outputs"
                        
                        # 遞歸添加目錄中的所有檔案
                        for root, dirs, files in os.walk(output_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                
                                # 計算在ZIP中的相對路徑
                                if root == output_dir:
                                    # 檔案在根目錄
                                    arcname = os.path.join(dir_name, file)
                                else:
                                    # 檔案在子目錄
                                    rel_path = os.path.relpath(file_path, output_dir)
                                    arcname = os.path.join(dir_name, rel_path)
                                
                                zipf.write(file_path, arcname)
                                total_files += 1
                                print(f"📄 添加檔案：{arcname}")
            
            if total_files == 0:
                messages.warning(request, '分析輸出目錄中沒有檔案')
                os.unlink(temp_zip_path)
                return redirect('liquefaction:results', pk=project.pk)
            
            print(f"✅ 總共打包了 {total_files} 個檔案")
            
            # 生成下載檔名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            download_filename = f"{project.name}_分析輸出_{timestamp}.zip"
            
            # 返回檔案響應
            response = FileResponse(
                open(temp_zip_path, 'rb'),
                as_attachment=True,
                filename=download_filename
            )
            response['Content-Type'] = 'application/zip'
            
            print(f"🎯 開始下載：{download_filename}")
            return response
            
        except Exception as e:
            # 清理臨時檔案
            if os.path.exists(temp_zip_path):
                os.unlink(temp_zip_path)
            raise e
            
    except Exception as e:
        print(f"❌ 下載分析輸出時發生錯誤：{e}")
        import traceback
        print(traceback.format_exc())
        
        messages.error(request, f'下載分析輸出時發生錯誤：{str(e)}')
        return redirect('liquefaction:results', pk=project.pk)

def _format_file_size(size_bytes):
    """格式化檔案大小"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"
