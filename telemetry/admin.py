from django.contrib import admin
from .models import AiDecisionLog

# Register your models here.
@admin.register(AiDecisionLog)
class AiDecisionLogAdmin(admin.ModelAdmin):
    # Configura las columnas visibles en el panel web
    list_display = ('control_id', 'value', 'action_taken', 'created_at')
    # Permite filtar los logs por fecha
    list_filter = ('created_at',)
    # Permite buscar por el texto de la decision
    search_fields = ('action_taken',)