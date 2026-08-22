from django.contrib import admin
from .models import (
    Logo, Sector, Trade, Level, TradeLevel, Trainer,
    Module, LearningOutcome, IndicativeContent, LessonPlan, AssessmentPlan,
)


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ('id', 'sector_name')
    search_fields = ('sector_name',)


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ('id', 'trade_name', 'sector')
    list_filter = ('sector',)
    search_fields = ('trade_name',)


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ('id', 'class_level')
    search_fields = ('class_level',)


@admin.register(TradeLevel)
class TradeLevelAdmin(admin.ModelAdmin):
    list_display = ('id', 'trade', 'level')
    list_filter = ('level',)


@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = ('id', 'fname', 'lname', 'username')
    search_fields = ('fname', 'lname', 'username')


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'mod_code', 'mod_name', 'trade', 'level', 'trainer',
        'learning_hours', 'term', 'num_terms', 'term_weeks', 'is_active',
    )
    list_filter = ('trade', 'level', 'term', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('mod_code', 'mod_name')
    fields = (
        'trade', 'level', 'trainer', 'mod_code', 'mod_name',
        'learning_hours', 'term', 'num_terms', 'term_weeks', 'is_active',
    )


@admin.register(LearningOutcome)
class LearningOutcomeAdmin(admin.ModelAdmin):
    list_display = ('id', 'module', 'outcome_text', 'learning_hours')
    list_filter = ('module',)


@admin.register(IndicativeContent)
class IndicativeContentAdmin(admin.ModelAdmin):
    list_display = ('id', 'outcome', 'indic_name')


@admin.register(Logo)
class LogoAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')


@admin.register(LessonPlan)
class LessonPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'module', 'trainer', 'week', 'lesson_date')
    list_filter = ('module', 'trainer')
    search_fields = ('title',)


@admin.register(AssessmentPlan)
class AssessmentPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'module', 'trainer', 'assessment_type', 'assessment_date', 'num_candidates')
    list_filter = ('module', 'trainer', 'assessment_type')
    search_fields = ('module__mod_code', 'module__mod_name')
