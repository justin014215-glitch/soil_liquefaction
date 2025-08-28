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
import pandas as pd

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


# 在 views.py 開頭或者創建一個新的 utils.py 文件添加這個函數

def filter_liquid_limit_messages(messages_list):
    """
    過濾掉與 liquid_limit 相關的錯誤和警告訊息
    
    Args:
        messages_list: 訊息列表
    
    Returns:
        list: 過濾後的訊息列表
    """
    if not messages_list:
        return []
    
    # 定義需要過濾的關鍵字 - 根據實際錯誤訊息調整
    filter_keywords = [
        'liquid_limit', 
        'liquid limit', 
        'll',           # 但要小心，可能會誤過濾其他包含 'll' 的訊息
        '液性限度',
        'liquid_limit 數值格式錯誤',  # 更精確的匹配
    ]
    
    filtered_messages = []
    for message in messages_list:
        message_str = str(message).lower()
        should_filter = False
        
        # 檢查是否包含任何過濾關鍵字
        for keyword in filter_keywords:
            if keyword.lower() in message_str:
                should_filter = True
                break
        
        # 特別檢查：如果訊息包含 "liquid_limit" 就一定要過濾
        if 'liquid_limit' in message_str:
            should_filter = True
            
        if not should_filter:
            filtered_messages.append(message)
    
    return filtered_messages

def check_has_non_liquid_limit_errors(error_message, errors_list):
    """
    檢查是否有非 liquid_limit 相關的錯誤
    
    Args:
        error_message: 主要錯誤訊息
        errors_list: 錯誤列表
    
    Returns:
        bool: 是否有非 liquid_limit 相關的錯誤
    """
    # 檢查主要錯誤訊息
    if error_message:
        message_str = str(error_message).lower()
        # 如果包含 liquid_limit 就視為液性限度錯誤
        if 'liquid_limit' in message_str:
            # 檢查是否還有其他類型的錯誤描述
            other_error_keywords = ['missing', '缺少', 'format', '格式', 'invalid', '無效']
            has_other_errors = any(keyword in message_str for keyword in other_error_keywords 
                                 if 'liquid_limit' not in message_str[message_str.find(keyword):])
            if not has_other_errors:
                return False  # 只是液性限度錯誤
        else:
            return True  # 有其他類型的錯誤
    
    # 檢查錯誤列表
    filtered_errors = filter_liquid_limit_messages(errors_list or [])
    return len(filtered_errors) > 0

