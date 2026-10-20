document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('form[data-entities-url]');
    if (!form) {
        return;
    }

    const programSelect = form.querySelector('[name="programa"]');
    const entitySelect = form.querySelector('[name="entidad_academica"]');
    if (!programSelect || !entitySelect) {
        return;
    }

    const status = document.createElement('span');
    status.className = 'helptext';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    entitySelect.insertAdjacentElement('afterend', status);

    let activeRequest;

    programSelect.addEventListener('change', async () => {
        activeRequest?.abort();
        entitySelect.replaceChildren();
        entitySelect.disabled = true;

        if (!programSelect.value) {
            entitySelect.add(new Option('Selecciona un programa primero', ''));
            status.textContent = '';
            return;
        }

        entitySelect.add(new Option('Cargando entidades académicas...', ''));
        status.textContent = '';
        activeRequest = new AbortController();

        try {
            const url = new URL(form.dataset.entitiesUrl, window.location.origin);
            url.searchParams.set('programa_id', programSelect.value);
            const response = await fetch(url, { signal: activeRequest.signal });
            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || 'No se pudieron cargar las entidades académicas.');
            }

            entitySelect.replaceChildren(new Option('Selecciona una entidad académica', ''));
            for (const entidad of result.entidades) {
                entitySelect.add(new Option(
                    `${entidad.clave} - ${entidad.nombre}`,
                    entidad.id,
                ));
            }

            entitySelect.disabled = false;
            if (result.entidades.length === 0) {
                status.textContent = 'Este programa no tiene entidades académicas registradas.';
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                return;
            }

            entitySelect.replaceChildren(new Option('No se pudieron cargar las entidades académicas', ''));
            status.textContent = error.message;
        }
    });
});
