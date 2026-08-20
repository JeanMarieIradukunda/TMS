from django.db import models
from django.contrib.auth.models import User


class Sector(models.Model):
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Trade(models.Model):
    sector = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name='trades')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Level(models.Model):
    name = models.CharField(max_length=100)  # e.g., "Level 3", "Level 4"
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class TradeLevel(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name='trade_levels')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='trade_levels')

    class Meta:
        unique_together = ('trade', 'level')

    def __str__(self):
        return f"{self.trade.code} ({self.level.name})"


class Trainer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='trainer_profile', null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    specialization = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Module(models.Model):
    trade_level = models.ForeignKey(TradeLevel, on_delete=models.CASCADE, related_name='modules')
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, blank=True, related_name='modules')
    code = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=255)
    credits = models.PositiveIntegerField(default=10)
    num_terms = models.PositiveIntegerField(default=3, help_description="Number of terms for this module")
    term_weeks = models.CharField(max_length=100, default="10,10,10", help_text="Comma-separated weeks per term, e.g. '10,10,10'")
    is_active = models.BooleanField(default=True, help_text="Uncheck to hide this module from generation")
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.code}: {self.title}"

    @property
    def total_hours(self):
        return self.credits * 10


class LearningOutcome(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='learning_outcomes')
    code = models.CharField(max_length=50)  # e.g., "LO1", "LO2"
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='approved')
    review_note = models.TextField(blank=True)

    class Meta:
        unique_together = ('module', 'code')

    def __str__(self):
        return f"{self.module.code} - {self.code}"


class IndicativeContent(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    learning_outcome = models.ForeignKey(LearningOutcome, on_delete=models.CASCADE, related_name='indicative_contents')
    code = models.CharField(max_length=50, blank=True)  # e.g., "IC1.1"
    topic = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='approved')
    review_note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.learning_outcome} - {self.topic}"


class LessonPlan(models.Model):
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name='lesson_plans')
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='lesson_plans')
    learning_outcome = models.ForeignKey(LearningOutcome, on_delete=models.CASCADE, related_name='lesson_plans')
    indicative_content = models.ForeignKey(IndicativeContent, on_delete=models.CASCADE, related_name='lesson_plans', null=True, blank=True)

    week_number = models.PositiveIntegerField()
    term_number = models.PositiveIntegerField(default=1)
    duration_hours = models.DecimalField(max_digits=4, decimal_places=1, default=1.0)

    topic = models.CharField(max_length=255)
    introduction = models.TextField(blank=True)
    presentation = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['term_number', 'week_number', 'id']

    def __str__(self):
        return f"T{self.term_number}W{self.week_number} - {self.topic}"
