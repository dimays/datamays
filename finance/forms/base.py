"""Shared form behavior.

The one thing every form in this app had in common was restating the same
Tailwind class string on every single widget. `StyledFormMixin` does it once,
by widget type, so a form's `widgets` declaration is left saying only what is
actually specific to it — a step size, a min/max, a rows count, a date picker.
"""

from django import forms

from .widgets import CHECKBOX_CLASSES, FIELD_CLASSES

# Widgets that render a box to tick rather than a box to type in. Note
# CheckboxSelectMultiple: it renders one <input> per choice and passes its
# attrs down to each, which is exactly what's wanted here.
CHECKBOX_WIDGETS = (forms.CheckboxInput, forms.CheckboxSelectMultiple)

# Nothing to style — these render no visible control.
UNSTYLED_WIDGETS = (forms.HiddenInput, forms.MultipleHiddenInput)


def style_widget(widget) -> None:
    """Give one widget the class it should have, unless it already has one.

    `setdefault` rather than assignment is the important part: a form that
    genuinely needs different styling (the auth screens, which are roomier)
    declares its own class and this leaves it alone.
    """
    if isinstance(widget, UNSTYLED_WIDGETS):
        return

    if isinstance(widget, CHECKBOX_WIDGETS):
        widget.attrs.setdefault("class", CHECKBOX_CLASSES)
        return

    widget.attrs.setdefault("class", FIELD_CLASSES)


class StyledFormMixin:
    """Applies the app's field styling to every widget on the form.

    Put it first in the bases (`class FooForm(StyledFormMixin, forms.ModelForm)`)
    so it runs after the fields exist.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            style_widget(field.widget)
