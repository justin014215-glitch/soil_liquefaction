from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import os
import csv
import mimetypes
import tempfile
from datetime import datetime
from pathlib import Path

from .models import AnalysisProject, BoreholeData, SoilLayer, AnalysisResult, Project
from .services.analysis_engine import LiquefactionAnalyzer


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
                user=request.user, status__in=['processing', 'pending']
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
                status='draft'  # 初始狀態為草稿
            )
            
            # 處理檔案上傳
            csv_processed = False
            if 'source_file' in request.FILES:
                project.source_file = request.FILES['source_file']
                project.save()
                
                # 立即處理 CSV 檔案
                try:
                    from .services.data_import_service import DataImportService
                    import_service = DataImportService(project)
                    import_result = import_service.import_csv_data(request.FILES['source_file'])
                    
                    if import_result['success']:
                        summary = import_result['summary']
                        messages.success(
                            request, 
                            f'CSV 檔案處理成功！已匯入 {summary["imported_boreholes"]} 個鑽孔，{summary["imported_layers"]} 個土層。'
                        )
                        
                        # 顯示警告訊息
                        for warning in import_result.get('warnings', []):
                            messages.warning(request, f'警告：{warning}')
                            
                        project.status = 'ready'  # 資料已準備好
                        csv_processed = True
                    else:
                        messages.error(request, f'CSV 檔案處理失敗：{import_result["error"]}')
                        project.status = 'error'
                        project.error_message = import_result["error"]
                except Exception as e:
                    messages.error(request, f'處理 CSV 檔案時發生錯誤：{str(e)}')
                    project.status = 'error'
                    project.error_message = str(e)

            # 處理斷層資料檔案
            if 'fault_shapefile' in request.FILES:
                project.fault_shapefile = request.FILES['fault_shapefile']

            project.save()

            if csv_processed:
                messages.success(request, f'專案 "{name}" 創建成功！資料已準備完成，可以開始分析。')
            else:
                messages.success(request, f'專案 "{name}" 創建成功！請上傳 CSV 檔案以開始分析。')
            
            return redirect('liquefaction:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'創建專案時發生錯誤：{str(e)}')
    
    # GET 請求顯示表單
    analyzer = LiquefactionAnalyzer()
    context = {
        'analysis_methods': [(k, v) for k, v in analyzer.supported_methods.items()],
        'unit_weight_units': [
            ('t/m3', 't/m³ (公噸/立方公尺)'),
            ('kN/m3', 'kN/m³ (千牛頓/立方公尺)')
        ],
    }
    
    return render(request, 'liquefaction/project_create.html', context)


@login_required
def project_detail(request, pk):
    """專案詳情視圖"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 獲取鑽孔資料，並預先載入相關的土層資料
    boreholes = BoreholeData.objects.filter(project=project).prefetch_related('soil_layers').order_by('borehole_id')
    
    # 為每個鑽孔計算統計資料
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
    
    # 檢查是否有分析結果文件
    analysis_files = []
    if hasattr(project, 'analysis_result_path') and project.analysis_result_path:
        result_dir = project.analysis_result_path
        if os.path.exists(result_dir):
            # 查找 ZIP 檔案
            zip_files = list(Path(result_dir).parent.glob('*.zip'))
            for zip_file in zip_files:
                analysis_files.append({
                    'name': zip_file.name,
                    'path': str(zip_file),
                    'size': zip_file.stat().st_size,
                    'created': datetime.fromtimestamp(zip_file.stat().st_ctime)
                })
    
    context = {
        'project': project,
        'boreholes': boreholes,
        'boreholes_with_stats': boreholes_with_stats,
        'total_layers': total_layers,
        'analyzed_layers': analyzed_layers,
        'analysis_progress': round(analysis_progress, 1),
        'analysis_files': analysis_files,
        'can_analyze': project.status in ['ready', 'completed', 'error'],
        'has_data': total_layers > 0,
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
                # 重新處理資料
                project.status = 'draft'
            
            if 'fault_shapefile' in request.FILES:
                project.fault_shapefile = request.FILES['fault_shapefile']
            
            project.save()
            
            messages.success(request, '專案更新成功！')
            return redirect('liquefaction:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'更新專案時發生錯誤：{str(e)}')
    
    analyzer = LiquefactionAnalyzer()
    context = {
        'project': project,
        'analysis_methods': [(k, v) for k, v in analyzer.supported_methods.items()],
        'unit_weight_units': [
            ('t/m3', 't/m³ (公噸/立方公尺)'),
            ('kN/m3', 'kN/m³ (千牛頓/立方公尺)')
        ],
    }
    
    return render(request, 'liquefaction/project_update.html', context)


@login_required
def project_delete(request, pk):
    """刪除專案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        project_name = project.name
        
        # 清理分析結果檔案
        if hasattr(project, 'analysis_result_path') and project.analysis_result_path:
            try:
                import shutil
                if os.path.exists(project.analysis_result_path):
                    shutil.rmtree(project.analysis_result_path)
            except Exception as e:
                print(f"清理分析結果檔案失敗：{e}")
        
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
            
            # 檢查檔案大小 (限制 50MB)
            if csv_file.size > 50 * 1024 * 1024:
                messages.error(request, '檔案大小不能超過 50MB')
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
                
                # 更新專案狀態
                project.status = 'ready'  # 準備就緒
                project.error_message = ''
                project.save()
                
            else:
                # 匯入失敗
                messages.error(request, f'CSV 檔案處理失敗：{import_result["error"]}')
                
                # 如果是缺少欄位的問題，提供詳細資訊
                if 'missing_fields' in import_result:
                    messages.info(request, f'可用的欄位：{", ".join(import_result["available_columns"])}')
                    messages.info(request, '請確保 CSV 檔案包含所有必要欄位')

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


@login_required
def analyze(request, pk):
    """執行液化分析 - 使用新的分析引擎"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            print(f"=== 開始分析專案 {project.name} ===")
            print(f"分析方法: {project.analysis_method}")
            
            # 檢查專案狀態
            if project.status == 'processing':
                messages.warning(request, '專案正在分析中，請稍候...')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 檢查是否有資料
            boreholes_count = BoreholeData.objects.filter(project=project).count()
            layers_count = SoilLayer.objects.filter(borehole__project=project).count()
            
            if boreholes_count == 0:
                messages.error(request, '專案中沒有鑽孔資料，請先上傳 CSV 檔案')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            if layers_count == 0:
                messages.error(request, '專案中沒有土層資料')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 更新狀態為處理中
            project.status = 'processing'
            project.save()
            
            # 準備分析資料
            analysis_data = prepare_analysis_data(project)
            
            if not analysis_data['success']:
                project.status = 'error'
                project.error_message = analysis_data['error']
                project.save()
                messages.error(request, f'準備分析資料失敗：{analysis_data["error"]}')
                return redirect('liquefaction:project_detail', pk=project.pk)
            
            # 執行液化分析
            analyzer = LiquefactionAnalyzer()
            
            print("正在執行液化分析...")
            analysis_result = analyzer.analyze(
                method=project.analysis_method,
                csv_content=analysis_data['csv_content'],
                shapefile_content=analysis_data.get('shapefile_content'),
                em_value=project.em_value,
                unit_weight_unit=project.unit_weight_unit
            )
            
            print(f"分析結果: {analysis_result['success']}")
            
            if analysis_result['success']:
                # 分析成功
                summary = analysis_result['summary']
                
                # 儲存分析結果路徑
                project.analysis_result_path = analysis_result['analysis_directory']
                project.status = 'completed'
                project.error_message = ''
                project.analyzed_at = timezone.now()
                project.save()
                
                messages.success(
                    request, 
                    f'液化分析完成！共分析 {summary["well_count"]} 個鑽孔，'
                    f'{summary["layer_count"]} 個土層，使用 {summary["analysis_method"]}。'
                )
                
                # 顯示分析詳情
                if summary.get('fault_data_used'):
                    messages.info(request, '✅ 已使用斷層距離參數進行分析')
                
                if summary.get('simplified_reports'):
                    messages.info(request, f'✅ 已生成 {len(summary["simplified_reports"])} 種地震情境報表')
                
                if summary.get('individual_reports_count', 0) > 0:
                    messages.info(request, f'✅ 已生成 {summary["individual_reports_count"]} 個鑽孔的詳細報表')
                
                return redirect('liquefaction:project_detail', pk=project.pk)
            else:
                # 分析失敗
                project.status = 'error'
                project.error_message = analysis_result['error_message']
                project.save()
                
                messages.error(request, f'液化分析失敗：{analysis_result["error_message"]}')
                return redirect('liquefaction:project_detail', pk=project.pk)
                
        except Exception as e:
            messages.error(request, f'分析過程中發生錯誤：{str(e)}')
            project.status = 'error'
            project.error_message = str(e)
            project.save()
            
            print(f"分析錯誤詳情：{e}")
            import traceback
            traceback.print_exc()
            
            return redirect('liquefaction:project_detail', pk=project.pk)
    
    # GET 請求，顯示分析確認頁面
    context = {
        'project': project,
        'boreholes_count': BoreholeData.objects.filter(project=project).count(),
        'layers_count': SoilLayer.objects.filter(borehole__project=project).count(),
        'analyzer_methods': LiquefactionAnalyzer().supported_methods,
    }
    
    return render(request, 'liquefaction/analyze.html', context)


def prepare_analysis_data(project):
    """準備分析所需的資料"""
    try:
        # 從資料庫匯出 CSV 格式資料
        boreholes = BoreholeData.objects.filter(project=project).prefetch_related('soil_layers')
        
        if not boreholes.exists():
            return {'success': False, 'error': '專案中沒有鑽孔資料'}
        
        # 建立 CSV 內容
        csv_data = []
        headers = [
            '鑽孔編號', 'TWD97_X', 'TWD97_Y', '鑽孔地表高程',
            '上限深度(公尺)', '下限深度(公尺)', '統一土壤分類', 'N_value',
            '細料(%)', '塑性指數(%)', '統體密度(t/m3)', 'water_depth(m)',
            '取樣編號', 'Em'
        ]
        csv_data.append(headers)
        
        for borehole in boreholes:
            for layer in borehole.soil_layers.all():
                row = [
                    borehole.borehole_id,
                    borehole.x_coordinate,
                    borehole.y_coordinate,
                    borehole.surface_elevation or 0,
                    layer.top_depth,
                    layer.bottom_depth,
                    layer.uscs or '',
                    layer.spt_n or '',
                    layer.fines_content or '',
                    layer.plasticity_index or '',
                    layer.unit_weight or '',
                    borehole.groundwater_depth or 0,
                    f'S-{layer.id}',  # 生成取樣編號
                    project.em_value
                ]
                csv_data.append(row)
        
        # 轉換為 CSV 字串
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(csv_data)
        csv_content = output.getvalue().encode('utf-8')
        output.close()
        
        result = {
            'success': True,
            'csv_content': csv_content,
        }
        
        # 處理斷層資料（如果有）
        if project.use_fault_data and project.fault_shapefile:
            try:
                with open(project.fault_shapefile.path, 'rb') as f:
                    result['shapefile_content'] = f.read()
            except Exception as e:
                print(f"讀取斷層檔案失敗：{e}")
                # 不是致命錯誤，繼續分析但不使用斷層資料
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}


@login_required
def download_analysis_result(request, pk, filename):
    """下載分析結果檔案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        # 安全檢查
        if not hasattr(project, 'analysis_result_path') or not project.analysis_result_path:
            raise Http404("分析結果不存在")
        
        # 構建檔案路徑
        result_dir = project.analysis_result_path
        file_path = os.path.join(os.path.dirname(result_dir), filename)
        
        # 檢查檔案是否存在且為ZIP檔案
        if not os.path.exists(file_path) or not filename.endswith('.zip'):
            raise Http404("檔案不存在")
        
        # 檢查檔案大小（避免過大檔案）
        file_size = os.path.getsize(file_path)
        if file_size > 500 * 1024 * 1024:  # 500MB限制
            raise Http404("檔案過大")
        
        # 設定回應標頭
        content_type = 'application/zip'
        
        with open(file_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = file_size
            return response
            
    except Exception as e:
        messages.error(request, f'下載檔案失敗：{str(e)}')
        return redirect('liquefaction:project_detail', pk=project.pk)


@login_required
def results(request, pk):
    """查看分析結果 - 重定向到專案詳情"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查專案狀態
    if project.status != 'completed':
        messages.warning(request, '專案尚未完成分析')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    # 重定向到專案詳情頁面，那裡會顯示下載連結
    messages.info(request, '分析已完成，請下載結果檔案查看詳細內容')
    return redirect('liquefaction:project_detail', pk=project.pk)


@login_required
def export_results(request, pk):
    """匯出分析結果 - 改為下載ZIP檔案"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    # 檢查專案狀態
    if project.status != 'completed':
        messages.error(request, '專案尚未完成分析，無法匯出結果')
        return redirect('liquefaction:project_detail', pk=project.pk)
    
    # 查找ZIP檔案
    if hasattr(project, 'analysis_result_path') and project.analysis_result_path:
        result_dir = project.analysis_result_path
        zip_files = list(Path(result_dir).parent.glob('*.zip'))
        
        if zip_files:
            # 返回第一個找到的ZIP檔案
            zip_file = zip_files[0]
            return download_analysis_result(request, pk, zip_file.name)
    
    messages.error(request, '找不到分析結果檔案')
    return redirect('liquefaction:project_detail', pk=project.pk)


# ===== API 端點 =====

@csrf_exempt
@require_http_methods(["POST"])
def api_liquefaction_analysis(request):
    """API：液化分析端點"""
    
    try:
        # 解析請求參數
        method = request.POST.get('method', 'HBF')
        em_value = float(request.POST.get('em_value', 72))
        unit_weight_unit = request.POST.get('unit_weight_unit', 't/m3')
        
        # 檢查檔案
        if 'csv_file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': '請上傳CSV檔案'
            }, status=400)
        
        csv_file = request.FILES['csv_file']
        csv_content = csv_file.read()
        
        # 可選的shapefile
        shapefile_content = None
        if 'shapefile' in request.FILES:
            shapefile = request.FILES['shapefile']
            shapefile_content = shapefile.read()
        
        # 執行分析
        analyzer = LiquefactionAnalyzer()
        result = analyzer.analyze(
            method=method,
            csv_content=csv_content,
            shapefile_content=shapefile_content,
            em_value=em_value,
            unit_weight_unit=unit_weight_unit
        )
        
        if result['success']:
            # 建立下載連結
            if result['zip_file_path']:
                zip_filename = os.path.basename(result['zip_file_path'])
                download_url = f"/api/download/{zip_filename}/"
                result['download_url'] = download_url
            
            return JsonResponse(result)
        else:
            return JsonResponse(result, status=400)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'伺服器錯誤：{str(e)}'
        }, status=500)


