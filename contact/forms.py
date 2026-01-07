from django import forms


class ContactForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        label="Your name",
        widget=forms.TextInput(attrs={
            "class": "w-full rounded-input border border-border bg-background px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary",
            "placeholder": "Jane Doe",
        }),
    )

    email = forms.EmailField(
        label="Your email",
        widget=forms.EmailInput(attrs={
            "class": "w-full rounded-input border border-border bg-background px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary",
            "placeholder": "jane@example.com",
        }),
    )

    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            "class": "w-full rounded-input border border-border bg-background px-4 py-2 min-h-[140px] focus:outline-none focus:ring-2 focus:ring-primary",
            "placeholder": "What would you like to connect about?",
        }),
    )

    # Honeypot field (hidden via CSS)
    website = forms.CharField(required=False)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Spam detected.")
        return ""
