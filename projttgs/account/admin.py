from django.contrib import admin

from .models import Profile, TeacherOnboarding


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "contact_number", "linked_instructor", "active_timetable")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email", "contact_number")


@admin.register(TeacherOnboarding)
class TeacherOnboardingAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "designation", "joining_year", "email", "submitted_at")
    list_filter = ("designation", "joining_year", "submitted_at")
    search_fields = ("full_name", "user__username", "email", "subjects_taught")
