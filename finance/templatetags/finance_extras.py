from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Look up a dict by a key held in a variable.

    Needed for the import preview, where the column names are data rather than
    something the template can know in advance.
    """
    if not hasattr(mapping, "get"):
        return ""

    return mapping.get(key, "")
