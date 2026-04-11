from io import BytesIO
from django.template.loader import get_template


def _get_pisa():
    from xhtml2pdf import pisa

    return pisa

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html  = template.render(context_dict)
    result = BytesIO()
    pisa = _get_pisa()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)

    if not pdf.err:
        return result.getvalue()
    return None

def section_sort_key(section_id: str):
    s = section_id.lower()

    # 🔴 MTech overrides (ALWAYS LAST)
    if s.startswith("mtech") and "3rd" in s:
        sem_order = 5
    elif s.startswith("mtech") and "1st" in s:
        sem_order = 4
    elif "3rd" in s:
        sem_order = 1
    elif "5th" in s:
        sem_order = 2
    elif "7th" in s:
        sem_order = 3
    else:
        sem_order = 99

    # 🔵 Branch ordering inside semester
    if s.startswith("ce31"):
        branch_order = 1
    elif s.startswith("ce32"):
        branch_order = 2
    elif "ce hindi" in s:
        branch_order = 3
    elif "datascience" in s or "ce-ds" in s:
        branch_order = 4
    elif s.startswith("it"):
        branch_order = 5
    else:
        branch_order = 50

    return (sem_order, branch_order, section_id)