# 使用範例 - 修改後的 file_upload 函數
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
                
                # 顯示單位檢測結果
                if 'detected_unit' in import_result and import_result['detected_unit']:
                    if import_result.get('unit_consistency', True):
                        messages.info(request, f'✓ 統體單位重單位檢測：{import_result["detected_unit"]}（與專案設定一致）')
                    else:
                        messages.warning(request, f'⚠️ 統體單位重單位檢測：{import_result["detected_unit"]}（與專案設定 {project.unit_weight_unit} 不一致）')
                
                # 使用過濾函數處理警告和錯誤訊息
                filtered_warnings = filter_liquid_limit_messages(import_result.get('warnings', []))
                for warning in filtered_warnings:
                    messages.warning(request, f'警告：{warning}')
                
                filtered_errors = filter_liquid_limit_messages(import_result.get('errors', []))
                for error in filtered_errors:
                    messages.error(request, f'錯誤：{error}')
                
                # 更新專案狀態
                project.status = 'pending'
                project.error_message = ''
                project.save()
                
            else:
                # 匯入失敗 - 檢查是否只是 liquid_limit 問題
                has_real_errors = check_has_non_liquid_limit_errors(
                    import_result["error"], 
                    import_result.get('errors', [])
                )
                
                if has_real_errors:
                    # 有真正的錯誤
                    main_error = import_result["error"]
                    filtered_main_error = filter_liquid_limit_messages([main_error])
                    
                    if filtered_main_error:
                        messages.error(request, f'CSV 檔案處理失敗：{filtered_main_error[0]}')
                    
                    # 顯示其他詳細錯誤
                    filtered_errors = filter_liquid_limit_messages(import_result.get('errors', []))
                    for error in filtered_errors:
                        messages.error(request, f'詳細錯誤：{error}')
                    
                    # 更新專案狀態為錯誤
                    project.status = 'error'
                    project.error_message = filtered_main_error[0] if filtered_main_error else "處理過程中發生錯誤"
                    project.save()
                    
                else:
                    # 只有 liquid_limit 相關問題，視為成功
                    messages.success(request, 'CSV 檔案處理完成（已忽略液性限度相關問題）')
                    project.status = 'pending'
                    project.error_message = ''
                    project.save()
                
                # 如果是缺少欄位的問題，提供詳細資訊
                if 'missing_fields' in import_result:
                    messages.info(request, f'可用的欄位：{", ".join(import_result["available_columns"])}')
                    messages.info(request, '請確保 CSV 檔案包含所有必要欄位，或使用相應的中文欄位名稱')
                
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
        
        # 在 views.py 的 export_results 函數中修改標題行部分
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

        # 根據分析方法添加不同的N值相關欄位
        if method_filter == 'JRA':
            headers.extend(['N72', 'N1_72', 'C1', 'C2', 'Na', '剪力波速Vs(m/s)', 'CRR_7.5'])
        elif method_filter == ['AIJ']:
            headers.extend(['N72', 'N1_72', 'Na', '剪力波速Vs(m/s)', 'CRR_7.5'])
        else:
            headers.extend(['N60', 'N1_60', 'N1_60cs', '剪力波速Vs(m/s)', 'CRR_7.5'])

        # 其餘欄位保持不變...
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
    """簡單版本 - 基於目錄結構搜尋"""
    import glob
    from django.conf import settings
    
    output_dirs = []
    
    try:
        analysis_output_root = getattr(settings, 'ANALYSIS_OUTPUT_ROOT', 
                                      os.path.join(settings.MEDIA_ROOT, 'analysis_outputs'))
        
        print(f"🔍 搜尋根目錄：{analysis_output_root}")
        
        if not os.path.exists(analysis_output_root):
            print(f"❌ 目錄不存在：{analysis_output_root}")
            return []
        
        # 取得專案ID的前8位（從截圖看，資料夾名稱以此開頭）
        project_id_short = str(project.id)[:8]
        print(f"🔍 搜尋專案ID：{project_id_short}")
        
        # 列出所有子目錄，尋找以專案ID開頭的目錄
        try:
            for item in os.listdir(analysis_output_root):
                item_path = os.path.join(analysis_output_root, item)
                
                if os.path.isdir(item_path):
                    print(f"📁 檢查目錄：{item}")
                    
                    # 檢查目錄名是否包含專案ID
                    if project_id_short in item:
                        output_dirs.append(item_path)
                        print(f"✅ 找到匹配目錄：{item}")
                    
                    # 也檢查是否包含專案名稱（安全的情況下）
                    elif len(project.name) > 3:
                        safe_name = "".join(c for c in project.name if c.isalnum() or c in ('-', '_'))
                        if safe_name and safe_name in item:
                            output_dirs.append(item_path)
                            print(f"✅ 找到專案名稱匹配目錄：{item}")
            
        except Exception as e:
            print(f"❌ 列出目錄時發生錯誤：{e}")
        
        print(f"🎯 找到 {len(output_dirs)} 個目錄")
        return output_dirs
        
    except Exception as e:
        print(f"❌ 搜尋時發生錯誤：{e}")
        return []

# 同時簡化 get_analysis_outputs_info 函數

