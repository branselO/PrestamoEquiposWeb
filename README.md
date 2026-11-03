## Entorno de Desarrollo Local

Este proyecto utiliza **Docker** para manejar la base de datos PostgreSQL. Para ejecutar pcPumaDjango en tu máquina local, sigue estos pasos:

### Prerrequisitos
- Python 3.10+
- Docker y Docker Compose instalados

### Pasos de Instalación

1. **Clonar el repositorio:**
   ```bash
   git clone https://tic.posgrado.unam.mx/git/cgep_ss/pcpumadjango.git
   cd pcpumadjango

2. **Levantar la base de datos (Docker):**
    ```bash
   docker-compose up -d

3. **Crear entorno virtual e instalar dependencias:**
   ```bash
   python3 -m venv venv
   source venv\Scripts\activate
   pip install -r requirements.txt

4. **Aplicar migraciones:**
    ```bash
   python manage.py migrate

4. **Iniciar servidor:**
    ```bash
   python manage.py runserver
