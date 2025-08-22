# src/liquefaction/forms.py
from django import forms
from .models import AnalysisProject


class AnalysisProjectForm(forms.ModelForm):
    """分析專案表單"""
    
    class Meta:
        model = AnalysisProject
        fields = [
            'name', 
            'description', 
            'source_file', 
            'em_value',
            'unit_weight_unit',
            'use_fault_data',
            'fault_shapefile'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '請輸入專案名稱'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '請輸入專案描述（可選）'
            }),
            'source_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.csv'
            }),
            'analysis_method': forms.Select(attrs={
                'class': 'form-select'
            }),
            'em_value': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'max': 100,
                'step': 0.1
            }),
            'unit_weight_unit': forms.Select(attrs={
                'class': 'form-select'
            }),
            'use_fault_data': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'fault_shapefile': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.shp'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 設定欄位說明
        self.fields['source_file'].help_text = '請上傳包含鑽孔資料的CSV檔案'
        self.fields['em_value'].help_text = '錘擊能量效率，範圍0-100%'
        self.fields['use_fault_data'].help_text = '是否使用斷層距離參數進行分析'
        self.fields['fault_shapefile'].help_text = '可選：上傳自定義斷層資料檔案(.shp)，若不上傳將使用系統預設資料'
        
        # 設定必填欄位
        self.fields['name'].required = True
        self.fields['source_file'].required = True
        self.fields['fault_shapefile'].required = False
    
    def clean_source_file(self):
        """驗證上傳的CSV檔案"""
        source_file = self.cleaned_data.get('source_file')
        if source_file:
            if not source_file.name.lower().endswith('.csv'):
                raise forms.ValidationError('請上傳CSV格式的檔案')
            
            # 檢查檔案大小 (限制50MB)
            if source_file.size > 50 * 1024 * 1024:
                raise forms.ValidationError('檔案大小不能超過50MB')
        
        return source_file
    
    def clean_fault_shapefile(self):
        """驗證上傳的Shapefile"""
        fault_shapefile = self.cleaned_data.get('fault_shapefile')
        if fault_shapefile:
            if not fault_shapefile.name.lower().endswith('.shp'):
                raise forms.ValidationError('請上傳.shp格式的檔案')
            
            # 檢查檔案大小 (限制100MB)
            if fault_shapefile.size > 100 * 1024 * 1024:
                raise forms.ValidationError('檔案大小不能超過100MB')
        
        return fault_shapefile


class ProjectSearchForm(forms.Form):
    """專案搜尋表單"""
    search = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '搜尋專案名稱或描述...'
        })
    )
    
    status = forms.ChoiceField(
        choices=[('', '全部狀態')] + AnalysisProject.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    analysis_method = forms.ChoiceField(
        choices=[('', '全部方法')] + [
            ('HBF', 'HBF (2012)'),
            ('NCEER', 'NCEER'),
            ('AIJ', 'AIJ'),
            ('JRA', 'JRA'),
        ],
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )