from django.http import HttpResponseForbidden
from django.views.generic.edit import ProcessFormView


class ProcessMultipleFormsView(ProcessFormView):
    def post(self, request, *args, **kwargs):
        form_classes = self.get_form_classes()
        form_name = request.POST.get("action")
        if self._individual_exists(form_name):
            return self._process_individual_form(form_name, form_classes)
        else:
            return self._process_all_forms(form_classes)

    def _individual_exists(self, form_name):
        return form_name in self.form_classes

    def _process_individual_form(self, form_name, form_classes):
        forms = self.get_forms(form_classes, (form_name,))
        form = forms.get(form_name)
        if not form:
            return HttpResponseForbidden()
        elif form.is_valid():
            return self.forms_valid(forms, form_name)
        else:
            return self.forms_invalid(forms)

    def _process_all_forms(self, form_classes):
        forms = self.get_forms(form_classes, None, True)
        if all([form.is_valid() for form in forms.values()]):  # noqa: C419
            return self.forms_valid(forms)
        else:
            return self.forms_invalid(forms)
