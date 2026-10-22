from django.db import models

# Create your models here.

class AiDecisionLog(models.Model):
    control_id = models.IntegerField(help_text="ID del control MIDI fisico")
    value = models.IntegerField(help_text="Valor procesado (0-127)")
    action_taken = models.CharField(max_length=255, help_text="Decision matematica generada.")
    # Equivalente a @PrePersist en Java:
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Control {self.control_id} -> {self.action_taken}"