def api_download_result(request, filename):
    """API：下載分析結果檔案"""
    
    try:
        # 安全檢查：確保檔案在允許的目錄內
        analyzer = LiquefactionAnalyzer()
        file_path = os.path.join(analyzer.results_base_dir, filename)
        
        # 檢查檔案是否存在且為ZIP檔案
        if not os.path.exists(file_path) or not filename.endswith('.zip'):
            raise Http404("檔案不存在")
        
        # 檢查檔案大小（避免過大檔案）
        file_size = os.path.getsize(file_path)
        if file_size > 500 * 1024 * 1024:  # 500MB限制
            raise Http404("檔案過大")
        
        # 設定回應標頭
        content_type = 'application/zip'
        
        with open(file_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = file_size
            return response
            
    except Exception as e:
        raise Http404("下載失敗")


@login_required
def analysis_status(request, pk):
    """查詢分析狀態"""
    project = get_object_or_404(AnalysisProject, pk=pk, user=request.user)
    
    try:
        status_data = {
            'project_id': project.pk,
            'status': project.status,
            'progress': 0,
            'message': '',
            'has_results': False,
            'download_links': []
        }
        
        if project.status == 'completed':
            status_data['progress'] = 100
            status_data['message'] = '分析已完成'
            status_data['has_results'] = True
            
            # 查找下載檔案
            if hasattr(project, 'analysis_result_path') and project.analysis_result_path:
                result_dir = project.analysis_result_path
                if os.path.exists(result_dir):
                    # 查找 ZIP 檔案
                    zip_files = list(Path(result_dir).parent.glob('*.zip'))
                    for zip_file in zip_files:
                        status_data['download_links'].append({
                            'name': zip_file.name,
                            'url': f'/liquefaction/project/{project.pk}/download/{zip_file.name}/',
                            'size': zip_file.stat().st_size
                        })
        
        elif project.status == 'processing':
            status_data['progress'] = 50
            status_data['message'] = '分析進行中...'
        
        elif project.status == 'error':
            status_data['message'] = project.error_message or '分析發生錯誤'
        
        elif project.status == 'ready':
            status_data['message'] = '準備就緒，可開始分析'
        
        elif project.status == 'draft':
            status_data['message'] = '請上傳資料檔案'
        
        return JsonResponse(status_data)
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


def api_seismic_data(request):
    """API：獲取地震參數資料"""
    x = request.GET.get('x', '')
    y = request.GET.get('y', '')
    city = request.GET.get('city', '')
    district = request.GET.get('district', '')
    village = request.GET.get('village', '')
    
    try:
        # 如果有座標，使用座標搜尋
        if x and y:
            try:
                x_coord = float(x)
                y_coord = float(y)
                
                # 這裡可以整合您現有的地震參數查詢邏輯
                from .services.HBF import coordinate_search_from_file
                
                result = coordinate_search_from_file(x_coord, y_coord, use_fault_data=False)
                
                if result:
                    return JsonResponse({
                        'success': True,
                        'x': x_coord,
                        'y': y_coord,
                        'seismic_data': {
                            'city': result.get('縣市', ''),
                            'district': result.get('鄉鎮/區', ''),
                            'village': result.get('里', ''),
                            'zone': result.get('微分區', ''),
                            'SDS': result.get('SDS'),
                            'SMS': result.get('SMS'),
                            'SD1': result.get('SD1'),
                            'SM1': result.get('SM1'),
                            'fault_info': result.get('鄰近之斷層', ''),
                            'data_source': result.get('資料來源', '')
                        }
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': '無法查詢到該座標的地震參數'
                    })
                    
            except (ValueError, TypeError) as e:
                return JsonResponse({
                    'success': False,
                    'error': '座標格式錯誤'
                }, status=400)
        
        # 如果沒有座標但有地址資訊
        elif city or district or village:
            # TODO: 實作地址查詢邏輯
            return JsonResponse({
                'success': False,
                'message': '地址查詢功能開發中',
                'city': city,
                'district': district,
                'village': village
            })
        
        else:
            return JsonResponse({
                'success': False,
                'error': '請提供座標或地址資訊'
            }, status=400)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'查詢過程中發生錯誤：{str(e)}'
        }, status=500)


