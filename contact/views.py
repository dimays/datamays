from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView

from .forms import ContactForm


class ContactView(FormView):
    template_name = "contact/contact_form.html"
    form_class = ContactForm
    success_url = reverse_lazy("contact:contact_success")

    def form_valid(self, form):
        name = form.cleaned_data["name"]
        email = form.cleaned_data["email"]
        message = form.cleaned_data["message"]

        subject = f"New contact form submission from {name}"
        body = (
            f"Name: {name}\n"
            f"Email: {email}\n\n"
            f"Message:\n{message}"
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.CONTACT_RECIPIENT_EMAIL],
            fail_silently=False,
        )

        return super().form_valid(form)


class ContactSuccessView(TemplateView):
    template_name = "contact/contact_success.html"
