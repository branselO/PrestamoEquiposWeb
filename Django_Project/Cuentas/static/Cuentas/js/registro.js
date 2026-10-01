const btnEscanear = document.getElementById('btn-escanear');
const btnGuardar = document.getElementById('btn-guardar');
    
const inputHuella = document.getElementById('huella-input');
const mensaje = document.getElementById('mensaje-estado');

btnEscanear.addEventListener('click', async () => {
mensaje.innerText = "Por favor, coloca tu dedo en el lector USB...";
btnEscanear.disabled = true;

try {
    // ¡AQUÍ ESTÁ LA MAGIA!
    // Tu página web (Django) le habla al Puente Local (PC Windows)
    const respuesta = await fetch('http://127.0.0.1:5000/api/escanear');
    const datos = await respuesta.json();

    if (datos.status === "success") {
        mensaje.innerText = "¡Huella capturada exitosamente!";
        // Guardamos el texto en el input oculto del formulario
        inputHuella.value = datos.template; 
        // Activamos el botón para que el admin lo envíe a Django
        btnGuardar.disabled = false; 
    } else {
        mensaje.innerText = "Error del lector: " + datos.mensaje;
    }
    
    } catch (error) {
        mensaje.innerText = "Error de conexión. ¿Está corriendo el Puente Local en esta PC?";
        console.error(error);
    } finally {
        btnEscanear.disabled = false;
    }
});