@login_required
def analysis_form(request):
    """液化分析表單頁面"""
    
    analyzer = LiquefactionAnalyzer()
    context = {
        'methods': analyzer.supported_methods,
        'default_em': 72,
        'unit_weight_options': [
            ('t/m3', 't/m³ (公噸/立方公尺)'),
            ('kN/m3', 'kN/m³ (千牛頓/立方公尺)')
        ]
    }
    
    return render(request, 'liquefaction/analysis_form.html', context)


@login_required
def cleanup_old_results(request):
    """清理舊的分析結果 - 管理員功能"""
    
    if not request.user.is_staff:
        messages.error(request, '權限不足')
        return redirect('liquefaction:index')
    
    if request.method == 'POST':
        try:
            days = int(request.POST.get('days', 7))
            
            analyzer = LiquefactionAnalyzer()
            analyzer.cleanup_old_results(days_old=days)
            
            messages.success(request, f'已清理 {days} 天前的分析結果')
            
        except Exception as e:
            messages.error(request, f'清理失敗：{str(e)}')
    
    return redirect('liquefaction:index')


# ===== 輔助函數 =====

def get_project_statistics(user):
    """獲取用戶專案統計資料"""
    
    total = AnalysisProject.objects.filter(user=user).count()
    completed = AnalysisProject.objects.filter(user=user, status='completed').count()
    processing = AnalysisProject.objects.filter(user=user, status='processing').count()
    error = AnalysisProject.objects.filter(user=user, status='error').count()
    
    return {
        'total': total,
        'completed': completed,
        'processing': processing,
        'error': error,
        'success_rate': (completed / total * 100) if total > 0 else 0
    }


def validate_analysis_parameters(project):
    """驗證分析參數"""
    
    errors = []
    
    # 檢查Em值
    if not (1 <= project.em_value <= 100):
        errors.append('Em值必須在1-100之間')
    
    # 檢查分析方法
    analyzer = LiquefactionAnalyzer()
    if project.analysis_method not in analyzer.supported_methods:
        errors.append(f'不支援的分析方法：{project.analysis_method}')
    
    # 檢查單位重單位
    valid_units = ['t/m3', 'kN/m3']
    if project.unit_weight_unit not in valid_units:
        errors.append(f'不支援的單位重單位：{project.unit_weight_unit}')
    
    return errors


def format_file_size(size_bytes):
    """格式化檔案大小"""
    
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f}{size_names[i]}"


# ===== 舊版相容性函數（保留給現有模板） =====

@login_required
def legacy_results(request, pk):
    """舊版結果查看 - 相容性函數"""
    return results(request, pk)


@login_required  
def legacy_export_results(request, pk):
    """舊版結果匯出 - 相容性函數"""
    return export_results(request, pk)