# 創建文件：liquefaction/management/commands/fix_analysis_results.py

from django.core.management.base import BaseCommand
from liquefaction.models import AnalysisProject, AnalysisResult
from django.db.models import Count

class Command(BaseCommand):
    help = '檢查和修復分析結果'

    def add_arguments(self, parser):
        parser.add_argument(
            '--project-name',
            type=str,
            help='專案名稱',
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            help='實際執行修復（不加此參數只檢查不修復）',
        )

    def handle(self, *args, **options):
        project_name = options['project_name']
        fix_mode = options['fix']
        
        if project_name:
            try:
                project = AnalysisProject.objects.get(name=project_name)
                self.check_project(project, fix_mode)
            except AnalysisProject.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'找不到專案: {project_name}')
                )
        else:
            # 檢查所有已完成的專案
            completed_projects = AnalysisProject.objects.filter(status='completed')
            for project in completed_projects:
                self.stdout.write(f'\n檢查專案: {project.name}')
                self.check_project(project, fix_mode)

    def check_project(self, project, fix_mode):
        """檢查單個專案的分析結果"""
        
        # 統計各方法的結果
        method_stats = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project
        ).values('analysis_method').annotate(
            count=Count('id')
        ).order_by('analysis_method')
        
        self.stdout.write(f'專案 {project.name} 的分析結果:')
        
        total_results = 0
        methods_found = []
        
        for stat in method_stats:
            method = stat['analysis_method']
            count = stat['count']
            total_results += count
            methods_found.append(method)
            
            self.stdout.write(f'  {method}: {count} 個結果')
        
        if total_results == 0:
            self.stdout.write(
                self.style.WARNING(f'  警告: 專案 {project.name} 沒有任何分析結果')
            )
            return
        
        # 檢查是否缺少某些方法的結果
        expected_methods = ['HBF', 'NCEER', 'AIJ', 'JRA']
        missing_methods = [m for m in expected_methods if m not in methods_found]
        
        if missing_methods:
            self.stdout.write(
                self.style.WARNING(f'  缺少方法: {", ".join(missing_methods)}')
            )
            
            if fix_mode:
                self.stdout.write('  開始重新分析缺少的方法...')
                # 這裡可以添加重新分析的邏輯
                self.stdout.write(
                    self.style.SUCCESS('  請手動重新執行缺少的分析方法')
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ 所有方法都有結果')
            )
        
        # 檢查是否有無效的 analysis_method
        invalid_results = AnalysisResult.objects.filter(
            soil_layer__borehole__project=project
        ).exclude(analysis_method__in=expected_methods)
        
        if invalid_results.exists():
            self.stdout.write(
                self.style.ERROR(f'  發現 {invalid_results.count()} 個無效的分析方法記錄')
            )
            
            for result in invalid_results:
                self.stdout.write(f'    無效方法: "{result.analysis_method}"')
            
            if fix_mode:
                deleted_count = invalid_results.count()
                invalid_results.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'  已刪除 {deleted_count} 個無效記錄')
                )

# 使用方法：
# python manage.py fix_analysis_results --project-name testv10
# python manage.py fix_analysis_results --project-name testv10 --fix