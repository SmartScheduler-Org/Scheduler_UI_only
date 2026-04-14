from django.contrib import admin
from.models import *

@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("section_id", "department")
    list_filter = ("department",)
    search_fields = ("section_id",)
    filter_horizontal = ("allowed_courses",)   # ⭐ nice multi-select widget

# (register others as usual)
admin.site.register(Department)
admin.site.register(Course)
admin.site.register(Room)
admin.site.register(Instructor)
admin.site.register(MeetingTime)
admin.site.register(SavedTimetable)
admin.site.register(ScheduledSlot)

from .models import TeacherPreference

@admin.register(TeacherPreference)
class TeacherPreferenceAdmin(admin.ModelAdmin):
    list_display  = ('name', 'email', 'designation', 'submitted_at')
    list_filter   = ('designation',)
    search_fields = ('name', 'email')
    readonly_fields = ('submitted_at',)
