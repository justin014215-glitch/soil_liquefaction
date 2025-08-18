# src/liquefaction/management/commands/setup_default_files.py
import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = '設置預設的斷層shapefile檔案'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source-dir',
            type=str,
            help='源檔案目錄路徑',
        )

    def handle(self, *args, **options):
        # 目標目錄
        target_dir = os.path.join(settings.MEDIA_ROOT, 'default_shapefiles')
        
        # 確保目標目錄存在
        os.makedirs(target_dir, exist_ok=True)
        
        # 檢查是否已經存在預設檔案
        shp_file = os.path.join(target_dir, '110全臺36條活動斷層數值檔(111年編修)_1110727.shp')
        
        if os.path.exists(shp_file):
            self.stdout.write(
                self.style.WARNING('預設斷層檔案已存在')
            )
            return
        
        source_dir = options.get('source_dir')
        if source_dir and os.path.exists(source_dir):
            # 複製所有相關檔案
            extensions = ['.shp', '.shx', '.dbf', '.prj', '.cpg']
            base_name = '110全臺36條活動斷層數值檔(111年編修)_1110727'
            
            copied_files = []
            for ext in extensions:
                source_file = os.path.join(source_dir, f"{base_name}{ext}")
                target_file = os.path.join(target_dir, f"{base_name}{ext}")
                
                if os.path.exists(source_file):
                    shutil.copy2(source_file, target_file)
                    copied_files.append(f"{base_name}{ext}")
                    self.stdout.write(f"已複製: {base_name}{ext}")
            
            if copied_files:
                self.stdout.write(
                    self.style.SUCCESS(f'成功複製 {len(copied_files)} 個檔案到 {target_dir}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'在 {source_dir} 中找不到斷層檔案')
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'請手動將斷層檔案放置到: {target_dir}\n'
                    f'需要的檔案:\n'
                    f'- 110全臺36條活動斷層數值檔(111年編修)_1110727.shp\n'
                    f'- 110全臺36條活動斷層數值檔(111年編修)_1110727.shx\n'
                    f'- 110全臺36條活動斷層數值檔(111年編修)_1110727.dbf\n'
                    f'- 110全臺36條活動斷層數值檔(111年編修)_1110727.prj\n'
                    f'- 110全臺36條活動斷層數值檔(111年編修)_1110727.cpg'
                )
            )