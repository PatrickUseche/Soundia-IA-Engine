from django.contrib import admin

from .models import Track


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ('title', 'bpm', 'key', 'camelot', 'energy', 'duration', 'created_at')
    list_filter = ('camelot', 'created_at')
    search_fields = ('title',)
    ordering = ('-created_at',)
