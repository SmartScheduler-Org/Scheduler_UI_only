from django.http import HttpResponse
from django.template.loader import render_to_string

def render_pdf(template_name, context):
    from weasyprint import HTML

    html_string = render_to_string(template_name, context)
    html = HTML(string=html_string)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename=\"timetable.pdf\"'

    html.write_pdf(response)
    return response
