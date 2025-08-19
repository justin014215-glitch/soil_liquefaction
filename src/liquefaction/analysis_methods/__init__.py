# src/liquefaction/analysis_methods/__init__.py
"""
液化分析方法模組
包含各種標準的液化評估方法
"""

# 列出目錄內容
import os
analysis_methods_dir = os.path.dirname(__file__)
files = [f for f in os.listdir(analysis_methods_dir) if f.endswith('.py') and f != '__init__.py']
print(f"找到的 Python 檔案: {files}")

# 嘗試導入 HBF
try:
    # 嘗試相對導入
    try:
        from .HBF import HBF
    except ImportError:
        # 如果相對導入失敗，嘗試絕對導入
        from HBF import HBF
    HBF_AVAILABLE = True
    print("✓ 成功載入 HBF 分析方法")
except ImportError as e:
    HBF_AVAILABLE = False
    print(f"⚠ 無法載入 HBF: {e}")

# 嘗試導入 NCEER
try:
    try:
        from .NCEER import NCEER
    except ImportError:
        from NCEER import NCEER
    NCEER_AVAILABLE = True
    print("✓ 成功載入 NCEER 分析方法")
except ImportError as e:
    NCEER_AVAILABLE = False
    print(f"⚠ 無法載入 NCEER: {e}")

# 嘗試導入 AIJ
try:
    try:
        from .AIJ import AIJ
    except ImportError:
        from AIJ import AIJ
    AIJ_AVAILABLE = True
    print("✓ 成功載入 AIJ 分析方法")
except ImportError as e:
    AIJ_AVAILABLE = False
    print(f"⚠ 無法載入 AIJ: {e}")

# 嘗試導入 JRA
try:
    try:
        from .JRA import JRA
    except ImportError:
        from JRA import JRA
    JRA_AVAILABLE = True
    print("✓ 成功載入 JRA 分析方法")
except ImportError as e:
    JRA_AVAILABLE = False
    print(f"⚠ 無法載入 JRA: {e}")

print(f"分析方法目錄已載入，位置: {analysis_methods_dir}")