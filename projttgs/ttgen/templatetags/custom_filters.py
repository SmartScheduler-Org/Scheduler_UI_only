from django import template

register = template.Library()

@register.filter
def index(list_var, i):
    try:
        return list_var[i]
    except:
        return ""
