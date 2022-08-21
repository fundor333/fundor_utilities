from django import template
from django.conf import settings

register = template.Library()


@register.filter
def table_page_range(page, paginator):
    """
    Given an page and paginator, return a list of max 10 (by default) page numbers:
     - always containing the first, last and current page.
     - containing one or two '...' to skip ranges between first/last and current.
    Example:
        {% for p in table.page|table_page_range:table.paginator %}
            {{ p }}
        {% endfor %}
    """

    page_range = getattr(settings, "DJANGO_FILTER_SORT_PAGE_RANGE", 10)

    num_pages = paginator.num_pages
    if num_pages <= page_range:
        return range(1, num_pages + 1)

    range_start = page.number - int(page_range / 2)
    if range_start < 1:
        range_start = 1
    range_end = range_start + page_range
    if range_end >= num_pages:
        range_start = num_pages - page_range + 1
        range_end = num_pages + 1

    ret = range(range_start, range_end)
    if 1 not in ret:
        ret = [1, "..."] + list(ret)[2:]
    if num_pages not in ret:
        ret = list(ret)[:-2] + ["...", num_pages]
    return ret


@register.simple_tag
def url_replace(value, field_name, params=None):
    """
    Give a field and a value and it's update the post parameter for the url accordly
    """
    url = f"?{field_name}={value}"
    if params:
        querystring = params.split("&")
        filtered_querystring = filter(
            lambda p: p.split("=")[0] != field_name, querystring
        )
        encoded_querystring = "&".join(filtered_querystring)
        url = f"{url}&{encoded_querystring}"
    return url


@register.simple_tag
def url_replace_diff(request, field, value):
    """
    Give a field and a value and it's update the post parameter for the url accordly
    """
    dict_ = request.GET.copy()
    dict_[field] = value
    return dict_.urlencode()
