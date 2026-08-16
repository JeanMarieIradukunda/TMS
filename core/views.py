import json
import logging
import re

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView
from groq import Groq, APIError, APIConnectionError, RateLimitError

from .models import (
    Logo, Sector, Trade, Level, TradeLevel, Trainer,
    Module, LearningOutcome, IndicativeContent, LessonPlan,
)
from .forms import (
    LogoForm, SectorForm, TradeForm, LevelForm, TradeLevelForm, TrainerForm,
    ModuleForm, LearningOutcomeForm, IndicativeContentForm, StyledAuthenticationForm,
    LessonPlanForm,
)

logger = logging.getLogger(__name__)


def get_client():
    """
    Builds a Groq API client from the key configured in .env / settings.
    Raises a clear, human-readable error if the key is missing or still
    set to a placeholder value, instead of letting a cryptic auth error
    bubble up from the Groq SDK.
    """
    api_key = (settings.GROQ_API_KEY or '').strip()
    if not api_key or api_key.startswith('gsk_your') or api_key == 'your-groq-api-key':
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add a valid key from "
            "https://console.groq.com/keys to your .env file."
        )
    return Groq(api_key=api_key)


# ---------------------------------------------------------------------------
# Shared data payload for the public "generator" pages
# ---------------------------------------------------------------------------
def _build_generator_payload():
    """
    Builds one JSON-serialisable snapshot of the full curriculum structure
    (sectors -> trades -> trade/level links -> modules -> learning outcomes
    -> indicative contents, plus trainers and institution logos) so that the
    public Scheme of Work and Lesson Plan generator pages can drive their
    cascading dropdowns and document preview entirely in the browser,
    without extra round trips to the server.
    """
    sectors = list(Sector.objects.values('id', 'sector_name'))

    trades = list(Trade.objects.values('id', 'trade_name', 'sector_id'))

    levels = list(Level.objects.values('id', 'class_level'))

    trade_levels = list(TradeLevel.objects.values('trade_id', 'level_id'))

    trainers = [
        {'id': t.id, 'name': t.full_name}
        for t in Trainer.objects.all()
    ]

    modules = [
        {
            'id': m.id,
            'mod_code': m.mod_code,
            'mod_name': m.mod_name,
            'trade_id': m.trade_id,
            'level_id': m.level_id,
            'trainer_id': m.trainer_id,
            'trainer_name': m.trainer.full_name if m.trainer_id else '',
            'learning_hours': m.learning_hours,
            'term': m.term,
        }
        for m in Module.objects.select_related('trainer').all()
    ]

    outcomes = list(
        LearningOutcome.objects.values('id', 'module_id', 'outcome_text', 'learning_hours')
    )

    contents = list(
        IndicativeContent.objects.values('id', 'outcome_id', 'indic_name')
    )

    logos = [

        {'id': l.id, 'name': l.name, 'image': l.image.name}
        for l in Logo.objects.all()
    ]

    return {
        'sectors': sectors,
        'trades': trades,
        'levels': levels,
        'trade_levels': trade_levels,
        'trainers': trainers,
        'modules': modules,
        'outcomes': outcomes,
        'contents': contents,
        'logos': logos,
    }


def _dump_generator_payload():
    """
    JSON-encodes the generator payload and neutralises any literal '</'
    sequence (which could otherwise prematurely close the surrounding
    <script> tag if it appeared inside free-text curriculum content).
    """
    raw = json.dumps(_build_generator_payload(), cls=DjangoJSONEncoder)
    return raw.replace('</', '<\\/')


