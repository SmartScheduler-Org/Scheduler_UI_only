from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.models import Profile, TeacherOnboarding


class TeacherOnboardingFlowTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.teacher = self.user_model.objects.create_user(
            username="teacheruser",
            password="testpass123",
            email="teacher@example.com",
        )
        self.teacher_profile = Profile.objects.get(user=self.teacher)
        self.teacher_profile.role = "teacher"
        self.teacher_profile.save(update_fields=["role"])

        self.hod = self.user_model.objects.create_user(
            username="hoduser",
            password="testpass123",
            email="hod@example.com",
        )
        self.hod_profile = Profile.objects.get(user=self.hod)
        self.hod_profile.role = "hod"
        self.hod_profile.save(update_fields=["role"])

    def test_teacher_dashboard_redirects_to_registration_without_onboarding_gate(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("teacher_dashboard"))

        self.assertRedirects(response, reverse("teacher_register"))

    def test_teacher_onboarding_url_redirects_to_dashboard(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("teacher_onboarding"), follow=True)

        self.assertRedirects(response, reverse("teacher_register"))

    def test_hod_can_view_and_export_teacher_onboarding_submissions(self):
        TeacherOnboarding.objects.create(
            user=self.teacher,
            full_name="Teacher User",
            designation="Professor",
            joining_year=2019,
            email="teacher@example.com",
            subjects_taught="AI, ML",
        )
        self.client.force_login(self.hod)

        response = self.client.get(reverse("teacher_onboarding_responses"))
        export_response = self.client.get(reverse("export_teacher_onboarding_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Teacher User")
        self.assertEqual(export_response.status_code, 200)
        self.assertContains(export_response, "Teacher User")
        self.assertContains(export_response, "AI, ML")

    def test_hod_can_request_resubmission_without_blocking_teacher_dashboard(self):
        submission = TeacherOnboarding.objects.create(
            user=self.teacher,
            full_name="Teacher User",
            designation="Professor",
            joining_year=2019,
            email="teacher@example.com",
            subjects_taught="AI, ML",
        )
        self.client.force_login(self.hod)

        response = self.client.post(
            reverse("request_teacher_onboarding_resubmission", args=[submission.id])
        )

        self.assertRedirects(response, reverse("teacher_onboarding_responses"))
        submission.refresh_from_db()
        self.assertTrue(submission.requires_resubmission)

        self.client.force_login(self.teacher)
        dashboard_response = self.client.get(reverse("teacher_dashboard"))
        self.assertRedirects(dashboard_response, reverse("teacher_register"))

    def test_hod_can_delete_teacher_onboarding_submission(self):
        submission = TeacherOnboarding.objects.create(
            user=self.teacher,
            full_name="Teacher User",
            designation="Professor",
            joining_year=2019,
            email="teacher@example.com",
            subjects_taught="AI, ML",
        )
        self.client.force_login(self.hod)

        response = self.client.post(
            reverse("delete_teacher_onboarding", args=[submission.id])
        )

        self.assertRedirects(response, reverse("teacher_onboarding_responses"))
        self.assertFalse(TeacherOnboarding.objects.filter(id=submission.id).exists())
