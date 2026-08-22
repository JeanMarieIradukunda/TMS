from django.conf import settings
from django.db import models


class Logo(models.Model):
    name = models.CharField(max_length=100)
    image = models.TextField(help_text='Base64 string or image URL')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Sector(models.Model):
    sector_name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['sector_name']

    def __str__(self):
        return self.sector_name


class Trade(models.Model):
    sector = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name='trades')
    trade_name = models.CharField(max_length=150)

    class Meta:
        ordering = ['trade_name']

    def __str__(self):
        return self.trade_name


class Level(models.Model):
    class_level = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ['class_level']

    def __str__(self):
        return self.class_level


class TradeLevel(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name='trade_levels')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='trade_levels')

    class Meta:
        unique_together = ('trade', 'level')
        ordering = ['trade__trade_name', 'level__class_level']

    def __str__(self):
        return f"{self.trade.trade_name} - {self.level.class_level}"


class Trainer(models.Model):
    # Links this trainer record to a real Django login account so trainers
    # can sign in through the existing admin login page/Dashboard. Optional
    # (null=True) so trainer records with no login access yet don't break.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='trainer_profile',
        help_text="The login account this trainer uses to sign in. "
                  "Leave blank if this trainer doesn't need portal access.",
    )

    fname = models.CharField(max_length=100)
    lname = models.CharField(max_length=100)
    username = models.CharField(max_length=100, unique=True)
    password_hash = models.TextField()

    class Meta:
        ordering = ['lname', 'fname']

    def __str__(self):
        return f"{self.fname} {self.lname}"

    @property
    def full_name(self):
        return f"{self.fname} {self.lname}"


class Module(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name='modules')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='modules')
    trainer = models.ForeignKey(Trainer, null=True, blank=True, on_delete=models.SET_NULL, related_name='modules')

    mod_code = models.CharField(max_length=50, unique=True)
    mod_name = models.CharField(max_length=150)
    learning_hours = models.IntegerField()
    term = models.CharField(max_length=50)

    # ------------------------------------------------------------------
    # Scheme of Work term/week structure for this module. These drive the
    # Scheme of Work generator's "Number of terms" and "Weeks per term"
    # fields so they're loaded from the module's own record instead of
    # defaulting to a hardcoded assumption (e.g. always 3 terms).
    # ------------------------------------------------------------------
    num_terms = models.PositiveSmallIntegerField(
        default=1,
        help_text="How many terms this module's Scheme of Work is split across.",
    )
    term_weeks = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Comma-separated number of weeks for each term, in order, e.g. "
            "'12,12,10' for a 3-term module where the last term is shorter. "
            "Leave blank to split evenly (12 weeks per term by default)."
        ),
    )

    # ------------------------------------------------------------------
    # Lock/unlock switch. When unchecked, the module is hidden from the
    # public Scheme of Work / Lesson Plan generators (it simply won't
    # appear in their dropdowns), effectively blocking its usage without
    # deleting any of its data. Admin CRUD screens still show and allow
    # editing locked modules so an admin can fix and re-enable them.
    # ------------------------------------------------------------------
    is_active = models.BooleanField(
        default=True,
        help_text="Unlocked (usable) modules appear in the public generators. "
                   "Lock a module to block it from being used there.",
    )

    class Meta:
        ordering = ['mod_code']
        permissions = [
            ("toggle_module_status", "Can lock/unlock module usage"),
        ]

    def __str__(self):
        return f"{self.mod_code} - {self.mod_name}"

    def get_term_weeks_list(self):
        """
        Resolves this module's per-term week counts into a clean list of
        positive integers, one entry per term (length == self.num_terms),
        regardless of whether `term_weeks` is blank, malformed, or has too
        few/many values compared to `num_terms`:

        - Blank/invalid            -> defaults every term to 12 weeks.
        - Fewer entries than terms -> pads using the last given value.
        - More entries than terms  -> truncates to num_terms.
        """
        n = max(1, self.num_terms or 1)
        weeks = []
        if self.term_weeks:
            for part in self.term_weeks.split(','):
                part = part.strip()
                if part.isdigit() and int(part) > 0:
                    weeks.append(int(part))

        if not weeks:
            return [12] * n
        if len(weeks) < n:
            weeks = weeks + [weeks[-1]] * (n - len(weeks))
        return weeks[:n]


class LearningOutcome(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='learning_outcomes')
    outcome_text = models.TextField()
    learning_hours = models.IntegerField()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.outcome_text[:60]


class IndicativeContent(models.Model):
    outcome = models.ForeignKey(LearningOutcome, on_delete=models.CASCADE, related_name='indicative_contents')
    indic_name = models.TextField()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.indic_name[:60]


class LessonPlan(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lesson_plans')
    trainer = models.ForeignKey(Trainer, null=True, blank=True, on_delete=models.SET_NULL, related_name='lesson_plans')

    title = models.CharField(max_length=200)
    week = models.CharField(max_length=50, blank=True)
    lesson_date = models.DateField(null=True, blank=True)
    objectives = models.TextField(blank=True)
    activities = models.TextField(blank=True)
    resources = models.TextField(blank=True)

    class Meta:
        ordering = ['-lesson_date', 'title']

    def __str__(self):
        return self.title


class AssessmentPlan(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='assessment_plans')
    learning_outcome = models.ForeignKey(
        LearningOutcome, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assessment_plans'
    )
    trainer = models.ForeignKey(Trainer, null=True, blank=True, on_delete=models.SET_NULL, related_name='assessment_plans')

    MODULE_TYPE_CHOICES = [('core', 'Core'), ('optional', 'Optional'), ('elective', 'Elective')]
    ASSESSMENT_TYPE_CHOICES = [
        ('written', 'Written assessment'),
        ('oral', 'Oral assessment'),
        ('practical', 'Practical assessment'),
        ('assignment', 'Assignment'),
    ]

    module_type = models.CharField(max_length=20, choices=MODULE_TYPE_CHOICES, blank=True)
    assessment_type = models.CharField(max_length=20, choices=ASSESSMENT_TYPE_CHOICES, blank=True)
    num_candidates = models.PositiveIntegerField(default=0)
    num_invigilators = models.PositiveIntegerField(default=0)
    assessment_date = models.DateField(null=True, blank=True)
    resources = models.TextField(blank=True)
    place = models.CharField(max_length=150, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    observation = models.TextField(blank=True)

    class Meta:
        ordering = ['-assessment_date', 'module__mod_code']

    def __str__(self):
        return f"{self.module.mod_code} assessment plan"
