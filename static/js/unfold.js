// Scripts del admin django-unfold (PROPAGA).

// "Probar conexión" (Integraciones API) es un enlace, así que por sí solo NO envía
// el formulario: probaría el modelo guardado en la DB e ignoraría el que acabás de
// elegir en el selector. Se intercepta el click para guardar primero y probar después.
document.addEventListener('DOMContentLoaded', function () {
    var boton = document.querySelector('a[href*="probar_conexion"]');
    var form = document.querySelector('form#apiintegration_form');
    if (!boton || !form) return;

    boton.addEventListener('click', function (evento) {
        evento.preventDefault();
        var flag = document.createElement('input');
        flag.type = 'hidden';
        flag.name = '_guardar_y_probar';
        flag.value = '1';
        form.appendChild(flag);
        form.submit();
    });
});