@login_required 
def get_analysis_outputs_info(request, pk):
    """簡化版本的輸出資訊獲取"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        print(f"🔍 查找專案輸出：{project.name} (ID: {str(project.id)[:8]})")
        
        output_dirs = _find_project_output_directories(project)
        
        output_info = {
            'has_outputs': len(output_dirs) > 0,
            'directories': [],
            'total_files': 0,
            'total_size': 0,
            'debug_info': {
                'project_id': str(project.id)[:8] + "...",
                'project_name': project.name,
                'found_dirs': len(output_dirs),
            }
        }
        
        for output_dir in output_dirs:
            if os.path.exists(output_dir):
                dir_info = {
                    'path': output_dir,
                    'name': os.path.basename(output_dir),
                    'relative_path': os.path.basename(output_dir),  # 用於下載
                    'files': [],
                    'file_count': 0,
                    'size': 0
                }
                
                # 列出目錄中的所有檔案
                try:
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
                                
                            except OSError:
                                continue
                
                except Exception as e:
                    print(f"❌ 處理目錄 {output_dir} 時發生錯誤：{e}")
                    continue
                
                if dir_info['file_count'] > 0:
                    output_info['directories'].append(dir_info)
                    output_info['total_files'] += dir_info['file_count']
                    output_info['total_size'] += dir_info['size']
                    print(f"✅ 目錄 {dir_info['name']} 包含 {dir_info['file_count']} 個檔案")
        
        print(f"🎯 總計：{output_info['total_files']} 個檔案")
        
        return JsonResponse(output_info)
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        return JsonResponse({
            'error': str(e),
            'has_outputs': False,
            'debug_info': {
                'project_id': str(project.id)[:8] + "...",
                'project_name': project.name,
                'error_details': str(e)
            }
        })

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


@login_required
def download_borehole_report(request, pk, borehole_id):
    """下載單個鑽孔的完整報表資料夾"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    borehole = get_object_or_404(BoreholeData, project=project, borehole_id=borehole_id)
    
    try:
        import tempfile
        import zipfile
        from datetime import datetime
        from django.http import FileResponse
        
        print(f"🔍 開始生成鑽孔 {borehole_id} 的報表...")
        
        # 獲取該鑽孔的分析結果數據
        soil_layers = SoilLayer.objects.filter(borehole=borehole).prefetch_related('analysis_result')
        
        if not soil_layers.exists():
            messages.error(request, f'鑽孔 {borehole_id} 沒有土層數據')
            return redirect('liquefaction:borehole_detail', pk=project.pk, borehole_id=borehole_id)
        
        # 檢查是否有分析結果
        analysis_results = AnalysisResult.objects.filter(soil_layer__borehole=borehole)
        if not analysis_results.exists():
            messages.error(request, f'鑽孔 {borehole_id} 沒有分析結果，請先進行液化分析')
            return redirect('liquefaction:borehole_detail', pk=project.pk, borehole_id=borehole_id)
        
        # 轉換數據為DataFrame格式（類似HBF輸出格式）
        borehole_data = _convert_borehole_to_dataframe(borehole, soil_layers, analysis_results)
        
        # 創建臨時目錄
        with tempfile.TemporaryDirectory() as temp_dir:
            borehole_dir = os.path.join(temp_dir, f"鑽孔_{borehole_id}")
            os.makedirs(borehole_dir)
            
            # 生成報表檔案
            report_files = _generate_borehole_reports(borehole_data, borehole_id, borehole_dir)
            
            if not report_files:
                messages.error(request, f'生成鑽孔 {borehole_id} 報表時發生錯誤')
                return redirect('liquefaction:borehole_detail', pk=project.pk, borehole_id=borehole_id)
            
            # 創建ZIP檔案
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"鑽孔_{borehole_id}_報表_{timestamp}.zip"
            
            # 創建臨時ZIP檔案
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
                temp_zip_path = temp_zip.name
            
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 遍歷鑽孔目錄中的所有檔案
                for root, dirs, files in os.walk(borehole_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
                        print(f"📄 添加檔案：{arcname}")
            
            print(f"✅ 報表ZIP檔案創建完成：{zip_filename}")
            
            # 返回檔案響應
            response = FileResponse(
                open(temp_zip_path, 'rb'),
                as_attachment=True,
                filename=zip_filename
            )
            response['Content-Type'] = 'application/zip'
            
            # 註冊清理函數（當響應完成後刪除臨時檔案）
            # 注意：這裡需要小心處理臨時檔案清理
            
            return response
            
    except Exception as e:
        print(f"❌ 下載鑽孔報表時發生錯誤：{e}")
        import traceback
        print(traceback.format_exc())
        
        messages.error(request, f'下載鑽孔 {borehole_id} 報表時發生錯誤：{str(e)}')
        return redirect('liquefaction:borehole_detail', pk=project.pk, borehole_id=borehole_id)


def _convert_borehole_to_dataframe(borehole, soil_layers, analysis_results):
    """將數據庫中的鑽孔數據轉換為DataFrame格式"""
    data = []
    
    # 按分析方法分組
    results_by_method = {}
    for result in analysis_results:
        method = result.analysis_method
        if method not in results_by_method:
            results_by_method[method] = {}
        results_by_method[method][result.soil_layer.id] = result
    
    for layer in soil_layers:
        # 基本土層信息
        base_row = {
            '鑽孔編號': borehole.borehole_id,
            'TWD97_X': borehole.twd97_x,
            'TWD97_Y': borehole.twd97_y,
            '上限深度(公尺)': layer.top_depth,
            '下限深度(公尺)': layer.bottom_depth,
            '統一土壤分類': layer.uscs or '',
            'N': layer.spt_n,
            '塑性指數(%)': layer.plastic_index,
            '細料(%)': layer.fines_content,
            '統體單位重(t/m3)': layer.unit_weight,
            'water_depth(m)': borehole.water_depth,
            '鑽孔地表高程': borehole.surface_elevation,
        }
        
        # 為每個分析方法創建一行數據
        for method, results in results_by_method.items():
            if layer.id in results:
                result = results[layer.id]
                row = base_row.copy()
                row.update({
                    '分析方法': method,
                    '土層深度': result.analysis_depth,
                    '累計sigmav': result.sigma_v,
                    'sigma_v_CSR': result.sigma_v_csr,
                    'N1_60cs': result.n1_60cs,
                    'CRR_7_5': result.crr_7_5,
                    'FS_Design': result.fs_design,
                    'FS_MidEq': result.fs_mid,
                    'FS_MaxEq': result.fs_max,
                    'LPI_Design': result.lpi_design,
                    'LPI_MidEq': result.lpi_mid,
                    'LPI_MaxEq': result.lpi_max,
                    'Vs': result.vs,
                    # 添加更多需要的欄位...
                })
                data.append(row)
    
    return pd.DataFrame(data)


def _generate_borehole_reports(borehole_data, borehole_id, output_dir):
    """生成單個鑽孔的所有報表檔案"""
    generated_files = []
    
    try:
        # 1. 生成CSV原始數據
        csv_filename = f"{borehole_id}_原始資料.csv"
        csv_path = os.path.join(output_dir, csv_filename)
        borehole_data.to_csv(csv_path, index=False, encoding='utf-8-sig')
        generated_files.append(csv_path)
        print(f"✅ 已生成CSV：{csv_filename}")
        
        # 2. 生成Excel報表（如果report模組可用）
        try:
            from liquefaction.services.report import create_liquefaction_excel_from_dataframe
            excel_filename = f"{borehole_id}_液化分析報表.xlsx"
            excel_path = os.path.join(output_dir, excel_filename)
            
            # 只使用第一個分析方法的數據來生成Excel（避免重複）
            first_method_data = borehole_data[borehole_data['分析方法'] == borehole_data['分析方法'].iloc[0]]
            create_liquefaction_excel_from_dataframe(first_method_data, excel_path)
            generated_files.append(excel_path)
            print(f"✅ 已生成Excel：{excel_filename}")
            
        except Exception as e:
            print(f"⚠️ Excel報表生成失敗：{e}")
        
        # 3. 生成圖表（如果report模組可用）
        try:
            from liquefaction.services.report import LiquefactionChartGenerator
            
            chart_generator = LiquefactionChartGenerator(
                n_chart_size=(10, 8),
                fs_chart_size=(12, 8),
                soil_chart_size=(4, 10)
            )
            
            # 使用第一個分析方法的數據來生成圖表
            first_method_data = borehole_data[borehole_data['分析方法'] == borehole_data['分析方法'].iloc[0]]
            
            # N值圖表
            try:
                chart1 = chart_generator.generate_depth_n_chart(first_method_data, borehole_id, output_dir)
                if chart1:
                    generated_files.append(chart1)
                    print(f"✅ 已生成N值圖表")
            except Exception as e:
                print(f"⚠️ N值圖表生成失敗：{e}")
            
            # FS圖表
            try:
                chart2 = chart_generator.generate_depth_fs_chart(first_method_data, borehole_id, output_dir)
                if chart2:
                    generated_files.append(chart2)
                    print(f"✅ 已生成FS圖表")
            except Exception as e:
                print(f"⚠️ FS圖表生成失敗：{e}")
            
            # 土壤柱狀圖
            try:
                chart3 = chart_generator.generate_soil_column_chart(first_method_data, borehole_id, output_dir)
                if chart3:
                    generated_files.append(chart3)
                    print(f"✅ 已生成土壤柱狀圖")
            except Exception as e:
                print(f"⚠️ 土壤柱狀圖生成失敗：{e}")
                
        except Exception as e:
            print(f"⚠️ 圖表生成模組載入失敗：{e}")
        
        # 4. 生成摘要文件
        try:
            summary_filename = f"{borehole_id}_液化分析摘要.txt"
            summary_path = os.path.join(output_dir, summary_filename)
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(f"鑽孔 {borehole_id} 液化分析摘要\n")
                f.write("="*50 + "\n\n")
                
                # 基本資訊
                first_row = borehole_data.iloc[0]
                f.write(f"座標 (TWD97): ({first_row.get('TWD97_X', '')}, {first_row.get('TWD97_Y', '')})\n")
                f.write(f"分析方法: {', '.join(borehole_data['分析方法'].unique())}\n")
                f.write(f"分析層數: {len(borehole_data['鑽孔編號'].unique()) if '鑽孔編號' in borehole_data.columns else len(borehole_data) // len(borehole_data['分析方法'].unique())}\n\n")
                
                # 各情境LPI總計（以第一個分析方法為例）
                first_method_data = borehole_data[borehole_data['分析方法'] == borehole_data['分析方法'].iloc[0]]
                for scenario in ['Design', 'MidEq', 'MaxEq']:
                    lpi_col = f'LPI_{scenario}'
                    if lpi_col in first_method_data.columns:
                        total_lpi = sum(float(x) for x in first_method_data[lpi_col] if x != '-' and pd.notna(x))
                        f.write(f"{scenario} 情境總LPI: {total_lpi:.3f}\n")
            
            generated_files.append(summary_path)
            print(f"✅ 已生成摘要：{summary_filename}")
            
        except Exception as e:
            print(f"⚠️ 摘要檔案生成失敗：{e}")
        
        return generated_files
        
    except Exception as e:
        print(f"❌ 生成鑽孔報表時發生錯誤：{e}")
        return []
    


@login_required
def download_single_directory(request, pk, dir_name):
    """下載單一資料夾 - 簡化版本"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        import tempfile
        import zipfile
        import urllib.parse
        from datetime import datetime
        from django.http import FileResponse
        from django.conf import settings
        
        # 解碼目錄名稱
        decoded_dir_name = urllib.parse.unquote(dir_name)
        print(f"🔍 請求下載目錄：{decoded_dir_name}")
        
        # 建構完整路徑
        analysis_output_root = getattr(settings, 'ANALYSIS_OUTPUT_ROOT', 
                                      os.path.join(settings.MEDIA_ROOT, 'analysis_outputs'))
        target_dir = os.path.join(analysis_output_root, decoded_dir_name)
        
        if not os.path.exists(target_dir):
            messages.error(request, f'找不到資料夾：{decoded_dir_name}')
            return redirect('liquefaction:results', pk=project.pk)
        
        # 基本安全檢查：確保目錄包含專案ID
        project_id_short = str(project.id)[:8]
        if project_id_short not in decoded_dir_name:
            messages.error(request, '該資料夾不屬於當前專案')
            return redirect('liquefaction:results', pk=project.pk)
        
        print(f"📁 準備打包：{target_dir}")
        
        # 創建ZIP檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            temp_zip_path = temp_zip.name
        
        total_files = 0
        
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # 在ZIP中的路徑
                    if root == target_dir:
                        arcname = os.path.join(decoded_dir_name, file)
                    else:
                        rel_path = os.path.relpath(file_path, target_dir)
                        arcname = os.path.join(decoded_dir_name, rel_path)
                    
                    zipf.write(file_path, arcname)
                    total_files += 1
        
        if total_files == 0:
            messages.warning(request, f'資料夾 {decoded_dir_name} 中沒有檔案')
            os.unlink(temp_zip_path)
            return redirect('liquefaction:results', pk=project.pk)
        
        # 生成下載檔名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"{project.name}_{decoded_dir_name}_{timestamp}.zip"
        
        response = FileResponse(
            open(temp_zip_path, 'rb'),
            as_attachment=True,
            filename=download_filename
        )
        response['Content-Type'] = 'application/zip'
        
        print(f"🎯 開始下載：{download_filename} ({total_files} 個檔案)")
        return response
        
    except Exception as e:
        print(f"❌ 下載錯誤：{e}")
        messages.error(request, f'下載資料夾時發生錯誤：{str(e)}')
        return redirect('liquefaction:results', pk=project.pk)