# ---------------------------------------------------------------------------
# Shared defensive coercion helpers for AI (Groq) JSON responses.
#
# Models don't always respect "return a single string" / "return an array"
# instructions perfectly, so every field pulled out of an AI response goes
# through one of these instead of being trusted as-is - used by both the
# Scheme of Work and Lesson Plan AI endpoints below.
# ---------------------------------------------------------------------------
def _split_items(value):
    """Break a value (list or string) into a clean list of item strings,
    regardless of whether the model used commas, semicolons, newlines,
    or returned a proper array."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"\s*(?:\n|;|,)\s*", value)
        return [p.strip() for p in parts if p.strip()]
    return []


def _coerce_to_csv_line(value, max_items=None):
    """
    Defensive normalizer for fields that must render as ONE comma-separated
    line (no bullets, no numbering, no JSON arrays), even if the model
    slips and returns an array instead of a string. Also enforces an
    optional cap on the number of items.
    """
    items = _split_items(value)
    if max_items:
        items = items[:max_items]
    return ", ".join(items)


def _coerce_to_list(value, min_items=None, max_items=None, fallback=None):
    """
    Defensive normalizer for fields that must render as a bullet LIST
    (an array of short item strings), even if the model returns a single
    comma/semicolon/newline-separated string instead of a JSON array.
    Pads with `fallback` items (if provided) to satisfy min_items, and
    truncates to max_items.
    """
    items = _split_items(value)
    if max_items:
        items = items[:max_items]
    if min_items and fallback:
        i = 0
        while len(items) < min_items and i < len(fallback):
            if fallback[i] not in items:
                items.append(fallback[i])
            i += 1
    return items


def _ensure_min_steps(steps, outcome_text, min_count=3):
    """
    Guarantees the Lesson Plan generator always has at least `min_count`
    Development/Body steps, even if the AI returns fewer (e.g. because the
    outcome only has one or two indicative content items). Pads with
    generic-but-usable progressive steps grounded in the outcome text,
    which the trainer can edit before printing.
    """
    filler_bank = [
        {
            "title": "Guided practice",
            "trainer_activity": [
                "Circulates to support trainees applying the outcome hands-on",
                "Checks understanding and corrects common errors",
            ],
            "learner_activity": [
                "Practise the skill individually or in pairs under guidance",
                "Ask questions where unclear",
            ],
            "resources": "Tools & equipment, task sheet",
        },
        {
            "title": "Consolidation and review",
            "trainer_activity": [
                "Reviews key points against the learning outcome",
                "Poses follow-up questions to confirm understanding",
            ],
            "learner_activity": [
                "Summarise what was learned in their own words",
                "Respond to review questions",
            ],
            "resources": "Whiteboard, notebook",
        },
        {
            "title": "Application check",
            "trainer_activity": [
                "Sets a short task applying the outcome to a new scenario",
                "Observes and gives targeted feedback",
            ],
            "learner_activity": [
                "Attempt the task independently",
                "Reflect on feedback received",
            ],
            "resources": "Task sheet, relevant tools/materials",
        },
    ]

    padded = list(steps)
    i = 0
    while len(padded) < min_count and i < len(filler_bank):
        padded.append(filler_bank[i])
        i += 1
    return padded


# ---------------------------------------------------------------------------
# Public landing page
# ---------------------------------------------------------------------------
class LandingView(TemplateView):
    """
    Public entry point for the whole system. Shown before login and presents
    the three main modules as large, clickable tiles.
    """
    template_name = 'core/landing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'module_count': Module.objects.count(),
            'lesson_plan_count': LessonPlan.objects.count(),
        })
        return context


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class AdminLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True


class AdminLogoutView(LogoutView):
    next_page = reverse_lazy('login')


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'sector_count': Sector.objects.count(),
            'trade_count': Trade.objects.count(),
            'level_count': Level.objects.count(),
            'module_count': Module.objects.count(),
            'trainer_count': Trainer.objects.count(),
            'outcome_count': LearningOutcome.objects.count(),
            'content_count': IndicativeContent.objects.count(),
            'logo_count': Logo.objects.count(),
            'lesson_plan_count': LessonPlan.objects.count(),
            'latest_logo': Logo.objects.order_by('-id').first(),
        })
        return context


# ---------------------------------------------------------------------------
# Generic CRUD scaffolding
# ---------------------------------------------------------------------------
class BaseListView(LoginRequiredMixin, ListView):
    """
    Generic list view. Subclasses set:
      - model, headers (list[str]), columns (list[str] dotted attribute paths)
      - title, create_url_name, edit_url_name, delete_url_name
    """
    template_name = 'core/crud_list.html'
    paginate_by = 25
    headers = []
    columns = []
    title = ''
    create_url_name = ''
    edit_url_name = ''
    delete_url_name = ''
    empty_message = 'No records found.'
    thumbnail_field = None  # e.g. 'image' -> renders a preview thumbnail column

    def get_column_value(self, obj, col):
        value = obj
        for part in col.split('.'):
            if value is None:
                return ''
            value = getattr(value, part, '')
            if callable(value):
                value = value()
        return value

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = []
        for obj in context['object_list']:
            cells = [self.get_column_value(obj, col) for col in self.columns]
            row = {'pk': obj.pk, 'cells': cells}
            if self.thumbnail_field:
                row['thumbnail'] = self.get_column_value(obj, self.thumbnail_field)
            rows.append(row)
        context.update({
            'headers': self.headers,
            'rows': rows,
            'title': self.title,
            'create_url_name': self.create_url_name,
            'edit_url_name': self.edit_url_name,
            'delete_url_name': self.delete_url_name,
            'empty_message': self.empty_message,
            'has_thumbnail': bool(self.thumbnail_field),
        })
        return context


class BaseCreateView(LoginRequiredMixin, CreateView):
    template_name = 'core/crud_form.html'
    title = ''
    list_url_name = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': f'Add {self.title}',
            'list_url_name': self.list_url_name,
        })
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class BaseUpdateView(LoginRequiredMixin, UpdateView):
    template_name = 'core/crud_form.html'
    title = ''
    list_url_name = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': f'Edit {self.title}',
            'list_url_name': self.list_url_name,
        })
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class BaseDeleteView(LoginRequiredMixin, DeleteView):
    template_name = 'core/crud_delete.html'
    title = ''
    list_url_name = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.title,
            'list_url_name': self.list_url_name,
        })
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


# ---------------------------------------------------------------------------
# Sector
# ---------------------------------------------------------------------------
class SectorListView(BaseListView):
    model = Sector
    headers = ['Sector Name']
    columns = ['sector_name']
    title = 'Sectors'
    create_url_name = 'sector-create'
    edit_url_name = 'sector-edit'
    delete_url_name = 'sector-delete'
    empty_message = 'No sectors yet. Click "Add Sector" to create one.'


class SectorCreateView(BaseCreateView):
    model = Sector
    form_class = SectorForm
    title = 'Sector'
    list_url_name = 'sector-list'


class SectorUpdateView(BaseUpdateView):
    model = Sector
    form_class = SectorForm
    title = 'Sector'
    list_url_name = 'sector-list'


class SectorDeleteView(BaseDeleteView):
    model = Sector
    title = 'Sector'
    list_url_name = 'sector-list'


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------
class TradeListView(BaseListView):
    model = Trade
    headers = ['Trade Name', 'Sector']
    columns = ['trade_name', 'sector.sector_name']
    title = 'Trades'
    create_url_name = 'trade-create'
    edit_url_name = 'trade-edit'
    delete_url_name = 'trade-delete'
    empty_message = 'No trades yet. Click "Add Trade" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('sector')


class TradeCreateView(BaseCreateView):
    model = Trade
    form_class = TradeForm
    title = 'Trade'
    list_url_name = 'trade-list'


class TradeUpdateView(BaseUpdateView):
    model = Trade
    form_class = TradeForm
    title = 'Trade'
    list_url_name = 'trade-list'


class TradeDeleteView(BaseDeleteView):
    model = Trade
    title = 'Trade'
    list_url_name = 'trade-list'


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------
class LevelListView(BaseListView):
    model = Level
    headers = ['Class Level']
    columns = ['class_level']
    title = 'Levels'
    create_url_name = 'level-create'
    edit_url_name = 'level-edit'
    delete_url_name = 'level-delete'
    empty_message = 'No levels yet. Click "Add Level" to create one.'


class LevelCreateView(BaseCreateView):
    model = Level
    form_class = LevelForm
    title = 'Level'
    list_url_name = 'level-list'


class LevelUpdateView(BaseUpdateView):
    model = Level
    form_class = LevelForm
    title = 'Level'
    list_url_name = 'level-list'


class LevelDeleteView(BaseDeleteView):
    model = Level
    title = 'Level'
    list_url_name = 'level-list'


# ---------------------------------------------------------------------------
# TradeLevel
# ---------------------------------------------------------------------------
class TradeLevelListView(BaseListView):
    model = TradeLevel
    headers = ['Trade', 'Level']
    columns = ['trade.trade_name', 'level.class_level']
    title = 'Trade Levels'
    create_url_name = 'tradelevel-create'
    edit_url_name = 'tradelevel-edit'
    delete_url_name = 'tradelevel-delete'
    empty_message = 'No trade-level links yet. Click "Add Trade Level" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('trade', 'level')


class TradeLevelCreateView(BaseCreateView):
    model = TradeLevel
    form_class = TradeLevelForm
    title = 'Trade Level'
    list_url_name = 'tradelevel-list'


class TradeLevelUpdateView(BaseUpdateView):
    model = TradeLevel
    form_class = TradeLevelForm
    title = 'Trade Level'
    list_url_name = 'tradelevel-list'


class TradeLevelDeleteView(BaseDeleteView):
    model = TradeLevel
    title = 'Trade Level'
    list_url_name = 'tradelevel-list'


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------
class TrainerListView(BaseListView):
    model = Trainer
    headers = ['First Name', 'Last Name', 'Username']
    columns = ['fname', 'lname', 'username']
    title = 'Trainers'
    create_url_name = 'trainer-create'
    edit_url_name = 'trainer-edit'
    delete_url_name = 'trainer-delete'
    empty_message = 'No trainers yet. Click "Add Trainer" to create one.'


class TrainerCreateView(BaseCreateView):
    model = Trainer
    form_class = TrainerForm
    title = 'Trainer'
    list_url_name = 'trainer-list'


class TrainerUpdateView(BaseUpdateView):
    model = Trainer
    form_class = TrainerForm
    title = 'Trainer'
    list_url_name = 'trainer-list'


class TrainerDeleteView(BaseDeleteView):
    model = Trainer
    title = 'Trainer'
    list_url_name = 'trainer-list'


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------
class ModuleListView(BaseListView):
    model = Module
    headers = ['Code', 'Name', 'Trade', 'Level', 'Trainer', 'Hours', 'Term']
    columns = ['mod_code', 'mod_name', 'trade.trade_name', 'level.class_level', 'trainer.full_name', 'learning_hours', 'term']
    title = 'Modules'
    create_url_name = 'module-create'
    edit_url_name = 'module-edit'
    delete_url_name = 'module-delete'
    empty_message = 'No modules yet. Click "Add Module" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('trade', 'level', 'trainer')


class ModuleCreateView(BaseCreateView):
    model = Module
    form_class = ModuleForm
    title = 'Module'
    list_url_name = 'module-list'


class ModuleUpdateView(BaseUpdateView):
    model = Module
    form_class = ModuleForm
    title = 'Module'
    list_url_name = 'module-list'


class ModuleDeleteView(BaseDeleteView):
    model = Module
    title = 'Module'
    list_url_name = 'module-list'


# ---------------------------------------------------------------------------
# LearningOutcome
# ---------------------------------------------------------------------------
class LearningOutcomeListView(BaseListView):
    model = LearningOutcome
    headers = ['Module', 'Outcome', 'Hours']
    columns = ['module.mod_code', 'outcome_text', 'learning_hours']
    title = 'Learning Outcomes'
    create_url_name = 'outcome-create'
    edit_url_name = 'outcome-edit'
    delete_url_name = 'outcome-delete'
    empty_message = 'No learning outcomes yet. Click "Add Learning Outcome" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('module')


class LearningOutcomeCreateView(BaseCreateView):
    model = LearningOutcome
    form_class = LearningOutcomeForm
    title = 'Learning Outcome'
    list_url_name = 'outcome-list'


class LearningOutcomeUpdateView(BaseUpdateView):
    model = LearningOutcome
    form_class = LearningOutcomeForm
    title = 'Learning Outcome'
    list_url_name = 'outcome-list'


class LearningOutcomeDeleteView(BaseDeleteView):
    model = LearningOutcome
    title = 'Learning Outcome'
    list_url_name = 'outcome-list'


# ---------------------------------------------------------------------------
# IndicativeContent
# ---------------------------------------------------------------------------
class IndicativeContentListView(BaseListView):
    model = IndicativeContent
    headers = ['Outcome', 'Indicative Content']
    columns = ['outcome.outcome_text', 'indic_name']
    title = 'Indicative Contents'
    create_url_name = 'content-create'
    edit_url_name = 'content-edit'
    delete_url_name = 'content-delete'
    empty_message = 'No indicative contents yet. Click "Add Indicative Content" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('outcome')


class IndicativeContentCreateView(BaseCreateView):
    model = IndicativeContent
    form_class = IndicativeContentForm
    title = 'Indicative Content'
    list_url_name = 'content-list'


class IndicativeContentUpdateView(BaseUpdateView):
    model = IndicativeContent
    form_class = IndicativeContentForm
    title = 'Indicative Content'
    list_url_name = 'content-list'


class IndicativeContentDeleteView(BaseDeleteView):
    model = IndicativeContent
    title = 'Indicative Content'
    list_url_name = 'content-list'


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------
class LogoListView(BaseListView):
    model = Logo
    headers = ['Name']
    columns = ['name']
    thumbnail_field = 'image'
    title = 'Logos'
    create_url_name = 'logo-create'
    edit_url_name = 'logo-edit'
    delete_url_name = 'logo-delete'
    empty_message = 'No logos yet. Click "Add Logo" to create one.'


class LogoCreateView(BaseCreateView):
    model = Logo
    form_class = LogoForm
    title = 'Logo'
    list_url_name = 'logo-list'


class LogoUpdateView(BaseUpdateView):
    model = Logo
    form_class = LogoForm
    title = 'Logo'
    list_url_name = 'logo-list'


class LogoDeleteView(BaseDeleteView):
    model = Logo
    title = 'Logo'
    list_url_name = 'logo-list'


# ---------------------------------------------------------------------------
# Lesson Plans
# ---------------------------------------------------------------------------
class LessonPlanListView(BaseListView):
    model = LessonPlan
    headers = ['Title', 'Module', 'Trainer', 'Week', 'Date']
    columns = ['title', 'module.mod_code', 'trainer.full_name', 'week', 'lesson_date']
    title = 'Lesson Plans'
    create_url_name = 'lessonplan-create'
    edit_url_name = 'lessonplan-edit'
    delete_url_name = 'lessonplan-delete'
    empty_message = 'No lesson plans yet. Click "Add Lesson Plan" to create one.'

    def get_queryset(self):
        return super().get_queryset().select_related('module', 'trainer')


class LessonPlanCreateView(BaseCreateView):
    model = LessonPlan
    form_class = LessonPlanForm
    title = 'Lesson Plan'
    list_url_name = 'lessonplan-list'


class LessonPlanUpdateView(BaseUpdateView):
    model = LessonPlan
    form_class = LessonPlanForm
    title = 'Lesson Plan'
    list_url_name = 'lessonplan-list'


class LessonPlanDeleteView(BaseDeleteView):
    model = LessonPlan
    title = 'Lesson Plan'
    list_url_name = 'lessonplan-list'


# ---------------------------------------------------------------------------
# Public generator pages (Scheme of Work / Lesson Plan)
# ---------------------------------------------------------------------------
@method_decorator(ensure_csrf_cookie, name='dispatch')
class SchemeOfWorkUserView(TemplateView):
    """
    Public generator page. ensure_csrf_cookie is required here because this
    page has no {% csrf_token %} in its template (it's not a Django <form>
    POST) - without it, Django never sets the csrftoken cookie for anonymous
    visitors, so the page's own JS fetch() to /api/scheme-of-work/ai-generate/
    has no token to send and every request is rejected with 403 CSRF cookie
    not set, before it ever reaches Groq.
    """
    template_name = "scheme_of_work_user.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tms_data_json'] = _dump_generator_payload()
        return context


@method_decorator(ensure_csrf_cookie, name='dispatch')
class LessonPlanUserView(TemplateView):
    """Same reasoning as SchemeOfWorkUserView above."""
    template_name = "lesson_plan_user.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tms_data_json'] = _dump_generator_payload()
        return context

# ---------------------------------------------------------------------------
# AI (Groq) endpoint used by the Scheme of Work generator page
# ---------------------------------------------------------------------------
@require_POST
@csrf_protect
def generate_scheme_ai_content(request):
    """
    Public AI endpoint for the Scheme of Work generator page.

    Receives the module/trade/level context plus the list of learning
    outcomes (with their indicative content) selected in the browser, and
    asks Groq to draft, for EACH outcome: learning activities, resources,
    learning place, and evidence of formative assessment. The Groq API key
    never leaves the server - the browser only ever talks to this endpoint.

    Field shapes returned per outcome (ALL plain single-line strings -
    no bullets, no numbering, no JSON arrays):
    - learning_activities: a SINGLE comma-separated line naming at most 3
      facilitation methodologies/techniques (e.g. "Demonstration, Group
      discussion, Practical exercise") - not a list of steps, and not a
      restatement of the outcome or its indicative content.
    - resources: a SINGLE comma-separated line of the tools/equipment/
      materials needed to deliver THAT row's outcome and indicative
      content specifically.
    - learning_place: a single string (e.g. "Workshop").
    - evidence: a SINGLE comma-separated line naming the assessment
      type(s) used to confirm formative learning for that outcome, drawn
      from: Written assessment, Oral assessment, Practical assessment,
      Assignment. Normally just ONE type per outcome.
    """
    # --------------------------------------------------
    # 1. Parse request safely
    # --------------------------------------------------
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return JsonResponse({"error": "Invalid or missing 'outcomes' field"}, status=400)

    # Trim/validate each outcome so we never forward garbage to the model,
    # and so we know exactly which outcome_ids we expect back.
    clean_outcomes = []
    expected_ids = []
    for o in outcomes:
        if not isinstance(o, dict) or "outcome_id" not in o:
            continue
        clean_outcomes.append({
            "outcome_id": o.get("outcome_id"),
            "learning_unit": str(o.get("learning_unit", ""))[:500],
            "learning_hours": o.get("learning_hours"),
            "indicative_content": [str(c)[:300] for c in (o.get("indicative_content") or [])][:20],
        })
        expected_ids.append(o.get("outcome_id"))

    if not clean_outcomes:
        return JsonResponse({"error": "No valid outcomes supplied"}, status=400)

    context_bits = []
    if payload.get("sector"):
        context_bits.append(f"Sector: {payload['sector']}")
    if payload.get("trade"):
        context_bits.append(f"Trade/Occupation: {payload['trade']}")
    if payload.get("level"):
        context_bits.append(f"Level: {payload['level']}")
    if payload.get("module_code") or payload.get("module_name"):
        context_bits.append(f"Module: {payload.get('module_code', '')} - {payload.get('module_name', '')}")
    if payload.get("hours_per_week"):
        context_bits.append(f"Hours per week: {payload['hours_per_week']}")
    context_block = "\n".join(context_bits) or "No additional module context supplied."

    # --------------------------------------------------
    # 2. Build a structured, strict-JSON prompt
    # --------------------------------------------------
    system_prompt = (
        "You are an expert TVET (Technical and Vocational Education and Training) "
        "curriculum designer who writes practical, workshop-ready Schemes of Work. "
        "You always respond with a single valid JSON object and nothing else - "
        "no markdown fences, no commentary, no explanations."
    )

    user_prompt = f"""Using the module context below, generate practical training content for
EACH learning outcome listed in INPUT DATA.

MODULE CONTEXT:
{context_block}

For every outcome, produce FOUR fields, and every one of them must be a
SINGLE plain string on one line - NOT a JSON array, NOT bullet points, NOT
numbered steps. Where an item has more than one part, separate the parts
with ", " on that same line.

- "learning_activities": AT MOST 3 facilitation methodologies/teaching
  techniques the trainer would use to deliver that specific outcome (e.g.
  "Demonstration, Group discussion, Practical exercise" or "Role play, Q&A").
  Name ONLY the methodology/technique - do NOT describe, restate, or
  summarize the learning outcome or its indicative content, and do NOT
  write full sentences or steps. 1-3 items only.

- "resources": the specific tools, equipment, or materials required to
  deliver THIS outcome's own indicative content (e.g. "Digital multimeter,
  Safety goggles, Wiring diagram handout"). Base this strictly on what this
  row's outcome and indicative content need - do not reuse a generic list
  across rows, and do not pad with unrelated items.

- "learning_place": where the learning happens (e.g. "Classroom", "ICT Lab",
  "Workshop", "Field visit"). A single value, not a combination.

- "evidence": the assessment type(s) used to confirm formative learning
  happened for THIS outcome, chosen from: "Written assessment",
  "Oral assessment", "Practical assessment", "Assignment". Normally name
  ONLY ONE type per outcome - pick whichever best fits how this specific
  outcome and indicative content would actually be assessed. Only name a
  second type if genuinely both apply (e.g. "Practical assessment, Oral
  assessment").

Rules:
- ALL FOUR fields ("learning_activities", "resources", "learning_place",
  "evidence") must be plain strings with items separated by ", " where
  applicable - NEVER a JSON array, and NEVER containing bullet characters,
  dashes, or numbering.
- Ground every answer in the outcome's own text and its indicative content - do not invent unrelated topics.
- Use concise, real workshop/training language, not vague filler.
- Return EVERY outcome_id from the input, in the same order, exactly once.
- Respond with STRICT JSON ONLY, matching exactly this shape:
{{
  "results": [
    {{
      "outcome_id": <number>,
      "learning_activities": "<comma-separated string, max 3 items>",
      "resources": "<comma-separated string>",
      "learning_place": "<string>",
      "evidence": "<comma-separated string, usually 1 item>"
    }}
  ]
}}

INPUT DATA:
{json.dumps(clean_outcomes, indent=2)}
""".strip()

    # --------------------------------------------------
    # 3. Call Groq
    # --------------------------------------------------
    try:
        client = get_client()
    except RuntimeError as e:
        logger.error("Groq client not configured: %s", e)
        return JsonResponse({"error": str(e)}, status=500)

    model_name = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )
    except RateLimitError:
        logger.warning("Groq rate limit hit")
        return JsonResponse(
            {"error": "The AI service is rate-limited right now. Please try again in a moment."},
            status=429,
        )
    except APIConnectionError as e:
        logger.error("Could not reach Groq: %s", e)
        return JsonResponse(
            {"error": "Could not reach the AI service. Check your internet connection and try again."},
            status=502,
        )
    except APIError as e:
        # Covers invalid/expired API keys, decommissioned models, bad requests, etc.
        logger.error("Groq API error (%s): %s", getattr(e, "status_code", "?"), e)
        message = str(e)
        if getattr(e, "status_code", None) == 401:
            message = "The Groq API key is invalid or missing. Check GROQ_API_KEY in your .env file."
        elif "decommissioned" in message.lower():
            message = (
                f"The model '{model_name}' is no longer available on Groq. "
                "Update GROQ_MODEL in your .env file to a current model "
                "(see https://console.groq.com/docs/models)."
            )
        return JsonResponse({"error": message}, status=502)
    except Exception as e:
        logger.exception("Unexpected error calling Groq")
        return JsonResponse({"error": "Internal server error", "detail": str(e)}, status=500)

    raw_content = (completion.choices[0].message.content or "").strip()

    # --------------------------------------------------
    # 4. Parse the AI response safely (strip stray ```json fences just in case)
    # --------------------------------------------------
    cleaned = raw_content
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("AI returned invalid JSON: %s", raw_content)
        return JsonResponse(
            {"error": "AI returned invalid JSON", "raw_output": raw_content},
            status=502,
        )

    # --------------------------------------------------
    # 5. Validate structure
    # --------------------------------------------------
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        logger.error("AI response missing 'results' list: %s", data)
        return JsonResponse(
            {"error": "Invalid AI response structure", "raw_output": data},
            status=502,
        )

    # Coerce outcome_id back to int where possible so the frontend's
    # lookup-by-id always matches, even if the model returned a numeric string.
    for r in results:
        if not isinstance(r, dict):
            continue

        if "outcome_id" in r:
            try:
                r["outcome_id"] = int(r["outcome_id"])
            except (TypeError, ValueError):
                pass

        r["learning_activities"] = _coerce_to_csv_line(r.get("learning_activities"), max_items=3)
        r["resources"] = _coerce_to_csv_line(r.get("resources"))
        r["evidence"] = _coerce_to_csv_line(r.get("evidence"), max_items=2)

        # learning_place stays a plain string
        if "learning_place" in r and not isinstance(r["learning_place"], str):
            r["learning_place"] = str(r["learning_place"])

    # --------------------------------------------------
    # 6. Return success
    # --------------------------------------------------
    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# AI (Groq) endpoint used by the Lesson Plan (Session Plan) generator page
# ---------------------------------------------------------------------------
MIN_LESSON_PLAN_STEPS = 3
MAX_LESSON_PLAN_STEPS = 6


@require_POST
@csrf_protect
def generate_lesson_plan_ai_content(request):
    """
    Public AI endpoint for the Lesson Plan (Session Plan) generator page.

    Receives the module/trade/level context plus the single learning
    outcome (with its indicative content) selected in the browser, and
    asks Groq to draft:
      - objectives: a JSON array of 2-5 clear, measurable, learner-focused
        session objectives, synthesised from the learning outcome, the
        Range and the indicative content - NOT a copy of the indicative
        content bullets.
      - facilitation_techniques: a SINGLE comma-separated line naming at
        most 3 facilitation methodologies/techniques (same shape/rules as
        the Scheme of Work's "learning_activities" field) - not a
        restatement of the outcome or its indicative content.
      - steps: the Development/Body of the session, as a JSON array of
        AT LEAST 3 steps (padded server-side if the model returns fewer),
        each with a short sub-topic "title" plus separate "trainer_activity"
        and "learner_activity" BULLET LISTS (JSON arrays of short plain
        phrases - not sentences glued together), and a "resources" line
        specific to that step.
      - reflection: a draft ANSWER (not the bare question) for each of the
        two standard post-session reflection prompts - "went_well" and
        "change_next_time" - grounded in this specific outcome/content, for
        the trainer to revise once the session has actually been taught.

    The Groq API key never leaves the server - the browser only ever talks
    to this endpoint.
    """
    # --------------------------------------------------
    # 1. Parse request safely
    # --------------------------------------------------
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    outcome_text = str(payload.get("outcome_text", ""))[:500]
    if not outcome_text.strip():
        return JsonResponse({"error": "Missing or empty 'outcome_text' field"}, status=400)

    indicative_content = [
        str(c)[:300] for c in (payload.get("indicative_content") or [])
    ][:20]

    context_bits = []
    if payload.get("sector"):
        context_bits.append(f"Sector: {payload['sector']}")
    if payload.get("trade"):
        context_bits.append(f"Trade/Occupation: {payload['trade']}")
    if payload.get("level"):
        context_bits.append(f"Level: {payload['level']}")
    if payload.get("module_code") or payload.get("module_name"):
        context_bits.append(f"Module: {payload.get('module_code', '')} - {payload.get('module_name', '')}")
    if payload.get("topic"):
        context_bits.append(f"Session topic: {payload['topic']}")
    if payload.get("range"):
        context_bits.append(f"Range (scope for this session): {payload['range']}")
    if payload.get("total_minutes"):
        context_bits.append(f"Total session duration: {payload['total_minutes']} minutes")
    context_block = "\n".join(context_bits) or "No additional session context supplied."

    # --------------------------------------------------
    # 2. Build a structured, strict-JSON prompt
    # --------------------------------------------------
    system_prompt = (
        "You are an expert TVET (Technical and Vocational Education and Training) "
        "curriculum designer who writes practical, workshop-ready session/lesson "
        "plans. You always respond with a single valid JSON object and nothing "
        "else - no markdown fences, no commentary, no explanations."
    )

    user_prompt = f"""Using the session context below, draft the facilitation technique(s) and the
Development/Body of a competence-based training session plan for THIS
learning outcome.

SESSION CONTEXT:
{context_block}

LEARNING OUTCOME:
{outcome_text}

INDICATIVE CONTENT:
{json.dumps(indicative_content, indent=2)}

Produce a JSON object with exactly three top-level fields:

- "objectives": a JSON array of 2-5 clear, measurable, learner-focused
  session objectives - NOT a copy or rewording of the indicative content
  bullets, and NOT a restatement of the learning outcome itself. Each
  objective must:
  - Start with a single observable, measurable action verb (e.g.
    "Identify", "Describe", "Demonstrate", "Install", "Configure",
    "Troubleshoot", "Assemble", "Calculate", "Differentiate", "Apply") -
    never vague verbs like "understand", "know", or "learn".
  - Be phrased as a direct action statement starting with the verb - do
    NOT prefix it with "By the end of the session, trainees will be able
    to" or any similar lead-in (e.g. write "Configure a basic network
    switch", not "By the end of the session, trainees will be able to
    configure a basic network switch").
  - Be scoped to what THIS session actually covers - i.e. grounded in,
    but synthesised from, the learning outcome, the Range, and the
    indicative content above, not a line-by-line restatement of any one
    of them.
  - Be short (one sentence each) and independently achievable/assessable.

- "facilitation_techniques": AT MOST 3 facilitation methodologies/teaching
  techniques the trainer would use across this session (e.g.
  "Demonstration, Group discussion, Practical exercise"). A SINGLE plain
  string on one line, items separated by ", " - NOT a JSON array, NOT
  bullet points. Name ONLY the methodology/technique, not a description.

- "steps": a JSON array covering the Development/Body of the session,
  broken into logical, progressive sub-topics grounded in the indicative
  content above. Requirements:
  - MINIMUM {MIN_LESSON_PLAN_STEPS} steps, MAXIMUM {MAX_LESSON_PLAN_STEPS} steps, ALWAYS.
  - If fewer than {MIN_LESSON_PLAN_STEPS} indicative content items are given, split
    the content into progressive stages instead (e.g. explanation and
    demonstration, guided/hands-on practice, independent practice or
    verification) so the step count still meets the minimum.
  - If there are more indicative content items than {MAX_LESSON_PLAN_STEPS}, group
    closely related items together into a single step.
  - Each step is an object with FOUR fields:
    - "title": a short sub-topic label (a few words, NOT a full sentence,
      NOT prefixed with "Step" or a number - the app numbers steps itself).
    - "trainer_activity": a JSON array of 2-4 SHORT, concrete, plain-text
      bullet phrases describing what the trainer does for this step
      (imperative mood, e.g. "Demonstrates the wiring sequence"). Each
      item is its own array entry - NOT one long sentence, NOT numbered,
      NOT starting with a dash or bullet character.
    - "learner_activity": a JSON array of 2-3 SHORT, concrete, plain-text
      bullet phrases describing what the trainee does for this step, in
      the same style as trainer_activity.
    - "resources": the specific tools, equipment, or materials this step
      needs - a SINGLE comma-separated plain string, not an array.

- "reflection": a JSON object with exactly two fields, each a short DRAFT
  ANSWER (1-2 plain sentences) written from the trainer's point of view,
  grounded in this specific outcome/content - NOT the question itself,
  and NOT generic filler. Since the session hasn't been delivered yet,
  phrase both as realistic, specific anticipations the trainer can revise
  after actually teaching it:
  - "went_well": what is likely to land well in this session, and why
    (e.g. which activity, demonstration, or hands-on moment).
  - "change_next_time": one concrete thing worth watching or adjusting
    (e.g. pacing, a step that may need more practice time, a resource
    that may be in short supply).

Rules:
- Ground every objective and every step in the outcome's own text, the
  Range, and the indicative content - do not invent unrelated topics, and
  do not simply copy or lightly reword any indicative content line as an
  objective.
- Use concise, real workshop/training language, not vague filler.
- Respond with STRICT JSON ONLY, matching exactly this shape:
{{
  "objectives": ["<objective 1>", "<objective 2>"],
  "facilitation_techniques": "<comma-separated string, max 3 items>",
  "steps": [
    {{
      "title": "<short sub-topic label>",
      "trainer_activity": ["<bullet 1>", "<bullet 2>"],
      "learner_activity": ["<bullet 1>", "<bullet 2>"],
      "resources": "<comma-separated string>"
    }}
  ],
  "reflection": {{
    "went_well": "<1-2 sentence draft answer>",
    "change_next_time": "<1-2 sentence draft answer>"
  }}
}}
""".strip()

    # --------------------------------------------------
    # 3. Call Groq
    # --------------------------------------------------
    try:
        client = get_client()
    except RuntimeError as e:
        logger.error("Groq client not configured: %s", e)
        return JsonResponse({"error": str(e)}, status=500)

    model_name = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )
    except RateLimitError:
        logger.warning("Groq rate limit hit")
        return JsonResponse(
            {"error": "The AI service is rate-limited right now. Please try again in a moment."},
            status=429,
        )
    except APIConnectionError as e:
        logger.error("Could not reach Groq: %s", e)
        return JsonResponse(
            {"error": "Could not reach the AI service. Check your internet connection and try again."},
            status=502,
        )
    except APIError as e:
        logger.error("Groq API error (%s): %s", getattr(e, "status_code", "?"), e)
        message = str(e)
        if getattr(e, "status_code", None) == 401:
            message = "The Groq API key is invalid or missing. Check GROQ_API_KEY in your .env file."
        elif "decommissioned" in message.lower():
            message = (
                f"The model '{model_name}' is no longer available on Groq. "
                "Update GROQ_MODEL in your .env file to a current model "
                "(see https://console.groq.com/docs/models)."
            )
        return JsonResponse({"error": message}, status=502)
    except Exception as e:
        logger.exception("Unexpected error calling Groq")
        return JsonResponse({"error": "Internal server error", "detail": str(e)}, status=500)

    raw_content = (completion.choices[0].message.content or "").strip()

    # --------------------------------------------------
    # 4. Parse the AI response safely (strip stray ```json fences just in case)
    # --------------------------------------------------
    cleaned = raw_content
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("AI returned invalid JSON: %s", raw_content)
        return JsonResponse(
            {"error": "AI returned invalid JSON", "raw_output": raw_content},
            status=502,
        )

    if not isinstance(data, dict):
        logger.error("AI response is not a JSON object: %s", data)
        return JsonResponse(
            {"error": "Invalid AI response structure", "raw_output": data},
            status=502,
        )

    # --------------------------------------------------
    # 5. Validate & defensively coerce structure
    # --------------------------------------------------
    # Objectives must never fall back to a copy of the indicative content -
    # if the model returns nothing usable, fall back to a single generic
    # objective built from the outcome text only.
    short_outcome = outcome_text.strip()
    if ":" in short_outcome:
        short_outcome = short_outcome.split(":", 1)[1].strip()
    objectives = _coerce_to_list(
        data.get("objectives"),
        min_items=2,
        max_items=5,
        fallback=[
            f"Apply {short_outcome[:120]}." if short_outcome
            else "Perform the key steps covered in this session.",
            "Explain the key steps covered in this session in their own words.",
        ],
    )

    facilitation_techniques = _coerce_to_csv_line(
        data.get("facilitation_techniques"), max_items=3
    )

    raw_steps = data.get("steps")
    steps = []
    if isinstance(raw_steps, list):
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            steps.append({
                "title": str(s.get("title", "")).strip()[:120],
                "trainer_activity": _coerce_to_list(
                    s.get("trainer_activity"),
                    min_items=2,
                    max_items=4,
                    fallback=["Guides trainees through this step"],
                ),
                "learner_activity": _coerce_to_list(
                    s.get("learner_activity"),
                    min_items=2,
                    max_items=3,
                    fallback=["Participate in the activity under guidance"],
                ),
                "resources": _coerce_to_csv_line(s.get("resources")),
            })

    # Always guarantee at least MIN_LESSON_PLAN_STEPS steps, and never more
    # than MAX_LESSON_PLAN_STEPS, regardless of what the model returned.
    steps = _ensure_min_steps(steps, outcome_text, min_count=MIN_LESSON_PLAN_STEPS)
    steps = steps[:MAX_LESSON_PLAN_STEPS]

    raw_reflection = data.get("reflection")
    raw_reflection = raw_reflection if isinstance(raw_reflection, dict) else {}
    went_well = str(raw_reflection.get("went_well", "")).strip()[:400]
    change_next_time = str(raw_reflection.get("change_next_time", "")).strip()[:400]
    reflection = {
        "went_well": went_well or (
            f"Trainees engaging hands-on with \"{outcome_text.strip()[:80]}\" through the "
            "planned demonstration and guided practice."
        ),
        "change_next_time": change_next_time or (
            "Watch the pacing of the guided-practice step and be ready to extend it "
            "if trainees need more time to master the skill."
        ),
    }

    # --------------------------------------------------
    # 6. Return success
    # --------------------------------------------------
    return JsonResponse({
        "objectives": objectives,
        "facilitation_techniques": facilitation_techniques,
        "steps": steps,
        "reflection": reflection,
    })
