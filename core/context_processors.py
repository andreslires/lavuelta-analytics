from django.core.cache import cache

from analytics.models import Edicion


def ediciones_processor(request):
    """Inyecta todas las ediciones ordenadas por año descendente en cada template."""
    ediciones = cache.get('ctx_all_ediciones')
    if ediciones is None:
        ediciones = list(Edicion.objects.all().order_by('-year'))
        cache.set('ctx_all_ediciones', ediciones, timeout=None)
    return {'all_ediciones': ediciones}
