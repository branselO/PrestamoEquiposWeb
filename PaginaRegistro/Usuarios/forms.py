from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser
from django.contrib.auth.forms import AuthenticationForm
from django import forms

# 1. Formulario Público: Fuerza is_staff = True
class StaffSignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('email', 'nombre', 'apellidos')

    def save(self, commit=True):
        # commit=False pausa el guardado en la base de datos
        user = super().save(commit=False) 
        user.is_staff = True # Asignamos el rol privilegiado
        if commit:
            user.save()
        return user

# 2. Formulario Interno: Crea usuarios normales (is_staff = False)
class NormalUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('email', 'nombre', 'apellidos')

class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        # 1. Primero, dejamos que Django verifique si el usuario está activo (comportamiento normal)
        super().confirm_login_allowed(user)
        
        # 2. Si está activo, verificamos si es Staff. Si no lo es, lanzamos un error.
        if not user.is_staff:
            raise forms.ValidationError(
                "Acceso denegado. Esta puerta de acceso es exclusiva para el personal administrativo.",
                code='invalid_login'
            )