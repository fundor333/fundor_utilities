from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from rest_framework.authtoken.models import Token


class SwaggerTemplateView(LoginRequiredMixin, TemplateView):
    template_name = "swagger-ui.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context["token"] = Token.objects.get(user=self.request.user)
        except Token.DoesNotExist:
            context["token"] = ""
        context["token"] = self.get_title()
        return context

    def get_title(self):
        if self.title is not None:
            title = "Swagger Rest Api"
        else:
            title = self.title
        return title
