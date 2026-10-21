from django.urls import path

from . import views

urlpatterns = [
    path('next', views.next_tracks, name='next_tracks'),
    path('transition', views.transition, name='transition'),
    path('feedback', views.feedback, name='feedback'),
    path('weights', views.weights, name='weights'),
]
