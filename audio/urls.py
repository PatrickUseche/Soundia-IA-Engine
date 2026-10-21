from django.urls import path

from . import views

urlpatterns = [
    path('analyze', views.analyze_track, name='analyze_track'),
    path('tracks', views.list_tracks, name='list_tracks'),
    path('tracks/<int:pk>', views.track_detail, name='track_detail'),
]
