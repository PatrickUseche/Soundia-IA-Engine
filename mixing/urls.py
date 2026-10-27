from django.urls import path

from . import views

urlpatterns = [
    path('next', views.next_tracks, name='next_tracks'),
    path('transition', views.transition, name='transition'),
    path('feedback', views.feedback, name='feedback'),
    path('weights', views.weights, name='weights'),
    path('timing', views.mix_timing, name='mix_timing'),
    path('style-model', views.style_model, name='style_model'),
    path('choices', views.choices, name='choices'),
    path('recordings', views.recordings, name='recordings'),
    path('recordings/summary', views.recordings_summary, name='recordings_summary'),
    path('recordings/export', views.recordings_export, name='recordings_export'),
    path('recordings/import', views.recordings_import, name='recordings_import'),
    path('recordings/<int:pk>', views.recording_detail, name='recording_detail'),
]
