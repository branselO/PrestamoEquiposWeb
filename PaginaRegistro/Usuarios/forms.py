from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, EntidadAcademica, Programa
from django.contrib.auth.forms import AuthenticationForm
from django import forms

class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)


# 1. Registro de Staff
class AcademicProgramFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        program_id = (
            self.data.get('programa')
            if self.is_bound
            else self.initial.get(
                'programa',
                getattr(self.instance, 'programa_id', None),
            )
        )
        self.fields['programa'].queryset = Programa.objects.order_by('nombre')
        self.fields['programa'].empty_label = 'Selecciona un programa'
        self.fields['entidad_academica'].queryset = EntidadAcademica.objects.none()
        self.fields['entidad_academica'].widget.attrs['disabled'] = True
        self.fields['entidad_academica'].empty_label = 'Selecciona un programa primero'

        if program_id:
            self.fields['entidad_academica'].queryset = EntidadAcademica.objects.filter(
                programas_impartidos__pk=program_id
            ).distinct().order_by('nombre')
            self.fields['entidad_academica'].widget.attrs.pop('disabled', None)
            self.fields['entidad_academica'].empty_label = 'Selecciona una entidad académica'


class StaffSignUpForm(AcademicProgramFormMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = (
            'email',
            'nombre',
            'apellidos',
            'numero_cuenta',
            'numero_trabajador',
            'rfc',
            'curp',
            'genero',
            'direccion',
            'telefono_celular',
            'programa',
            'entidad_academica',
        )

    def save(self, commit=True):
        # commit=False pausa el guardado en la base de datos
        user = super().save(commit=False) 
        user.is_staff = True # Asignamos el rol privilegiado
        if commit:
            user.save()
        return user

# 2. Registro de Usuario Normal
class NormalUserCreationForm(AcademicProgramFormMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = (
            'email',
            'nombre',
            'apellidos',
            'numero_cuenta',
            'numero_trabajador',
            'rfc',
            'curp',
            'genero',
            'direccion',
            'telefono_celular',
            'programa',
            'entidad_academica',
        )

class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        # 1. Primero, dejamos que Django verifique si el usuario está activo 
        super().confirm_login_allowed(user)
        
        # 2. Si está activo, verificamos si es Staff. Si no lo es, lanzamos un error.
        if not user.is_staff:
            raise forms.ValidationError(
                "Acceso denegado. Esta puerta de acceso es exclusiva para el personal administrativo.",
                code='invalid_login'
            )