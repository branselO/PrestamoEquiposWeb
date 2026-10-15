document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('form[data-programs-url]');
    if (!form) {
        return;
    }

    const entitySelect = form.querySelector('[name="entidad_academica"]');
    const programSelect = form.querySelector('[name="programa"]');
    if (!entitySelect || !programSelect) {
        return;
    }

    const status = document.createElement('span');
    status.className = 'helptext';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    programSelect.insertAdjacentElement('afterend', status);

    let activeRequest;

    entitySelect.addEventListener('change', async () => {
        activeRequest?.abort();
        programSelect.replaceChildren();
        programSelect.disabled = true;

        if (!entitySelect.value) {
            programSelect.add(new Option('Selecciona una entidad primero', ''));
            status.textContent = '';
            return;
        }

        programSelect.add(new Option('Cargando programas...', ''));
        status.textContent = '';
        activeRequest = new AbortController();

        try {
            const url = new URL(form.dataset.programsUrl, window.location.origin);
            url.searchParams.set('entidad_id', entitySelect.value);
            const response = await fetch(url, { signal: activeRequest.signal });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || 'No se pudieron cargar los programas.');
            }

            programSelect.replaceChildren(new Option('Selecciona un programa', ''));
            for (const programa of result.programas) {
                programSelect.add(new Option(
                    `${programa.clave} - ${programa.nombre}`,
                    programa.id,
                ));
            }

            programSelect.disabled = false;
            if (result.programas.length === 0) {
                status.textContent = 'Esta entidad no tiene programas registrados.';
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                return;
            }

            programSelect.replaceChildren(new Option('No se pudieron cargar los programas', ''));
            status.textContent = error.message;
        }
    });
});
