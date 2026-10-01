from django.shortcuts import render

def login_web(request):
    return render(request, 'Cuentas/login.html')

def registro_web(request): 
    return render(request, 'Cuentas/registro.html')