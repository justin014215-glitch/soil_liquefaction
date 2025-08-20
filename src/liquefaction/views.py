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
        'analysis_methods': AnalysisProject._meta.get_field('analysis_method').choices,
        'unit_weight_units': AnalysisProject._meta.get_field('unit_weight_unit').choices,
    }
    
    return render(request, 'liquefaction/project_create.html', context)


@login_required
def project_detail(request, pk):
    """專案詳情視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 獲取鑽孔資料，並預先載入相關的土層資料
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
    analyzed_layers = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).count()
    
    # 計算分析進度
    analysis_progress = (analyzed_layers / total_layers * 100) if total_layers > 0 else 0
    
    context = {
        'project': project,
        'boreholes': boreholes,
        'boreholes_with_stats': boreholes_with_stats,
        'total_layers': total_layers,
        'analyzed_layers': analyzed_layers,
        'analysis_progress': round(analysis_progress, 1),
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
    """執行液化分析"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            print(f"=== 開始分析專案 {project.name} ===")
            print(f"分析方法: {project.analysis_method}")
            print(f"當前專案狀態: {project.status}")
            
            # 檢查專案狀態 - 智能處理 processing 狀態
            if project.status == 'processing':
                # 檢查更新時間，如果超過10分鐘沒更新，認為分析已中斷
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
            # 執行液化分析
            from .services.analysis_engine import LiquefactionAnalysisEngine
            
            print("創建分析引擎實例...")
            analysis_engine = LiquefactionAnalysisEngine(project)
            
            print("執行分析...")
            analysis_result = analysis_engine.run_analysis()
            
            print(f"分析結果: {analysis_result}")
            
            if analysis_result['success']:
                messages.success(
                    request, 
                    f'液化分析完成！共分析 {analysis_result["analyzed_layers"]} 個土層，'
                    f'使用 {analysis_result["analysis_method"]} 方法。'
                )
                
                # 顯示警告訊息
                for warning in analysis_result.get('warnings', []):
                    messages.warning(request, f'警告：{warning}')
                
                return redirect('liquefaction:results', pk=project.pk)
            else:
                messages.error(request, f'液化分析失敗：{analysis_result["error"]}')
                
                # 顯示詳細錯誤
                for error in analysis_result.get('errors', []):
                    messages.error(request, f'錯誤：{error}')
                
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
    """查看分析結果"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查專案狀態
    if project.status != 'completed':
        messages.warning(request, '專案尚未完成分析或分析失敗')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    # 獲取所有分析結果
    results = AnalysisResult.objects.filter(
        soil_layer__borehole__project=project
    ).select_related('soil_layer', 'soil_layer__borehole').order_by(
        'soil_layer__borehole__borehole_id', 'soil_layer__top_depth'
    )
    
    # 應用篩選條件
    borehole_filter = request.GET.get('borehole', '')
    if borehole_filter:
        results = results.filter(soil_layer__borehole__borehole_id=borehole_filter)
    
    safety_filter = request.GET.get('safety', '')
    if safety_filter == 'danger':
        results = results.filter(fs_design__lt=1.0)
    elif safety_filter == 'warning':
        results = results.filter(fs_design__gte=1.0, fs_design__lt=1.3)
    elif safety_filter == 'safe':
        results = results.filter(fs_design__gte=1.3)
    
    context = {
        'project': project,
        'results': results,
    }
    
    return render(request, 'liquefaction/results.html', context)


@login_required
def export_results(request, pk):
    """匯出分析結果"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查專案狀態
    if project.status != 'completed':
        messages.error(request, '專案尚未完成分析，無法匯出結果')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    try:
        import csv
        from django.http import HttpResponse
        from datetime import datetime
        
        # 創建 HTTP 響應
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{project.name}_analysis_results_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
        
        # 添加 BOM 以確保 Excel 正確顯示中文
        response.write('\ufeff')
        
        writer = csv.writer(response)
        
        # 寫入標題行
        headers = [
            '鑽孔編號', '深度上限(m)', '深度下限(m)', '土壤分類', 'SPT-N', 'N1_60cs', 'Vs(m/s)',
            '設計地震_Mw', '設計地震_amax(g)', '設計地震_CSR', '設計地震_CRR', '設計地震_FS', '設計地震_LPI',
            '中小地震_Mw', '中小地震_amax(g)', '中小地震_CSR', '中小地震_CRR', '中小地震_FS', '中小地震_LPI',
            '最大地震_Mw', '最大地震_amax(g)', '最大地震_CSR', '最大地震_CRR', '最大地震_FS', '最大地震_LPI'
        ]
        writer.writerow(headers)
        
        # 獲取分析結果
        results = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project
        ).select_related('soil_layer', 'soil_layer__borehole').order_by(
            'soil_layer__borehole__borehole_id', 'soil_layer__top_depth'
        )
        
        # 寫入資料行
        for result in results:
            row = [
                result.soil_layer.borehole.borehole_id,
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
    """重新執行液化分析"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            print(f"=== 開始重新分析專案 {project.name} ===")
            
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
            
            # 清除現有的分析結果
            print("正在清除現有分析結果...")
            deleted_count = AnalysisResult.objects.filter(
                soil_layer__borehole__project=project
            ).count()
            
            AnalysisResult.objects.filter(
                soil_layer__borehole__project=project
            ).delete()
            
            print(f"已清除 {deleted_count} 個現有分析結果")
            
            # ====== 重要修改：不要在這裡設定狀態為 processing ======
            # 移除以下兩行：
            # project.status = 'processing'
            # project.save()
            
            # 重設錯誤訊息，但不改變狀態，讓 analysis_engine 自己管理
            project.error_message = ''
            project.save()
            
            print("正在載入分析引擎...")
            # 執行液化分析
            from .services.analysis_engine import LiquefactionAnalysisEngine
            
            print("創建分析引擎實例...")
            analysis_engine = LiquefactionAnalysisEngine(project)
            
            print("執行重新分析...")
            analysis_result = analysis_engine.run_analysis()
            
            print(f"重新分析結果: {analysis_result}")
            
            if analysis_result['success']:
                messages.success(
                    request, 
                    f'重新分析完成！共分析 {analysis_result["analyzed_layers"]} 個土層，'
                    f'使用 {analysis_result["analysis_method"]} 方法。'
                )
                
                # 顯示警告訊息
                for warning in analysis_result.get('warnings', []):
                    messages.warning(request, f'警告：{warning}')
                
                return redirect('liquefaction:results', pk=project.pk)
            else:
                messages.error(request, f'重新分析失敗：{analysis_result["error"]}')
                
                # 顯示詳細錯誤
                for error in analysis_result.get('errors', []):
                    messages.error(request, f'錯誤：{error}')
                
                return redirect('liquefaction:project_detail', pk=project.pk)
                
        except Exception as e:
            messages.error(request, f'重新分析過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
            
            return redirect('liquefaction:project_detail', pk=project.pk)
    
    # GET 請求，顯示重新分析確認頁面
    context = {
        'project': project,
        'boreholes_count': BoreholeData.objects.filter(project=project).count(),
        'layers_count': SoilLayer.objects.filter(borehole__project=project).count(),
        'existing_results_count': AnalysisResult.objects.filter(
            soil_layer__borehole__project=project
        ).count(),
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
