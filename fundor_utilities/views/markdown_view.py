from django.views.generic import DetailView

from fundor_utilities.models import MarkdownContent


class MarkdownContentView(DetailView):
    model = MarkdownContent
    context_object_name = "markdown_content"
