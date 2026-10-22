from django.urls import path

from . import views

urlpatterns = [
    path('analyze', views.analyze_track, name='analyze_track'),
    path('tracks', views.list_tracks, name='list_tracks'),
    path('tracks/<int:pk>', views.track_detail, name='track_detail'),
    path('tracks/<int:pk>/file', views.track_file, name='track_file'),
    path('tracks/<int:pk>/vocals', views.request_vocals, name='request_vocals'),
]
