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
                import_result = import_service.import_csv_data(request.FILES['source_file'])
                
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
            import_result = import_service.import_csv_data(csv_file)
            
            if import_result['success']:
                # 匯入成功
                summary = import_result['summary']
                messages.success(
                    request, 
                    f'CSV 檔案上傳成功！已匯入 {summary["imported_boreholes"]} 個鑽孔，{summary["imported_layers"]} 個土層。'
                )
                
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
    
    safety_filter = request.GET.get('safety', '')
    if safety_filter == 'danger':
        results = results.filter(fs_design__lt=1.0)
    elif safety_filter == 'warning':
        results = results.filter(fs_design__gte=1.0, fs_design__lt=1.3)
    elif safety_filter == 'safe':
        results = results.filter(fs_design__gte=1.3)
    
    print(f"🔍 最終結果數量: {results.count()}")
    
    context = {
        'project': project,
        'results': results,
        'available_methods': available_methods_display,
        'method_filter': method_filter,
    }
    
    return render(request, 'liquefaction/results.html', context)


@login_required
def export_results(request, pk):
    """匯出分析結果 - 支援多方法"""
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
        
        # 創建 HTTP 響應
        if method_filter:
            filename = f"{project.name}_{method_filter}_analysis_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        else:
            filename = f"{project.name}_all_methods_analysis_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # 添加 BOM 以確保 Excel 正確顯示中文
        response.write('\ufeff')
        
        writer = csv.writer(response)
        
        # 寫入標題行 - 包含分析方法欄位
        headers = [
            '鑽孔編號', '分析方法', '深度上限(m)', '深度下限(m)', '土壤分類', 'SPT-N', 'N1_60cs', 'Vs(m/s)',
            '設計地震_Mw', '設計地震_amax(g)', '設計地震_CSR', '設計地震_CRR', '設計地震_FS', '設計地震_LPI',
            '中小地震_Mw', '中小地震_amax(g)', '中小地震_CSR', '中小地震_CRR', '中小地震_FS', '中小地震_LPI',
            '最大地震_Mw', '最大地震_amax(g)', '最大地震_CSR', '最大地震_CRR', '最大地震_FS', '最大地震_LPI'
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
        
        # 寫入資料行
        for result in results:
            row = [
                result.soil_layer.borehole.borehole_id,
                result.analysis_method,  # 新增：分析方法
                result.soil_layer.top_depth,
                result.soil_layer.bottom_depth,
                result.soil_layer.uscs or '',
                result.soil_layer.spt_n or '',
                result.n1_60cs or '',
                result.vs or '',
                
                # 設計地震
                result.mw_design or '',
                result.a_value_design or '',
                result.csr_design or '',
                result.crr_design or '',
                result.fs_design or '',
                result.lpi_design or '',
                
                # 中小地震
                result.mw_mid or '',
                result.a_value_mid or '',
                result.csr_mid or '',
                result.crr_mid or '',
                result.fs_mid or '',
                result.lpi_mid or '',
                
                # 最大地震
                result.mw_max or '',
                result.a_value_max or '',
                result.csr_max or '',
                result.crr_max or '',
                result.fs_max or '',
                result.lpi_max or ''
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
    
    # 土壤類型分布
    soil_type_counts = {}
    for layer in soil_layers:
        if layer.uscs:
            soil_type_counts[layer.uscs] = soil_type_counts.get(layer.uscs, 0) + 1
    
    # 深度分布（每5米一組）
    depth_distribution = {}
    for layer in soil_layers:
        depth_group = int(layer.top_depth // 5) * 5
        key = f"{depth_group}-{depth_group + 5}m"
        depth_distribution[key] = depth_distribution.get(key, 0) + 1
    
    context = {
        'project': project,
        'borehole': borehole,
        'soil_layers': soil_layers,
        'analysis_results': analysis_results,
        'total_layers': total_layers,
        'max_depth': max_depth,
        'n_stats': n_stats,
        'soil_type_counts': soil_type_counts,
        'depth_distribution': depth_distribution,
    }
    
    return render(request, 'liquefaction/borehole_detail.html', context)

# 在 src/liquefaction/views.py 的最後添加以下函數

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