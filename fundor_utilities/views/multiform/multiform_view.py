from django.views.generic.base import TemplateResponseMixin

from fundor_utilities.views.multiform import ProcessMultipleFormsView
from fundor_utilities.views.multiform.multiform_mixin import MultiFormMixin


class BaseMultipleFormsView(MultiFormMixin, ProcessMultipleFormsView):
    """
    A base view for displaying several forms.
    """


class MultiFormsView(TemplateResponseMixin, BaseMultipleFormsView):
    """
    A view for displaying several forms, and rendering a template response.
    """
