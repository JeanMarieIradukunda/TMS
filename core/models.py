from django.db import models


class Logo(models.Model):
    name = models.CharField(max_length=100)
    # Stored as a base64 data-URI string (see core/forms.py:encode_image_to_base64),
    # NOT as an uploaded file on disk. This must stay a TextField: an ImageField's
    # underlying DB column defaults to varchar(100), which silently works on SQLite
    # (no length enforcement) but raises "value too long for type character
    # varying(100)" on PostgreSQL as soon as a real base64 image is saved. Storing
    # the image as text also means logo uploads work correctly on Vercel, whose
    # serverless filesystem is ephemeral and cannot persist uploaded files.
    image = models.TextField(help_text='Base64 data-URI string of the logo image')

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

    class Meta:
        ordering = ['mod_code']

    def __str__(self):
        return f"{self.mod_code} - {self.mod_name}"


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