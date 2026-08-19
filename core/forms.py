import base64

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password

from .models import (
    Logo, Sector, Trade, Level, TradeLevel, Trainer,
    Module, LearningOutcome, IndicativeContent, LessonPlan,
)

MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def encode_image_to_base64(uploaded_file):
    """
    Reads an uploaded image file and returns it as a data URI string
    (e.g. "data:image/png;base64,iVBORw0KG...") suitable for storing
    directly in Logo.image (a TextField) and for use as an <img src="">.
    """
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    encoded = base64.b64encode(raw_bytes).decode('utf-8')
    content_type = getattr(uploaded_file, 'content_type', None) or 'image/png'
    return f'data:{content_type};base64,{encoded}'


class StyledAuthenticationForm(AuthenticationForm):
    """Django's built-in login form, dressed up with Bootstrap classes."""

    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your username',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
        })
    )


class BootstrapModelForm(forms.ModelForm):
    """Adds Bootstrap 5 form-control / form-select classes to every field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')
            widget.attrs.setdefault('placeholder', field.label)


class LogoForm(BootstrapModelForm):
    logo_file = forms.ImageField(
        label='Logo Image',
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/png, image/jpeg, image/webp, image/svg+xml',
        }),
        help_text='PNG, JPG, WEBP or SVG, up to 2 MB. Stored securely and shown as a live preview.',
    )

    class Meta:
        model = Logo
        # NOTE: 'logo_file' is intentionally NOT listed here — it's not a
        # model field. It's declared above and Django automatically
        # includes it on the form regardless of Meta.fields.
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['logo_file'].required = True

    def clean_logo_file(self):
        logo_file = self.cleaned_data.get('logo_file')
        if logo_file and logo_file.size > MAX_LOGO_SIZE_BYTES:
            raise forms.ValidationError('Image must be smaller than 2 MB.')
        return logo_file

    def save(self, commit=True):
        logo = super().save(commit=False)
        logo_file = self.cleaned_data.get('logo_file')
        if logo_file:
            logo.image = encode_image_to_base64(logo_file)
        if commit:
            logo.save()
        return logo


class SectorForm(BootstrapModelForm):
    class Meta:
        model = Sector
        fields = ['sector_name']


class TradeForm(BootstrapModelForm):
    class Meta:
        model = Trade
        fields = ['sector', 'trade_name']


class LevelForm(BootstrapModelForm):
    class Meta:
        model = Level
        fields = ['class_level']


class TradeLevelForm(BootstrapModelForm):
    class Meta:
        model = TradeLevel
        fields = ['trade', 'level']


class TrainerForm(BootstrapModelForm):
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        required=False,
        help_text='Leave blank to keep the current password when editing.'
    )

    class Meta:
        model = Trainer
        fields = ['fname', 'lname', 'username']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['password'].required = True

    def save(self, commit=True):
        trainer = super().save(commit=False)
        raw_password = self.cleaned_data.get('password')
        if raw_password:
            trainer.password_hash = make_password(raw_password)
        if commit:
            trainer.save()
        return trainer


class ModuleForm(BootstrapModelForm):
    class Meta:
        model = Module
        # Trainer first: recording a Module starts with "who teaches
        # it", then the curriculum placement (trade/level), then the
        # module's own identity.
        fields = ['trainer', 'trade', 'level', 'mod_code', 'mod_name', 'learning_hours', 'term']


class LearningOutcomeForm(BootstrapModelForm):
    class Meta:
        model = LearningOutcome
        fields = ['module', 'outcome_text', 'learning_hours']
        widgets = {
            'outcome_text': forms.Textarea(attrs={'rows': 3}),
        }


class IndicativeContentForm(BootstrapModelForm):
    class Meta:
        model = IndicativeContent
        fields = ['outcome', 'indic_name']
        widgets = {
            'indic_name': forms.Textarea(attrs={'rows': 3}),
        }


class LessonPlanForm(BootstrapModelForm):
    class Meta:
        model = LessonPlan
        fields = ['module', 'trainer', 'title', 'week', 'lesson_date', 'objectives', 'activities', 'resources']
        widgets = {
            'lesson_date': forms.DateInput(attrs={'type': 'date'}),
            'objectives': forms.Textarea(attrs={'rows': 3}),
            'activities': forms.Textarea(attrs={'rows': 3}),
            'resources': forms.Textarea(attrs={'rows': 2}),
        }


# ---------------------------------------------------------------------------
# Bulk-create workflow: "pick a parent once, then add several children"
#
# Learning Outcomes belong to a Module, and Indicative Contents belong to a
# Learning Outcome. Admins almost always add several of these at a time for
# the *same* parent (e.g. 5 outcomes for one module), so the single-record
# BootstrapModelForm above is repetitive for that job. These picker forms +
# formsets power a dedicated "add multiple" screen: choose the parent once,
# then fill in as many child rows as needed and save them all together.
# ---------------------------------------------------------------------------
class ModulePickerForm(forms.Form):
    """Step 1 of the Learning Outcome bulk-create screen: which module are
    these outcomes for. Rendered as a locked/read-only summary instead of
    this dropdown whenever the module was already chosen (e.g. the admin
    arrived via a module's "Add outcomes" quick link)."""
    module = forms.ModelChoiceField(
        queryset=Module.objects.select_related('trade', 'level').order_by('mod_code'),
        label='Module',
        empty_label='Select a module…',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class OutcomePickerForm(forms.Form):
    """Step 1 of the Indicative Content bulk-create screen: which learning
    outcome these contents belong to."""
    outcome = forms.ModelChoiceField(
        queryset=LearningOutcome.objects.select_related('module').order_by('module__mod_code', 'id'),
        label='Learning Outcome',
        empty_label='Select a learning outcome…',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['outcome'].label_from_instance = (
            lambda obj: f"{obj.module.mod_code} — {obj.outcome_text[:70]}"
        )


class LearningOutcomeQuickForm(BootstrapModelForm):
    """One row of the Learning Outcome bulk-create formset. Deliberately
    excludes 'module' — that's chosen once via ModulePickerForm and applied
    to every row on save."""
    class Meta:
        model = LearningOutcome
        fields = ['outcome_text', 'learning_hours']
        widgets = {
            'outcome_text': forms.Textarea(attrs={'rows': 2}),
        }


class IndicativeContentQuickForm(BootstrapModelForm):
    """One row of the Indicative Content bulk-create formset. Excludes
    'outcome' — that's chosen once via OutcomePickerForm."""
    class Meta:
        model = IndicativeContent
        fields = ['indic_name']
        widgets = {
            'indic_name': forms.Textarea(attrs={'rows': 2}),
        }


LearningOutcomeFormSet = forms.formset_factory(LearningOutcomeQuickForm, extra=3, can_delete=True)
IndicativeContentFormSet = forms.formset_factory(IndicativeContentQuickForm, extra=4, can_delete=True)
