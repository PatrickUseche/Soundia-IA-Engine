from django.urls import path
from . import views

urlpatterns = [
    # Esta ruta se unira al prefijo principal
    path('mix/calculate', views.calculate_mix, name='calculate_mix')
]
