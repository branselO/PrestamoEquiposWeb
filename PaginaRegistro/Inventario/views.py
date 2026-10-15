from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView
from .models import Categoria, Dispositivo


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class adminInventarioView(StaffRequiredMixin, TemplateView):
    template_name = 'Inventario/inventario.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '').strip()
        codigo = self.request.GET.get('codigo_inventario', '').strip()
        categoria = self.request.GET.get('categoria', '')
        estado = self.request.GET.get('estado', '')

        dispositivos = Dispositivo.objects.select_related('categoria').order_by('codigo_inventario')
        if q:
            dispositivos = dispositivos.filter(nombre__icontains=q)
        if codigo:
            dispositivos = dispositivos.filter(codigo_inventario__icontains=codigo)
        if categoria.isdigit():
            dispositivos = dispositivos.filter(categoria_id=int(categoria))
        if estado in dict(Dispositivo.ESTADOS):
            dispositivos = dispositivos.filter(estado=estado)

        context.update({
            'categorias': Categoria.objects.all(),
            'dispositivos': dispositivos,
            'estados': Dispositivo.ESTADOS,
            'q': q,
            'codigo_inventario': codigo,
            'categoria_sel': categoria,
            'estado_sel': estado,
        })
        return context


class DispositivoCreateView(StaffRequiredMixin, CreateView):
    model = Dispositivo
    model.estado = "Disponible"
    fields = ['codigo_inventario', 'nombre', 'categoria', 'especificaciones',
              'foto', 'comentarios']

    template_name = 'Inventario/form.html'
    success_url = reverse_lazy('inventario')
    extra_context = {'titulo': 'Añadir dispositivo'}


class DispositivoUpdateView(StaffRequiredMixin, UpdateView):
    model = Dispositivo
    fields = ['codigo_inventario', 'nombre', 'categoria', 'especificaciones',
              'estado', 'foto', 'comentarios']
    template_name = 'Inventario/form.html'
    success_url = reverse_lazy('inventario')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['estado'].choices = [
            choice for choice in form.fields['estado'].choices
            if choice[0] != 'prestado'
        ]
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Editar dispositivo'
        return context


class CategoriaCreateView(StaffRequiredMixin, CreateView):
    model = Categoria
    fields = ['nombre', 'descripcion']
    template_name = 'Inventario/form.html'
    success_url = reverse_lazy('inventario')
    extra_context = {'titulo': 'Añadir categoría'}
