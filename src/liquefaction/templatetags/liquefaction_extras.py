from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """
    模板過濾器：根據動態鍵查找字典值
    使用方法：{{ dict|lookup:key }}
    """
    if dictionary and key:
        return dictionary.get(key)
    return None

@register.filter
def get_item(dictionary, key):
    """
    模板過濾器：獲取字典項目
    使用方法：{{ dict|get_item:key }}
    """
    if isinstance(dictionary, dict) and key:
        return dictionary.get(str(key))
    return None

@register.filter
def multiply(value, arg):
    """
    模板過濾器：乘法運算
    使用方法：{{ value|multiply:arg }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def percentage(value, total):
    """
    模板過濾器：計算百分比
    使用方法：{{ value|percentage:total }}
    """
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError):
        return 0

@register.simple_tag
def get_method_stats(stats_dict, method_code):
    """
    簡單標籤：獲取方法統計資料
    使用方法：{% get_method_stats analysis_methods_stats method_code %}
    """
    if stats_dict and method_code:
        return stats_dict.get(method_code, {})
    return {}

@register.inclusion_tag('liquefaction/includes/method_progress_bar.html')
def method_progress_bar(method_name, current, total):
    """
    包含標籤：顯示方法進度條
    使用方法：{% method_progress_bar method_name current total %}
    """
    try:
        progress = (current / total * 100) if total > 0 else 0
        return {
            'method_name': method_name,
            'current': current,
            'total': total,
            'progress': progress,
            'is_completed': current > 0
        }
    except (ValueError, TypeError, ZeroDivisionError):
        return {
            'method_name': method_name,
            'current': 0,
            'total': 0,
            'progress': 0,
            'is_completed': False
        }
@register.filter
def mul(value, arg):
    """
    範本過濾器：乘法運算
    使用方法：{{ value|mul:arg }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter 
def div(value, arg):
    """
    範本過濾器：除法運算
    使用方法：{{ value|div:arg }}
    """
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0
    
    