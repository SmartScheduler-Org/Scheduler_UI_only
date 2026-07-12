import json
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.messages import get_messages
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from . import views
from . import views_other
from .models import (
    Subject,
    Department,
    Instructor,
    LiveTimetable,
    MeetingTime,
    Room,
    Section,
    SectionSubjectInstructor,
    SectionSubjectMapping,
    SavedTimetable,
    ScheduledSlot,
    SavedParkingSlot,
    SavedSlotRoomReservation,
)


class SchedulerInitializationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="scheduler_test",
            password="testpass123",
        )

        self.department = Department.objects.create(user=self.user)

        Room.objects.create(
            r_number="LH-1",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        Room.objects.create(
            r_number="LAB-1",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            user=self.user,
        )

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            for slot in ["1", "2", "3", "4", "6", "7", "8", "9"]:
                MeetingTime.objects.create(
                    pid=f"{day[:2]}{slot}",
                    day=day,
                    time=slot,
                    user=self.user,
                )

        self.section = Section.objects.create(
            section_id="Test Section",
            department=self.department,
            user=self.user,
        )

        theory_loads = [2, 2, 2, 2, 1]
        for index, classes_per_week in enumerate(theory_loads, start=1):
            instructor = Instructor.objects.create(
                uid=f"T{index:03d}",
                name=f"Theory Teacher {index}",
                designation="Assistant Professor",
                max_workload=25,
                user=self.user,
            )
            subject = Subject.objects.create(
                subject_number=f"TH{index:03d}",
                subject_name=f"Theory {index}",
                department=self.department,
                max_numb_students=60,
                room_required="Lecture Hall",
                classes_per_week=classes_per_week,
                user=self.user,
            )
            subject.instructors.add(instructor)
            self.section.allowed_subjects.add(subject)

        lab_instructor = Instructor.objects.create(
            uid="L001",
            name="Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        lab_subject = Subject.objects.create(
            subject_number="LAB001",
            subject_name="Solo Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            classes_per_week=1,
            user=self.user,
        )
        lab_subject.instructors.add(lab_instructor)
        self.section.allowed_subjects.add(lab_subject)

    def test_initialize_schedules_theory_even_when_lab_uses_part_of_day(self):
        with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views_other, "COMPACT_SECTIONS", {}
        ):
            views_other.data = views_other.Data()
            schedule = views_other.Schedule().initialize()

        theory_classes = [cls for cls in schedule.get_classes() if cls.section == "Test Section"]
        self.assertEqual(len(theory_classes), 9)
        self.assertTrue({cls.meeting_time.day for cls in theory_classes})

    def test_prefilled_theory_counts_toward_required_occurrences(self):
        subject = self.section.allowed_subjects.get(subject_number="TH001")
        teacher = subject.instructors.first()
        room = Room.objects.get(r_number="LH-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")

        locked = views_other.Class(900, self.department, self.section.section_id, subject)
        locked.set_instructor(teacher)
        locked.set_room(room)
        locked.set_meetingTime(monday_1)
        locked.meeting_times = [monday_1]
        locked.duration = 1
        locked.prefill_locked = True

        original_classes = getattr(views_other, "PREFILLED_LOCKED_CLASSES", [])
        original_labs = getattr(views_other, "PREFILLED_LOCKED_LABS", [])
        try:
            views_other.PREFILLED_LOCKED_CLASSES = [locked]
            views_other.PREFILLED_LOCKED_LABS = []
            with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
                views_other, "COMPACT_SECTIONS", {}
            ):
                views_other.data = views_other.Data()
                schedule = views_other.Schedule().initialize()
        finally:
            views_other.PREFILLED_LOCKED_CLASSES = original_classes
            views_other.PREFILLED_LOCKED_LABS = original_labs

        theory_classes = [cls for cls in schedule.get_classes() if cls.section == "Test Section"]
        subject_classes = [cls for cls in theory_classes if cls.subject == subject]

        self.assertEqual(len(theory_classes), 9)
        self.assertEqual(len(subject_classes), 2)

    def test_prefilled_lab_counts_toward_required_occurrences(self):
        subject = self.section.allowed_subjects.get(subject_number="LAB001")
        teacher = subject.instructors.first()
        room = Room.objects.get(r_number="LAB-1")
        block = [
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ]

        locked = views_other.Lab(901, self.department, self.section.section_id, subject, batch=1, total_batches=1)
        locked.set_instructor(teacher)
        locked.set_room(room)
        locked.set_meetingTimes(block)
        locked.duration = 4
        locked.prefill_locked = True

        original_classes = getattr(views_other, "PREFILLED_LOCKED_CLASSES", [])
        original_labs = getattr(views_other, "PREFILLED_LOCKED_LABS", [])
        try:
            views_other.PREFILLED_LOCKED_CLASSES = []
            views_other.PREFILLED_LOCKED_LABS = [locked]
            with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
                views_other, "COMPACT_SECTIONS", {}
            ):
                views_other.data = views_other.Data()
                schedule = views_other.Schedule().initialize()
        finally:
            views_other.PREFILLED_LOCKED_CLASSES = original_classes
            views_other.PREFILLED_LOCKED_LABS = original_labs

        labs = [lab for lab in schedule.get_labs() if lab.section == "Test Section" and lab.subject == subject]
        self.assertEqual(len(labs), 1)

    def test_lab_conflict_detection_blocks_overlapping_slots_for_same_room(self):
        second_lab_room = Room.objects.create(
            r_number="LAB-2",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            user=self.user,
        )
        second_lab_instructor = Instructor.objects.create(
            uid="L002",
            name="Second Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        existing_lab = views_other.Lab(
            1,
            self.department,
            self.section.section_id,
            self.section.allowed_subjects.get(subject_number="LAB001"),
        )
        existing_lab.group = "Batch-1"
        existing_lab.set_instructor(self.section.allowed_subjects.get(subject_number="LAB001").instructors.first())
        existing_lab.set_room(Room.objects.get(r_number="LAB-1"))
        existing_lab.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
        ])
        schedule._labs = [existing_lab]

        blocked_same_room = schedule._conflicts_if_assign_lab(
            [MeetingTime.objects.get(pid="Mo2"), MeetingTime.objects.get(pid="Mo3")],
            Room.objects.get(r_number="LAB-1"),
            second_lab_instructor,
            "Other Section",
            group="Batch-2",
            max_parallel=1,
        )
        allowed_other_room = schedule._conflicts_if_assign_lab(
            [MeetingTime.objects.get(pid="Mo2"), MeetingTime.objects.get(pid="Mo3")],
            second_lab_room,
            second_lab_instructor,
            "Other Section",
            group="Batch-2",
            max_parallel=1,
        )

        self.assertTrue(blocked_same_room)
        self.assertFalse(allowed_other_room)

    def test_compute_real_metrics_handles_empty_schedule(self):
        teacher_load, resource_util, student_load = views_other.compute_real_metrics([], [])

        self.assertEqual(teacher_load, 5)
        self.assertEqual(resource_util, 0)
        self.assertEqual(student_load, 5)

    def test_build_section_tables_includes_subject_counts(self):
        theory_subjects = list(self.section.allowed_subjects.filter(room_required="Lecture Hall").order_by("subject_number"))
        lab_subject = self.section.allowed_subjects.get(room_required="Lab")
        teacher = theory_subjects[0].instructors.first()
        room = Room.objects.get(r_number="LH-1")
        lab_room = Room.objects.get(r_number="LAB-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")
        monday_2 = MeetingTime.objects.get(pid="Mo2")
        tuesday_1 = MeetingTime.objects.get(pid="Tu1")

        cls1 = views_other.Class(1, self.department, self.section.section_id, theory_subjects[0])
        cls1.set_instructor(teacher)
        cls1.set_room(room)
        cls1.set_meetingTime(monday_1)

        cls2 = views_other.Class(2, self.department, self.section.section_id, theory_subjects[0])
        cls2.set_instructor(teacher)
        cls2.set_room(room)
        cls2.set_meetingTime(monday_2)

        cls3 = views_other.Class(3, self.department, self.section.section_id, theory_subjects[1])
        cls3.set_instructor(theory_subjects[1].instructors.first())
        cls3.set_room(room)
        cls3.set_meetingTime(tuesday_1)

        lab = views_other.Lab(4, self.department, self.section.section_id, lab_subject)
        lab.set_instructor(lab_subject.instructors.first())
        lab.set_room(lab_room)
        lab.set_meetingTimes([
            monday_1,
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])

        views_other.data = views_other.Data()
        tables = views_other.build_section_tables([cls1, cls2, cls3], [lab])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")

        compact_subject_counts = [
            {
                "name": subject["name"],
                "count": subject["count"],
                "required": subject["required"],
                "missing": subject["missing"],
                "is_lab": subject["is_lab"],
            }
            for subject in test_table["subject_counts"]
        ]
        self.assertEqual(compact_subject_counts, [
            {"name": "Solo Lab", "count": 1, "required": 1, "missing": 0, "is_lab": True},
            {"name": "Theory 1", "count": 2, "required": 2, "missing": 0, "is_lab": False},
            {"name": "Theory 2", "count": 1, "required": 2, "missing": 1, "is_lab": False},
            {"name": "Theory 3", "count": 0, "required": 2, "missing": 2, "is_lab": False},
            {"name": "Theory 4", "count": 0, "required": 2, "missing": 2, "is_lab": False},
            {"name": "Theory 5", "count": 0, "required": 1, "missing": 1, "is_lab": False},
        ])

    def test_build_section_tables_excludes_manual_unknown_subject_from_missing_counts(self):
        teacher = self.section.allowed_subjects.filter(room_required="Lecture Hall").first().instructors.first()
        room = Room.objects.get(r_number="LH-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")
        manual_subject = views_other.ManualPrefillSubject("Manual Workshop", duration=4)

        manual_class = views_other.Class(99, self.department, self.section.section_id, manual_subject)
        manual_class.set_instructor(teacher)
        manual_class.set_room(room)
        manual_class.set_meetingTime(monday_1)
        manual_class.meeting_times = [
            monday_1,
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ]
        manual_class.duration = 4
        manual_class.manual_entry = True

        tables = views_other.build_section_tables([manual_class], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")

        self.assertNotIn("Manual Workshop", [subject["name"] for subject in test_table["subject_counts"]])
        self.assertNotIn("Manual Workshop", [lab["name"] for lab in test_table["missed_labs"]])
        self.assertEqual(test_table["total_missing_classes"], sum(subject["missing"] for subject in test_table["subject_counts"]))

    def test_prefill_restore_lab_keeps_slot_when_room_is_blank(self):
        entry = {
            "section_id": self.section.section_id,
            "subject_text": "Solo Lab",
            "teacher_uid": "L001",
            "second_teacher_uid": "",
            "co_teacher_uids": [],
            "room_number": "",
            "day": "Monday",
            "start_slot": "1",
            "duration": "4",
            "manual_entry": True,
            "manual_slot_uid": "prefill-lab-1",
            "prefill_locked": True,
            "batch": 1,
            "total_batches": 1,
        }

        restored = views_other._prefill_restore_lab(entry, self.user)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.section, self.section.section_id)
        self.assertEqual(getattr(restored, "room", None), None)
        self.assertEqual(len(getattr(restored, "meeting_times", []) or []), 4)

    def test_prefill_restore_lab_uses_placeholder_teacher_and_room_when_missing(self):
        entry = {
            "section_id": self.section.section_id,
            "subject_text": "Solo Lab",
            "teacher_uid": "Missing Teacher",
            "second_teacher_uid": "",
            "co_teacher_uids": [],
            "room_number": "Missing Lab",
            "day": "Monday",
            "start_slot": "1",
            "duration": "4",
            "manual_entry": True,
            "manual_slot_uid": "prefill-lab-2",
            "prefill_locked": True,
            "batch": 1,
            "total_batches": 1,
        }

        restored = views_other._prefill_restore_lab(entry, self.user)

        self.assertIsNotNone(restored)
        self.assertEqual(getattr(restored.instructor, "uid", ""), "Missing Teacher")
        self.assertEqual(getattr(restored.instructor, "name", ""), "Missing Teacher")
        self.assertEqual(getattr(restored.room, "r_number", ""), "Missing Lab")
        self.assertEqual(getattr(restored.room, "room_type", ""), "Lab")

    def test_build_section_tables_lists_missed_labs(self):
        extra_lab_subject = Subject.objects.create(
            subject_number="LAB002",
            subject_name="Missed Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="ADVANCED",
            classes_per_week=1,
            user=self.user,
        )
        self.assertEqual(test_table["total_missing_classes"], 6)

    def test_build_section_tables_includes_missing_reason(self):
        subject = Subject.objects.create(
            subject_number="TH999",
            subject_name="Unmapped Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        self.section.allowed_subjects.add(subject)

        views_other.data = views_other.Data()
        tables = views_other.build_section_tables([], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")
        subject = next(subject for subject in test_table["subject_counts"] if subject["name"] == "Unmapped Theory")

        self.assertEqual(subject["unfulfilled"], 3)
        self.assertEqual(subject["reason"], "Teacher not mapped")

    def test_get_section_load_rule_does_not_cap_theory_below_subject_demand(self):
        with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (3, 0)}):
            theory_limit, lab_slots = views_other.get_section_load_rule(self.section)

        self.assertEqual(theory_limit, 9)
        self.assertEqual(lab_slots, 1)

    def test_build_section_tables_includes_manual_add_suggestions_for_missed_lecture(self):
        views_other.data = views_other.Data()
        tables = views_other.build_section_tables([], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")
        subject = next(subject for subject in test_table["subject_counts"] if subject["name"] == "Theory 1")

        self.assertGreater(subject["unfulfilled"], 0)
        self.assertTrue(subject["suggested_slots"])

    def test_initialize_keeps_same_teacher_for_section_subject_pair(self):
        subject = self.section.allowed_subjects.filter(room_required="Lecture Hall").order_by("subject_number").first()
        primary = Instructor.objects.create(
            uid="FX001",
            name="Fixed Teacher",
            designation="Assistant Professor",
            max_workload=1,
            user=self.user,
        )
        backup = Instructor.objects.create(
            uid="FX002",
            name="Backup Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject.instructors.clear()
        subject.instructors.add(primary, backup)

        with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views_other, "COMPACT_SECTIONS", {}
        ):
            views_other.data = views_other.Data()
            schedule = views_other.Schedule().initialize()

        subject_classes = [
            cls for cls in schedule.get_classes()
            if cls.section == "Test Section" and cls.subject.subject_number == subject.subject_number
        ]

        assigned_teachers = {cls.instructor.uid for cls in subject_classes}
        self.assertLessEqual(len(assigned_teachers), 1)

    def test_crossover_keeps_same_teacher_for_section_subject_pair(self):
        subject = self.section.allowed_subjects.filter(room_required="Lecture Hall").order_by("subject_number").first()
        teacher_one = Instructor.objects.create(
            uid="CX001",
            name="Crossover Teacher 1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        teacher_two = Instructor.objects.create(
            uid="CX002",
            name="Crossover Teacher 2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        room = Room.objects.get(r_number="LH-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")
        monday_2 = MeetingTime.objects.get(pid="Mo2")

        views_other.data = views_other.Data()
        s1 = views_other.Schedule()
        c1 = views_other.Class(1, self.department, self.section.section_id, subject)
        c1.set_instructor(teacher_one)
        c1.set_room(room)
        c1.set_meetingTime(monday_1)
        s1._classes = [c1]
        s1._instructor_fixed[(self.section.section_id, subject.pk)] = teacher_one

        s2 = views_other.Schedule()
        c2 = views_other.Class(2, self.department, self.section.section_id, subject)
        c2.set_instructor(teacher_two)
        c2.set_room(room)
        c2.set_meetingTime(monday_2)
        s2._classes = [c2]
        s2._instructor_fixed[(self.section.section_id, subject.pk)] = teacher_two

        child = views_other.GeneticAlgorithm()._crossover(s1, s2)

        assigned_teachers = {
            cls.instructor.uid
            for cls in child.get_classes()
            if cls.section == self.section.section_id and cls.subject.subject_number == subject.subject_number
        }
        self.assertLessEqual(len(assigned_teachers), 1)

    def test_crossover_skips_conflicting_lab_groups_from_parents(self):
        other_section = Section.objects.create(
            section_id="Other Section",
            department=self.department,
            user=self.user,
        )
        lab_subject = self.section.allowed_subjects.get(subject_number="LAB001")
        other_section.allowed_subjects.add(lab_subject)
        teacher = lab_subject.instructors.first()
        room = Room.objects.get(r_number="LAB-1")

        views_other.data = views_other.Data()
        s1 = views_other.Schedule()
        lab1 = views_other.Lab(1, self.department, self.section.section_id, lab_subject)
        lab1.group = "Solo"
        lab1.set_instructor(teacher)
        lab1.set_room(room)
        lab1.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])
        s1._labs = [lab1]

        s2 = views_other.Schedule()
        lab2 = views_other.Lab(2, self.department, other_section.section_id, lab_subject)
        lab2.group = "Solo"
        lab2.set_instructor(teacher)
        lab2.set_room(room)
        lab2.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])
        s2._labs = [lab2]

        child = views_other.GeneticAlgorithm()._crossover(s1, s2)

        self.assertEqual(len(child.get_labs()), 1)
        self.assertIn(child.get_labs()[0].section, {self.section.section_id, other_section.section_id})

    def test_group_parallel_classes_keeps_mirrored_electives_together(self):
        linked_section = Section.objects.create(
            section_id="Elective Linked",
            department=self.department,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="ELC001",
            name="Elective Mirror Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="ELCX01",
            subject_name="Mirrored Elective",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        room = Room.objects.get(r_number="LH-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        class_a = views_other.Class(1, self.department, self.section.section_id, subject)
        class_a.set_instructor(teacher)
        class_a.set_room(room)
        class_a.set_meetingTime(monday_1)
        class_a.is_elective = True
        class_a.elective_sections = [self.section.section_id, linked_section.section_id]

        class_b = views_other.Class(2, self.department, linked_section.section_id, subject)
        class_b.set_instructor(teacher)
        class_b.set_room(room)
        class_b.set_meetingTime(monday_1)
        class_b.is_elective = True
        class_b.elective_sections = [self.section.section_id, linked_section.section_id]

        grouped = schedule._group_parallel_classes([class_a, class_b])

        self.assertEqual(len(grouped), 1)
        self.assertEqual({cls.section for cls in next(iter(grouped.values()))}, {self.section.section_id, linked_section.section_id})

    def test_fitness_prefers_packed_lab_room_utilization(self):
        second_lab_room = Room.objects.create(
            r_number="LAB-2",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            user=self.user,
        )
        views_other.data = views_other.Data()

        packed = views_other.Schedule()
        fragmented = views_other.Schedule()
        lab_subject = self.section.allowed_subjects.get(subject_number="LAB001")
        teacher = lab_subject.instructors.first()
        lab_room = Room.objects.get(r_number="LAB-1")

        packed_lab_1 = views_other.Lab(1, self.department, self.section.section_id, lab_subject)
        packed_lab_1.group = "Solo-1"
        packed_lab_1.set_instructor(teacher)
        packed_lab_1.set_room(lab_room)
        packed_lab_1.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])
        packed_lab_2 = views_other.Lab(2, self.department, self.section.section_id, lab_subject)
        packed_lab_2.group = "Solo-2"
        packed_lab_2.set_instructor(teacher)
        packed_lab_2.set_room(lab_room)
        packed_lab_2.set_meetingTimes([
            MeetingTime.objects.get(pid="Tu1"),
            MeetingTime.objects.get(pid="Tu2"),
            MeetingTime.objects.get(pid="Tu3"),
            MeetingTime.objects.get(pid="Tu4"),
        ])
        packed._labs = [packed_lab_1, packed_lab_2]

        fragmented_lab_1 = views_other.Lab(3, self.department, self.section.section_id, lab_subject)
        fragmented_lab_1.group = "Solo-1"
        fragmented_lab_1.set_instructor(teacher)
        fragmented_lab_1.set_room(lab_room)
        fragmented_lab_1.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])
        fragmented_lab_2 = views_other.Lab(4, self.department, self.section.section_id, lab_subject)
        fragmented_lab_2.group = "Solo-2"
        fragmented_lab_2.set_instructor(teacher)
        fragmented_lab_2.set_room(second_lab_room)
        fragmented_lab_2.set_meetingTimes([
            MeetingTime.objects.get(pid="Tu1"),
            MeetingTime.objects.get(pid="Tu2"),
            MeetingTime.objects.get(pid="Tu3"),
            MeetingTime.objects.get(pid="Tu4"),
        ])
        fragmented._labs = [fragmented_lab_1, fragmented_lab_2]

        self.assertGreater(packed.get_fitness(), fragmented.get_fitness())

    def test_compact_lab_room_utilization_moves_low_usage_lab_to_better_used_room(self):
        second_lab_room = Room.objects.create(
            r_number="LAB-2",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            user=self.user,
        )
        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        lab_subject = self.section.allowed_subjects.get(subject_number="LAB001")
        teacher = lab_subject.instructors.first()
        lab_room = Room.objects.get(r_number="LAB-1")

        lab1 = views_other.Lab(1, self.department, self.section.section_id, lab_subject)
        lab1.group = "Solo-1"
        lab1.set_instructor(teacher)
        lab1.set_room(lab_room)
        lab1.set_meetingTimes([
            MeetingTime.objects.get(pid="Mo1"),
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])

        lab2 = views_other.Lab(2, self.department, self.section.section_id, lab_subject)
        lab2.group = "Solo-2"
        lab2.set_instructor(teacher)
        lab2.set_room(lab_room)
        lab2.set_meetingTimes([
            MeetingTime.objects.get(pid="We1"),
            MeetingTime.objects.get(pid="We2"),
            MeetingTime.objects.get(pid="We3"),
            MeetingTime.objects.get(pid="We4"),
        ])

        lab3 = views_other.Lab(3, self.department, self.section.section_id, lab_subject)
        lab3.group = "Solo-3"
        lab3.set_instructor(teacher)
        lab3.set_room(second_lab_room)
        lab3.set_meetingTimes([
            MeetingTime.objects.get(pid="Tu1"),
            MeetingTime.objects.get(pid="Tu2"),
            MeetingTime.objects.get(pid="Tu3"),
            MeetingTime.objects.get(pid="Tu4"),
        ])

        schedule._labs = [lab1, lab2, lab3]

        moved = schedule._compact_lab_room_utilization()

        self.assertTrue(moved)
        self.assertEqual(lab3.room.r_number, "LAB-1")

    def test_initialize_keeps_same_room_within_half_day_block(self):
        with patch.object(views_other, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views_other, "COMPACT_SECTIONS", {}
        ):
            views_other.data = views_other.Data()
            schedule = views_other.Schedule().initialize()

        rooms_by_block = {}
        for cls in schedule.get_classes():
            if cls.section != "Test Section" or not cls.meeting_time or not cls.room:
                continue
            block = "pre_lunch" if int(cls.meeting_time.time) < int(views_other.LUNCH_SLOT) else "post_lunch"
            key = (cls.section, cls.meeting_time.day, block)
            rooms_by_block.setdefault(key, set()).add(cls.room.r_number)

        self.assertTrue(rooms_by_block)
        self.assertTrue(all(len(rooms) <= 1 for rooms in rooms_by_block.values()))

    def test_room_candidates_returns_fixed_room_first(self):
        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        home_room = Room.objects.get(r_number="LH-1")
        extra_room = Room.objects.create(
            r_number="LH-2",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )

        # When no fixed room, candidates follow prioritized_rooms order
        candidates = schedule._build_room_candidates(
            self.section.section_id,
            "Monday",
            "6",
            None,
            [extra_room, home_room],
            {},
            None,
        )
        self.assertEqual(candidates, [extra_room, home_room])

        # When a fixed room is set, it comes first
        schedule._fixed_rooms[self.section.section_id] = home_room
        candidates = schedule._build_room_candidates(
            self.section.section_id,
            "Monday",
            "6",
            None,
            [extra_room, home_room],
            {},
            None,
        )
        self.assertEqual(candidates[0], home_room)
        self.assertEqual(candidates[1], extra_room)

    def test_room_candidates_lock_to_subject_specific_room(self):
        locked_room = Room.objects.create(
            r_number="LH-LOCK",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="LOCK101",
            subject_name="Locked Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            specific_rooms="LH-LOCK",
            classes_per_week=1,
            user=self.user,
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        candidates = schedule._build_room_candidates(
            self.section.section_id,
            "Monday",
            "6",
            None,
            [Room.objects.get(r_number="LH-1"), locked_room],
            {},
            subject,
        )

        self.assertEqual(candidates, [locked_room])

    def test_lab_room_priority_uses_specific_room_over_category(self):
        locked_room = Room.objects.create(
            r_number="SPECIAL-LH",
            room_type="Lecture Hall",
            seating_capacity=40,
            department=self.department,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="LABLOCK",
            subject_name="Locked Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-A",
            specific_rooms="SPECIAL-LH",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        self.assertEqual(schedule._get_prioritized_lab_rooms("CAT-A", subject=subject), [locked_room])

    def test_generic_lab_subject_avoids_other_subjects_reserved_room(self):
        # Two lab rooms in the same category; one is locked as another
        # subject's specific room and must be kept free for its owner.
        owner_room = Room.objects.create(
            r_number="CC05",
            room_type="Lab",
            seating_capacity=30,
            lab_category="Computer Lab",
            department=self.department,
            user=self.user,
        )
        free_room = Room.objects.create(
            r_number="CC06",
            room_type="Lab",
            seating_capacity=30,
            lab_category="Computer Lab",
            department=self.department,
            user=self.user,
        )
        # Owner subject locked to CC05.
        Subject.objects.create(
            subject_number="OWN101",
            subject_name="CC05 Owner Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="Computer Lab",
            specific_rooms="CC05",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        # Generic subject that only needs the Computer Lab category.
        generic = Subject.objects.create(
            subject_number="GEN101",
            subject_name="Generic Computer Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="Computer Lab",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        ordered = schedule._get_prioritized_lab_rooms("Computer Lab", subject=generic)
        room_numbers = [room.r_number for room in ordered]

        self.assertIn("CC05", room_numbers)
        self.assertIn("CC06", room_numbers)
        # The reserved room (CC05) is pushed after the free room so the generic
        # subject only falls back to it when nothing else is available.
        self.assertLess(room_numbers.index("CC06"), room_numbers.index("CC05"))
        self.assertEqual(room_numbers[-1], "CC05")

    def test_saved_drag_room_candidates_prefer_original_then_usage(self):
        subject = Subject.objects.create(
            subject_number="DROP101",
            subject_name="Drop Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        original_room = Room.objects.create(
            r_number="LH-ORIG",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        busiest_room = Room.objects.create(
            r_number="LH-BUSY",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        medium_room = Room.objects.create(
            r_number="LH-MED",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )

        rooms = views_other._saved_drag_room_candidates(
            self.user,
            self.department,
            subject,
            original_room=original_room,
            usage_counts={busiest_room.pk: 5, medium_room.pk: 2, original_room.pk: 1},
        )

        self.assertEqual([room.pk for room in rooms[:3]], [original_room.pk, busiest_room.pk, medium_room.pk])

    def test_save_timetable_uses_live_generated_state_instead_of_stale_snapshot(self):
        request = RequestFactory().get(
            reverse("save_timetable", args=[1]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user

        stale_subject = Subject.objects.create(
            subject_number="SAVE101",
            subject_name="Stale Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        live_subject = Subject.objects.create(
            subject_number="SAVE102",
            subject_name="Live Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        stale_subject.instructors.add(Instructor.objects.create(
            uid="S101",
            name="Stale Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        ))
        live_teacher = Instructor.objects.create(
            uid="S102",
            name="Live Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        live_subject.instructors.add(live_teacher)
        self.section.allowed_subjects.add(stale_subject, live_subject)

        room = Room.objects.filter(user=self.user, room_type="Lecture Hall").first()
        stale_mt = MeetingTime.objects.get(user=self.user, day="Monday", time="1")
        live_mt = MeetingTime.objects.get(user=self.user, day="Tuesday", time="2")

        stale_class = views_other.Class(1, self.department, self.section.section_id, stale_subject)
        stale_class.set_instructor(stale_subject.instructors.first())
        stale_class.set_room(room)
        stale_class.set_meetingTime(stale_mt)

        live_class = views_other.Class(2, self.department, self.section.section_id, live_subject)
        live_class.set_instructor(live_teacher)
        live_class.set_room(room)
        live_class.set_meetingTime(live_mt)
        live_class.meeting_times = [live_mt]

        state = views_other._get_user_state(self.user.id)
        state["schedules"] = [{"classes": [stale_class], "labs": [], "stats": {}, "reco_block": {}}]
        state["classes"] = [live_class]
        state["labs"] = []
        state["generated_edit_index"] = 1
        views_other.GLOBAL_GENERATED_SCHEDULES = state["schedules"]
        views_other.GLOBAL_CLASSES = state["classes"]
        views_other.GLOBAL_LABS = state["labs"]

        response = views_other.save_timetable(request, 1)

        self.assertEqual(response.status_code, 200)
        saved = SavedTimetable.objects.get(user=self.user)
        slot = ScheduledSlot.objects.get(timetable=saved)
        self.assertEqual(slot.subject, live_subject)
        self.assertEqual(slot.instructor, live_teacher)
        self.assertEqual(slot.meeting_time, live_mt)

    def test_saved_reshuffle_missing_subject_creates_slot(self):
        request = RequestFactory().post(
            reverse("saved_reshuffle_missing_subject", args=[1, self.section.section_id, self.section.allowed_subjects.first().pk]),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user

        subject = Subject.objects.create(
            subject_number="SAVE201",
            subject_name="Saved Repair Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="S201",
            name="Saved Repair Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject.instructors.add(teacher)
        self.section.allowed_subjects.add(subject)

        saved = SavedTimetable.objects.create(user=self.user)
        response = views_other.saved_reshuffle_missing_subject(request, saved.id, self.section.section_id, subject.pk)

        self.assertEqual(response.status_code, 200)
        slot = ScheduledSlot.objects.get(timetable=saved)
        self.assertEqual(slot.subject, subject)
        self.assertEqual(slot.instructor, teacher)
        self.assertFalse(slot.is_lab)

    def test_saved_reshuffle_missing_subject_creates_multiple_slots_when_possible(self):
        request = RequestFactory().post(
            reverse("saved_reshuffle_missing_subject", args=[1, self.section.section_id, self.section.allowed_subjects.first().pk]),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user

        subject = Subject.objects.create(
            subject_number="SAVE202",
            subject_name="Saved Multi Repair Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="S202",
            name="Saved Multi Repair Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject.instructors.add(teacher)
        self.section.allowed_subjects.add(subject)

        saved = SavedTimetable.objects.create(user=self.user)
        response = views_other.saved_reshuffle_missing_subject(request, saved.id, self.section.section_id, subject.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ScheduledSlot.objects.filter(timetable=saved, subject=subject).count(), 3)

    def test_saved_reshuffle_ignores_stale_global_conflicts(self):
        request = RequestFactory().post(
            reverse("saved_reshuffle_missing_subject", args=[1, self.section.section_id, self.section.allowed_subjects.first().pk]),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        request.user = self.user

        subject = Subject.objects.create(
            subject_number="SAVE203",
            subject_name="Saved Global Isolation Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="S203",
            name="Saved Global Isolation Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject.instructors.add(teacher)
        self.section.allowed_subjects.add(subject)

        blocking_subject = self.section.allowed_subjects.filter(room_required="Lecture Hall").exclude(pk=subject.pk).first()
        blocking_room = Room.objects.get(r_number="LH-1")
        blocking_mt = MeetingTime.objects.get(pid="Mo1")
        blocking_class = views_other.Class(999, self.department, self.section.section_id, blocking_subject)
        blocking_class.set_instructor(teacher)
        blocking_class.set_room(blocking_room)
        blocking_class.set_meetingTime(blocking_mt)
        blocking_class.meeting_times = [blocking_mt]

        saved = SavedTimetable.objects.create(user=self.user)
        views_other.GLOBAL_CLASSES = [blocking_class]
        views_other.GLOBAL_LABS = []

        response = views_other.saved_reshuffle_missing_subject(request, saved.id, self.section.section_id, subject.pk)

        self.assertEqual(response.status_code, 200)
        slot = ScheduledSlot.objects.get(timetable=saved, subject=subject)
        self.assertEqual(slot.subject, subject)
        self.assertEqual(slot.instructor, teacher)

    def test_grouped_theory_uses_parallel_slots_with_two_teachers(self):
        Room.objects.create(
            r_number="LH-2",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="Grouped Theory",
            department=self.department,
            user=self.user,
        )
        teacher_one = Instructor.objects.create(
            uid="GT001",
            name="Grouped Theory Teacher 1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        teacher_two = Instructor.objects.create(
            uid="GT002",
            name="Grouped Theory Teacher 2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="GTH001",
            subject_name="Grouped Lecture",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject.instructors.add(teacher_one, teacher_two)
        section.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        grouped_classes = [
            cls for cls in schedule.get_classes()
            if cls.section == section.section_id and cls.subject == subject
        ]

        self.assertEqual(len(grouped_classes), 2)
        self.assertEqual(
            len({(cls.meeting_time.day, cls.meeting_time.time) for cls in grouped_classes}),
            1,
        )
        self.assertEqual(len({cls.room.r_number for cls in grouped_classes}), 2)
        self.assertEqual(len({cls.instructor.pk for cls in grouped_classes}), 2)

    def test_grouped_theory_uses_different_slots_with_one_teacher(self):
        section = Section.objects.create(
            section_id="Serial Theory",
            department=self.department,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="GT003",
            name="Grouped Theory Solo Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="GTH002",
            subject_name="Serial Grouped Lecture",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject.instructors.add(teacher)
        section.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        grouped_classes = [
            cls for cls in schedule.get_classes()
            if cls.section == section.section_id and cls.subject == subject
        ]

        self.assertEqual(len(grouped_classes), 2)
        self.assertEqual(len({(cls.meeting_time.day, cls.meeting_time.time) for cls in grouped_classes}), 2)

    def test_grouped_theory_uses_fixed_group_teacher_assignments(self):
        Room.objects.create(
            r_number="LH-2",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="Fixed Group Theory",
            department=self.department,
            user=self.user,
        )
        teacher_one = Instructor.objects.create(
            uid="FG001",
            name="Fixed Group Teacher 1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        teacher_two = Instructor.objects.create(
            uid="FG002",
            name="Fixed Group Teacher 2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="FGT001",
            subject_name="Fixed Group Lecture",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject.instructors.add(teacher_one, teacher_two)
        section.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)
        SectionSubjectInstructor.objects.create(
            user=self.user,
            section=section,
            subject=subject,
            instructor=teacher_one,
            second_instructor=None,
            group_instructor_ids=[teacher_one.id, teacher_two.id],
            group_second_instructor_ids=[],
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        grouped_classes = sorted(
            [cls for cls in schedule.get_classes() if cls.section == section.section_id and cls.subject == subject],
            key=lambda cls: cls.group or "",
        )

        self.assertEqual(len(grouped_classes), 2)
        self.assertEqual(grouped_classes[0].instructor.uid, "FG001")
        self.assertEqual(grouped_classes[1].instructor.uid, "FG002")

    def test_lab_group_count_overrides_capacity_batches(self):
        section = Section.objects.create(
            section_id="Lab Override",
            department=self.department,
            user=self.user,
            student_strength=90,
        )
        teacher = Instructor.objects.create(
            uid="GL001",
            name="Grouped Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        lab_subject = Subject.objects.create(
            subject_number="GLAB01",
            subject_name="Grouped Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            classes_per_week=1,
            user=self.user,
        )
        lab_subject.instructors.add(teacher)
        section.allowed_subjects.add(lab_subject)
        SectionSubjectMapping.objects.filter(section=section, subject=lab_subject).update(group_count=1)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize_labs()

        grouped_labs = [
            lab for lab in schedule.get_labs()
            if lab.section == section.section_id and lab.subject == lab_subject
        ]

        self.assertEqual(len(grouped_labs), 1)
        self.assertEqual(grouped_labs[0].total_batches, 1)

    def test_unmapped_section_is_not_scheduled_from_department_fallback(self):
        mapped_section = Section.objects.create(
            section_id="Mapped Section",
            department=self.department,
            user=self.user,
        )
        empty_section = Section.objects.create(
            section_id="Empty Section",
            department=self.department,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="UF001",
            name="Fallback Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="UF101",
            subject_name="Mapped Only Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject.instructors.add(teacher)
        mapped_section.allowed_subjects.add(subject)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        mapped_classes = [cls for cls in schedule.get_classes() if cls.section == mapped_section.section_id and cls.subject == subject]
        empty_classes = [cls for cls in schedule.get_classes() if cls.section == empty_section.section_id]

        self.assertTrue(mapped_classes)
        self.assertEqual(empty_classes, [])

    def test_subject_without_basic_resources_is_skipped(self):
        section = Section.objects.create(
            section_id="Resource Gap Section",
            department=self.department,
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="RG001",
            name="Resource Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        schedulable_subject = Subject.objects.create(
            subject_number="RG101",
            subject_name="Schedulable Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        blocked_subject = Subject.objects.create(
            subject_number="RG102",
            subject_name="Teacherless Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        schedulable_subject.instructors.add(teacher)
        section.allowed_subjects.add(schedulable_subject, blocked_subject)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        scheduled_subject_numbers = {
            cls.subject.subject_number
            for cls in schedule.get_classes()
            if cls.section == section.section_id
        }

        self.assertIn(schedulable_subject.subject_number, scheduled_subject_numbers)
        self.assertNotIn(blocked_subject.subject_number, scheduled_subject_numbers)

    def test_split_solo_lab_honors_classes_per_week_for_each_batch(self):
        section = Section.objects.create(
            section_id="Repeated Grouped Lab",
            department=self.department,
            user=self.user,
            student_strength=60,
        )
        room = Room.objects.create(
            r_number="LAB-CPW",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CPW-LAB",
            user=self.user,
        )
        teacher = Instructor.objects.create(
            uid="CPW001",
            name="Repeated Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        lab_subject = Subject.objects.create(
            subject_number="CPWLAB01",
            subject_name="Repeated Grouped Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CPW-LAB",
            classes_per_week=2,
            duration=2,
            user=self.user,
        )
        lab_subject.instructors.add(teacher)
        section.allowed_subjects.add(lab_subject)
        SectionSubjectMapping.objects.filter(section=section, subject=lab_subject).update(group_count=2)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize_labs()

        grouped_labs = [
            lab for lab in schedule.get_labs()
            if lab.section == section.section_id and lab.subject == lab_subject
        ]

        self.assertEqual(len(grouped_labs), 4)
        self.assertEqual(sorted(lab.batch_number for lab in grouped_labs), [1, 1, 2, 2])
        self.assertTrue(all(lab.room == room for lab in grouped_labs))

    def test_rotation_group_backtracks_before_split_solo(self):
        section = Section.objects.create(
            section_id="Rotation Search",
            department=self.department,
            user=self.user,
            student_strength=60,
        )
        room_a = Room.objects.create(
            r_number="LAB-A",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-A",
            user=self.user,
        )
        room_b = Room.objects.create(
            r_number="LAB-B",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-B",
            user=self.user,
        )
        a1 = Instructor.objects.create(
            uid="RA001",
            name="Rotation A1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        a2 = Instructor.objects.create(
            uid="RA002",
            name="Rotation A2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        b1 = Instructor.objects.create(
            uid="RB001",
            name="Rotation B1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        b2 = Instructor.objects.create(
            uid="RB002",
            name="Rotation B2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject_a = Subject.objects.create(
            subject_number="RLA001",
            subject_name="Rotation Lab A",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-A",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        subject_b = Subject.objects.create(
            subject_number="RLB001",
            subject_name="Rotation Lab B",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-B",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        subject_a.instructors.add(a1, a2)
        subject_b.instructors.add(b1, b2)
        section.allowed_subjects.add(subject_a, subject_b)
        SectionSubjectMapping.objects.filter(section=section, subject=subject_a).update(group_count=2)
        SectionSubjectMapping.objects.filter(section=section, subject=subject_b).update(group_count=2)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        schedule._lab_days = {section.section_id: set()}
        monday_block = [MeetingTime.objects.get(pid="Mo1"), MeetingTime.objects.get(pid="Mo2")]
        tuesday_block = [MeetingTime.objects.get(pid="Tu1"), MeetingTime.objects.get(pid="Tu2")]

        def day_blocks(duration=None):
            return iter([
                ("Monday", monday_block),
                ("Tuesday", tuesday_block),
            ])

        def room_pool(required_category=None, subject=None):
            if required_category == "CAT-A":
                return [room_a]
            if required_category == "CAT-B":
                return [room_b]
            return []

        real_conflict_checker = schedule._conflicts_if_assign_lab

        def conflict_checker(mts, room, instructor, section_id, group=None, max_parallel=2, co_instructor=None, subject=None):
            day = mts[0].day
            allowed = {
                ("Monday", room_a.r_number, a1.uid),
                ("Monday", room_a.r_number, a2.uid),
                ("Tuesday", room_a.r_number, a2.uid),
                ("Monday", room_b.r_number, b1.uid),
                ("Monday", room_b.r_number, b2.uid),
                ("Tuesday", room_b.r_number, b1.uid),
            }
            if (day, room.r_number, instructor.uid) not in allowed:
                return True
            return real_conflict_checker(
                mts,
                room,
                instructor,
                section_id,
                group=group,
                max_parallel=max_parallel,
                co_instructor=co_instructor,
                subject=subject,
            )

        def lab_instructors(subject):
            if subject == subject_a:
                return [a1, a2]
            if subject == subject_b:
                return [b1, b2]
            return []

        with patch.object(schedule, "_iter_lab_day_blocks", side_effect=day_blocks), patch.object(
            schedule, "_get_prioritized_lab_rooms", side_effect=room_pool
        ), patch.object(schedule, "_conflicts_if_assign_lab", side_effect=conflict_checker):
            success = schedule._schedule_rotation_group(
                section,
                self.department,
                [subject_a, subject_b],
                2,
                {},
                lab_instructors,
            )

        self.assertTrue(success)
        grouped_labs = [lab for lab in schedule.get_labs() if lab.section == section.section_id]
        self.assertEqual(len(grouped_labs), 4)
        parallel_slots = {}
        for lab in grouped_labs:
            key = (lab.meeting_times[0].day, lab.meeting_times[0].time)
            parallel_slots.setdefault(key, []).append(lab.subject.subject_number)
        self.assertEqual({key for key, vals in parallel_slots.items() if len(vals) == 2}, {("Monday", "1"), ("Tuesday", "1")})

    def test_initialize_labs_prioritizes_constrained_grouped_sections(self):
        flexible_section = Section.objects.create(
            section_id="Flexible First",
            department=self.department,
            user=self.user,
            student_strength=60,
        )
        constrained_section = Section.objects.create(
            section_id="Constrained Second",
            department=self.department,
            user=self.user,
            student_strength=60,
        )

        Room.objects.create(
            r_number="LAB-SPEC",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-S",
            user=self.user,
        )
        Room.objects.create(
            r_number="LAB-GEN",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-G",
            user=self.user,
        )

        flexible_teacher = Instructor.objects.create(
            uid="FLX001",
            name="Flexible Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        constrained_teacher_a = Instructor.objects.create(
            uid="CNS001",
            name="Constrained Lab Teacher A",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        constrained_teacher_b = Instructor.objects.create(
            uid="CNS002",
            name="Constrained Lab Teacher B",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )

        flexible_subject = Subject.objects.create(
            subject_number="FLXLAB",
            subject_name="Flexible Specific Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-S",
            specific_rooms="LAB-SPEC",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        constrained_subject_a = Subject.objects.create(
            subject_number="CNSLAB1",
            subject_name="Constrained Specific Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-S",
            specific_rooms="LAB-SPEC",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        constrained_subject_b = Subject.objects.create(
            subject_number="CNSLAB2",
            subject_name="Constrained Parallel Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-G",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )

        flexible_subject.instructors.add(flexible_teacher)
        constrained_subject_a.instructors.add(constrained_teacher_a)
        constrained_subject_b.instructors.add(constrained_teacher_b)

        flexible_section.allowed_subjects.add(flexible_subject)
        constrained_section.allowed_subjects.add(constrained_subject_a, constrained_subject_b)

        SectionSubjectMapping.objects.filter(section=flexible_section, subject=flexible_subject).update(group_count=2)
        SectionSubjectMapping.objects.filter(section=constrained_section, subject=constrained_subject_a).update(group_count=2)
        SectionSubjectMapping.objects.filter(section=constrained_section, subject=constrained_subject_b).update(group_count=2)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        monday_block = [MeetingTime.objects.get(pid="Mo1"), MeetingTime.objects.get(pid="Mo2")]
        tuesday_block = [MeetingTime.objects.get(pid="Tu1"), MeetingTime.objects.get(pid="Tu2")]

        def limited_day_blocks(duration=None):
            return iter([
                ("Monday", monday_block),
                ("Tuesday", tuesday_block),
            ])

        with patch.object(views_other, "SECTION_LOAD_RULES", {
            "Flexible First": (0, 2),
            "Constrained Second": (0, 4),
        }), patch.object(views_other.rnd, "shuffle", side_effect=lambda seq: None), patch.object(
            schedule, "_iter_lab_day_blocks", side_effect=limited_day_blocks
        ):
            schedule.initialize_labs()

        constrained_labs = [
            lab for lab in schedule.get_labs()
            if lab.section == constrained_section.section_id
        ]

        self.assertEqual(len(constrained_labs), 4)
        parallel_slots = {}
        for lab in constrained_labs:
            key = (lab.meeting_times[0].day, lab.meeting_times[0].time)
            parallel_slots.setdefault(key, []).append(lab.subject.subject_number)

        self.assertEqual(
            {key for key, vals in parallel_slots.items() if len(vals) == 2},
            {("Monday", "1"), ("Tuesday", "1")},
        )

    def test_initialize_labs_parallelizes_single_grouped_lab_with_multivalue_categories(self):
        section = Section.objects.create(
            section_id="Workshop Section",
            department=self.department,
            user=self.user,
            student_strength=90,
        )

        room_computer = Room.objects.create(
            r_number="LAB-C",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="Computer Lab",
            user=self.user,
        )
        room_electrical = Room.objects.create(
            r_number="LAB-E",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="Electrical Lab",
            user=self.user,
        )
        room_electronics = Room.objects.create(
            r_number="LAB-EL",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="Electronics Lab",
            user=self.user,
        )

        instructors = []
        for index in range(1, 4):
            instructors.append(
                Instructor.objects.create(
                    uid=f"WS{index:03d}",
                    name=f"Workshop Teacher {index}",
                    designation="Assistant Professor",
                    max_workload=25,
                    user=self.user,
                )
            )

        workshop = Subject.objects.create(
            subject_number="WS001",
            subject_name="Workshop",
            department=self.department,
            max_numb_students=90,
            room_required="Lab",
            required_lab_category="Computer Lab;Electrical Lab;Electronics Lab",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        workshop.instructors.add(*instructors)
        section.allowed_subjects.add(workshop)
        SectionSubjectMapping.objects.filter(section=section, subject=workshop).update(group_count=3)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        schedule._lab_days = {section.section_id: set()}

        monday_block = [MeetingTime.objects.get(pid="Mo1"), MeetingTime.objects.get(pid="Mo2")]

        def day_blocks(duration=None):
            return iter([("Monday", monday_block)])

        with patch.object(schedule, "_iter_lab_day_blocks", side_effect=day_blocks):
            success = schedule._schedule_parallel_single_subject(
                section,
                self.department,
                workshop,
                3,
                {},
                lambda _subject: instructors,
            )

        self.assertTrue(success)
        grouped_labs = [lab for lab in schedule.get_labs() if lab.section == section.section_id]
        self.assertEqual(len(grouped_labs), 3)
        self.assertEqual({lab.meeting_times[0].day for lab in grouped_labs}, {"Monday"})
        self.assertEqual({lab.meeting_times[0].time for lab in grouped_labs}, {"1"})
        self.assertEqual({lab.room for lab in grouped_labs}, {room_computer, room_electrical, room_electronics})

    def test_rotation_group_tries_best_pair_order_before_falling_back(self):
        section = Section.objects.create(
            section_id="Balanced Rotation",
            department=self.department,
            user=self.user,
            student_strength=60,
        )
        room_computer = Room.objects.create(
            r_number="LAB-C1",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-C",
            user=self.user,
        )
        room_electronics = Room.objects.create(
            r_number="LAB-E1",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-E",
            user=self.user,
        )
        subjects = []
        for code, name, category, teacher_uid in [
            ("BAL1", "Computer Lab 1", "CAT-C", "BC001"),
            ("BAL2", "Electronics Lab 1", "CAT-E", "BE001"),
            ("BAL3", "Electronics Lab 2", "CAT-E", "BE002"),
            ("BAL4", "Computer Lab 2", "CAT-C", "BC002"),
        ]:
            teacher = Instructor.objects.create(
                uid=teacher_uid,
                name=f"Teacher {teacher_uid}",
                designation="Assistant Professor",
                max_workload=25,
                user=self.user,
            )
            subject = Subject.objects.create(
                subject_number=code,
                subject_name=name,
                department=self.department,
                max_numb_students=30,
                room_required="Lab",
                required_lab_category=category,
                classes_per_week=1,
                duration=2,
                user=self.user,
            )
            subject.instructors.add(teacher)
            section.allowed_subjects.add(subject)
            SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)
            subjects.append(subject)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        schedule._lab_days = {section.section_id: set()}
        blocks = [
            [MeetingTime.objects.get(pid="Mo1"), MeetingTime.objects.get(pid="Mo2")],
            [MeetingTime.objects.get(pid="Tu1"), MeetingTime.objects.get(pid="Tu2")],
            [MeetingTime.objects.get(pid="We1"), MeetingTime.objects.get(pid="We2")],
            [MeetingTime.objects.get(pid="Th1"), MeetingTime.objects.get(pid="Th2")],
        ]

        def day_blocks(duration=None):
            return iter([
                ("Monday", blocks[0]),
                ("Tuesday", blocks[1]),
                ("Wednesday", blocks[2]),
                ("Thursday", blocks[3]),
            ])

        with patch.object(schedule, "_iter_lab_day_blocks", side_effect=day_blocks):
            success = schedule._schedule_rotation_group(
                section,
                self.department,
                subjects,
                2,
                {},
                lambda subject: list(subject.instructors.all()),
            )

        self.assertTrue(success)
        grouped_labs = [lab for lab in schedule.get_labs() if lab.section == section.section_id]
        self.assertEqual(len(grouped_labs), 8)
        parallel_pairs = {
            tuple(sorted(lab.subject.subject_name for lab in labs))
            for _slot, labs in {
                (lab.meeting_times[0].day, lab.meeting_times[0].time): [
                    grouped_lab for grouped_lab in grouped_labs
                    if grouped_lab.meeting_times[0].day == lab.meeting_times[0].day
                    and grouped_lab.meeting_times[0].time == lab.meeting_times[0].time
                ]
                for lab in grouped_labs
            }.items()
        }
        self.assertEqual(parallel_pairs, {
            ("Computer Lab 1", "Electronics Lab 1"),
            ("Computer Lab 1", "Electronics Lab 2"),
            ("Computer Lab 2", "Electronics Lab 1"),
            ("Computer Lab 2", "Electronics Lab 2"),
        })

    def test_rotation_group_preserves_feasible_pairs_when_one_pair_is_impossible(self):
        section = Section.objects.create(
            section_id="Partial Rotation",
            department=self.department,
            user=self.user,
            student_strength=60,
        )
        Room.objects.create(
            r_number="LAB-C2",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-C",
            user=self.user,
        )
        Room.objects.create(
            r_number="LAB-E2",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-E",
            user=self.user,
        )
        subjects = []
        for code, name, category, teacher_uid in [
            ("PAR1", "Computer Lab", "CAT-C", "PC001"),
            ("PAR2", "Electronics Lab A", "CAT-E", "PE001"),
            ("PAR3", "Electronics Lab B", "CAT-E", "PE002"),
        ]:
            teacher = Instructor.objects.create(
                uid=teacher_uid,
                name=f"Teacher {teacher_uid}",
                designation="Assistant Professor",
                max_workload=25,
                user=self.user,
            )
            subject = Subject.objects.create(
                subject_number=code,
                subject_name=name,
                department=self.department,
                max_numb_students=30,
                room_required="Lab",
                required_lab_category=category,
                classes_per_week=1,
                duration=2,
                user=self.user,
            )
            subject.instructors.add(teacher)
            section.allowed_subjects.add(subject)
            SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)
            subjects.append(subject)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()
        schedule._lab_days = {section.section_id: set()}
        blocks = [
            [MeetingTime.objects.get(pid="Mo1"), MeetingTime.objects.get(pid="Mo2")],
            [MeetingTime.objects.get(pid="Tu1"), MeetingTime.objects.get(pid="Tu2")],
            [MeetingTime.objects.get(pid="We1"), MeetingTime.objects.get(pid="We2")],
        ]

        def day_blocks(duration=None):
            return iter([
                ("Monday", blocks[0]),
                ("Tuesday", blocks[1]),
                ("Wednesday", blocks[2]),
            ])

        with patch.object(schedule, "_iter_lab_day_blocks", side_effect=day_blocks):
            success = schedule._schedule_rotation_group(
                section,
                self.department,
                subjects,
                2,
                {},
                lambda subject: list(subject.instructors.all()),
            )

        self.assertTrue(success)
        grouped_labs = [lab for lab in schedule.get_labs() if lab.section == section.section_id]
        self.assertEqual(len(grouped_labs), 5)
        parallel_slots = {}
        for lab in grouped_labs:
            key = (lab.meeting_times[0].day, lab.meeting_times[0].time)
            parallel_slots.setdefault(key, []).append(lab.subject.subject_name)
        self.assertEqual(len([slot for slot, names in parallel_slots.items() if len(names) == 2]), 2)
        self.assertEqual(sorted(lab.subject.subject_name for lab in grouped_labs).count("Computer Lab"), 2)


class SavedTimetableParkingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="parking_user", password="testpass123")
        self.client.force_login(self.user)

        self.department = Department.objects.create(user=self.user)
        self.section = Section.objects.create(
            section_id="SEC-A",
            department=self.department,
            user=self.user,
        )
        self.other_section = Section.objects.create(
            section_id="SEC-B",
            department=self.department,
            user=self.user,
        )
        self.room = Room.objects.create(
            r_number="LH-101",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        self.other_room = Room.objects.create(
            r_number="LH-102",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        self.instructor = Instructor.objects.create(
            uid="T901",
            name="Parking Teacher",
            email="parking@example.com",
            contact_number="9999999999",
            designation="Assistant Professor",
            max_workload=12,
            user=self.user,
        )
        self.subject = Subject.objects.create(
            subject_number="SUB901",
            subject_name="Saved Parking Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=2,
            user=self.user,
        )
        self.subject.instructors.add(self.instructor)
        self.section.allowed_subjects.add(self.subject)

        self.mt1 = MeetingTime.objects.create(pid="Mo1", day="Monday", time="1", user=self.user)
        self.mt2 = MeetingTime.objects.create(pid="Mo2", day="Monday", time="2", user=self.user)
        self.saved = SavedTimetable.objects.create(user=self.user, department=self.department)

    def test_saved_park_slot_creates_parking_item_and_room_reservation(self):
        ScheduledSlot.objects.create(
            timetable=self.saved,
            section=self.section,
            subject=self.subject,
            instructor=self.instructor,
            room=self.room,
            meeting_time=self.mt1,
            is_lab=False,
        )

        response = self.client.post(
            reverse("saved_park_slot", args=[self.saved.id, self.section.section_id, "Monday", 1]),
            data='{"move_type":"class"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScheduledSlot.objects.filter(timetable=self.saved).exists())
        self.assertTrue(
            SavedParkingSlot.objects.filter(
                timetable=self.saved,
                section=self.section,
                subject=self.subject,
            ).exists()
        )
        reservation = SavedSlotRoomReservation.objects.get(
            timetable=self.saved,
            section=self.section,
            meeting_time=self.mt1,
        )
        self.assertEqual(reservation.room, self.room)

    def test_saved_restore_parked_slot_uses_reserved_room_and_blocks_teacher_conflict(self):
        parked = SavedParkingSlot.objects.create(
            timetable=self.saved,
            section=self.section,
            subject=self.subject,
            instructor=self.instructor,
            original_room=self.room,
            original_meeting_time=self.mt1,
            is_lab=False,
            slot_span=1,
        )
        SavedSlotRoomReservation.objects.create(
            timetable=self.saved,
            section=self.section,
            meeting_time=self.mt2,
            room=self.other_room,
        )

        conflict_subject = Subject.objects.create(
            subject_number="SUB902",
            subject_name="Conflicting Subject",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        conflict_subject.instructors.add(self.instructor)
        ScheduledSlot.objects.create(
            timetable=self.saved,
            section=self.other_section,
            subject=conflict_subject,
            instructor=self.instructor,
            room=self.room,
            meeting_time=self.mt2,
            is_lab=False,
        )

        blocked_response = self.client.post(
            reverse("saved_restore_parked_slot", args=[self.saved.id, parked.id]),
            data='{"target_section":"SEC-A","target_day":"Monday","target_slot":"2"}',
            content_type="application/json",
        )
        self.assertEqual(blocked_response.status_code, 409)
        self.assertTrue(SavedParkingSlot.objects.filter(id=parked.id).exists())

        ScheduledSlot.objects.filter(
            timetable=self.saved,
            section=self.other_section,
            meeting_time=self.mt2,
        ).delete()

        success_response = self.client.post(
            reverse("saved_restore_parked_slot", args=[self.saved.id, parked.id]),
            data='{"target_section":"SEC-A","target_day":"Monday","target_slot":"2"}',
            content_type="application/json",
        )
        self.assertEqual(success_response.status_code, 200)

        restored = ScheduledSlot.objects.get(
            timetable=self.saved,
            section=self.section,
            meeting_time=self.mt2,
        )
        self.assertEqual(restored.room, self.other_room)
        self.assertFalse(SavedParkingSlot.objects.filter(id=parked.id).exists())
        self.assertFalse(
            SavedSlotRoomReservation.objects.filter(
                timetable=self.saved,
                section=self.section,
                meeting_time=self.mt2,
            ).exists()
        )


class LiveTimetableReopenProjectionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="live_user", password="testpass123")
        self.client.force_login(self.user)

        views_other.ensure_private_generator_loaded()

        self.department = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        self.section = Section.objects.create(section_id="SEC-LIVE", department=self.department, user=self.user)

        self.teacher = Instructor.objects.create(
            uid="LIVE-T1",
            name="Live Theory Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.department,
        )
        self.lab_teacher = Instructor.objects.create(
            uid="LIVE-L1",
            name="Live Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.department,
        )

        self.lecture_room = Room.objects.create(
            r_number="LH-LIVE",
            room_type="Lecture Hall",
            seating_capacity=80,
            department=self.department,
            user=self.user,
        )
        self.lab_room = Room.objects.create(
            r_number="LAB-LIVE",
            room_type="Lab",
            seating_capacity=30,
            lab_category="CAT-A",
            department=self.department,
            user=self.user,
        )

        self.theory_subject = Subject.objects.create(
            subject_number="TH-LIVE",
            subject_name="Live Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            duration=1,
            user=self.user,
        )
        self.theory_subject.instructors.add(self.teacher)

        self.lab_subject = Subject.objects.create(
            subject_number="LAB-LIVE",
            subject_name="Live Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-A",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        self.lab_subject.instructors.add(self.lab_teacher)
        self.section.allowed_subjects.add(self.theory_subject, self.lab_subject)

        self.mt1 = MeetingTime.objects.create(pid="Mo1-live", day="Monday", time="1", user=self.user)
        self.mt2 = MeetingTime.objects.create(pid="Mo2-live", day="Monday", time="2", user=self.user)
        self.mt6 = MeetingTime.objects.create(pid="Mo6-live", day="Monday", time="6", user=self.user)
        self.mt7 = MeetingTime.objects.create(pid="Mo7-live", day="Monday", time="7", user=self.user)

        class_obj = views_other.Class(1, self.department, self.section.section_id, self.theory_subject)
        class_obj.set_instructor(self.teacher)
        class_obj.set_room(self.lecture_room)
        class_obj.set_meetingTime(self.mt1)
        class_obj.meeting_times = [self.mt1]
        class_obj.duration = 1

        lab_obj = views_other.Lab(2, self.department, self.section.section_id, self.lab_subject, batch=1, total_batches=1)
        lab_obj.set_instructor(self.lab_teacher)
        lab_obj.set_room(self.lab_room)
        lab_obj.set_meetingTimes([self.mt6, self.mt7])
        lab_obj.duration = 2

        state = views_other._get_user_state(self.user.id)
        state["schedules"] = [{
            "classes": [class_obj],
            "labs": [lab_obj],
            "stats": {},
            "reco_block": {},
        }]
        views_other._bind_runtime_to_schedule(state, 1)
        state["view_mode"] = "editing"

        session = self.client.session
        session["current_index"] = 1
        session.save()

    def _assert_live_projection_context(self, context):
        teacher_tables = context["teacher_tables"]
        self.assertTrue(any(table["teacher"].uid == self.teacher.uid for table in teacher_tables))
        self.assertTrue(any(table["teacher"].uid == self.lab_teacher.uid for table in teacher_tables))
        self.assertTrue(
            any(
                table["teacher"].uid == self.teacher.uid
                and any(cell.get("classes") for row in table["rows"] for cell in row["cells"])
                for table in teacher_tables
            )
        )
        self.assertTrue(
            any(
                table["teacher"].uid == self.lab_teacher.uid
                and any(cell.get("labs") for row in table["rows"] for cell in row["cells"])
                for table in teacher_tables
            )
        )

        room_tables = context["room_tables"]
        self.assertTrue(
            any(
                table["room"].r_number == self.lecture_room.r_number
                and any(cell.get("classes") for row in table["rows"] for cell in row["cells"])
                for table in room_tables
            )
        )
        self.assertTrue(
            any(
                table["room"].r_number == self.lab_room.r_number
                and any(cell.get("labs") for row in table["rows"] for cell in row["cells"])
                for table in room_tables
            )
        )

        workloads = context["teacher_workloads"]
        teacher_totals = {
            getattr(teacher, "uid", ""): data["total"]
            for teacher, data in workloads.items()
        }
        self.assertEqual(teacher_totals.get(self.teacher.uid), 1)
        self.assertEqual(teacher_totals.get(self.lab_teacher.uid), 2)

        stats_by_room = {
            row["r_number"]: row["used_slots"]
            for row in context["room_statistics"]["overall"]["rooms"]
        }
        self.assertEqual(stats_by_room.get(self.lecture_room.r_number), 1)
        self.assertEqual(stats_by_room.get(self.lab_room.r_number), 2)

    def _load_live_projection_context(self, live_id):
        request = RequestFactory().get("/")
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        index, _live_timetable = views_other.load_live_timetable_into_runtime(request, live_id)
        self.assertEqual(index, 1)

        return self._current_live_projection_context()

    def _current_live_projection_context(self):

        private_views_main = getattr(views, "_views_main", None)
        self.assertIsNotNone(private_views_main)
        private_core = private_views_main.core
        state = views_other._get_user_state(self.user.id)
        classes = list(state.get("classes") or [])
        labs = list(state.get("labs") or [])
        statistics = private_views_main._compute_full_statistics(classes, labs, self.user)
        return {
            "teacher_tables": private_core.build_teacher_tables(classes, labs, user=self.user),
            "room_tables": private_core.build_room_tables(classes, labs, user=self.user),
            "teacher_workloads": private_core._compute_teacher_workloads(classes, labs),
            "room_statistics": statistics,
        }

    def _move_restored_class(self, source_slot, target_slot):
        private_views_main = getattr(views, "_views_main", None)
        self.assertIsNotNone(private_views_main)
        private_core = private_views_main.core

        request = RequestFactory().post(
            "/",
            data=json.dumps({
                "target_day": "Monday",
                "target_slot": target_slot,
                "move_type": "class",
            }),
            content_type="application/json",
        )
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session["current_index"] = 1
        request.session.save()

        response = private_core.move_slot_dragdrop(request, self.section.section_id, "Monday", source_slot)
        self.assertEqual(response.status_code, 200)

    def _load_live_state(self, live_id):
        request = RequestFactory().get("/")
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        index, _live_timetable = views_other.load_live_timetable_into_runtime(request, live_id)
        self.assertEqual(index, 1)
        return views_other._get_user_state(self.user.id)

    def _rows_have_class_at_slot(self, rows, day, slot_number):
        for row in rows:
            if row.get("day") != day:
                continue
            for cell in row.get("cells", []):
                if cell.get("slot_number") == slot_number and cell.get("classes"):
                    return True
                if cell.get("classes"):
                    first_class = cell["classes"][0]
                    meeting_time = getattr(first_class, "meeting_time", None)
                    if meeting_time is not None and int(getattr(meeting_time, "time", 0) or 0) == slot_number:
                        return True
                if cell.get("labs"):
                    meeting_times = list(getattr(cell["labs"][0], "meeting_times", None) or [])
                    if meeting_times and int(getattr(meeting_times[0], "time", 0) or 0) == slot_number:
                        return True
        return False

    def test_live_timetable_reopen_rebuilds_teacher_and_room_views_from_snapshot_runtime(self):
        save_response = self.client.get(reverse("save_live_timetable", args=[1]))
        self.assertEqual(save_response.status_code, 200)
        first_live = LiveTimetable.objects.get(user=self.user)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)

        first_context = self._load_live_projection_context(first_live.id)
        self._assert_live_projection_context(first_context)

        self._move_restored_class(1, 2)
        moved_context = self._current_live_projection_context()
        moved_teacher_table = next(
            table for table in moved_context["teacher_tables"]
            if table["teacher"].uid == self.teacher.uid
        )
        moved_room_table = next(
            table for table in moved_context["room_tables"]
            if table["room"].r_number == self.lecture_room.r_number
        )
        self.assertTrue(self._rows_have_class_at_slot(moved_teacher_table["rows"], "Monday", 2))
        self.assertTrue(self._rows_have_class_at_slot(moved_room_table["rows"], "Monday", 2))

        second_save_response = self.client.get(reverse("save_live_timetable", args=[1]))
        self.assertEqual(second_save_response.status_code, 200)
        second_live = LiveTimetable.objects.filter(user=self.user).order_by("-id").first()
        self.assertIsNotNone(second_live)
        self.assertNotEqual(second_live.id, first_live.id)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)

        second_context = self._load_live_projection_context(second_live.id)
        self._assert_live_projection_context(second_context)
        moved_teacher_table = next(
            table for table in second_context["teacher_tables"]
            if table["teacher"].uid == self.teacher.uid
        )
        moved_room_table = next(
            table for table in second_context["room_tables"]
            if table["room"].r_number == self.lecture_room.r_number
        )
        self.assertTrue(self._rows_have_class_at_slot(moved_teacher_table["rows"], "Monday", 2))
        self.assertTrue(self._rows_have_class_at_slot(moved_room_table["rows"], "Monday", 2))

    def test_live_timetable_move_updates_current_snapshot_for_reload_and_reopen(self):
        save_response = self.client.get(reverse("save_live_timetable", args=[1]))
        self.assertEqual(save_response.status_code, 200)
        live = LiveTimetable.objects.get(user=self.user)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        self._load_live_state(live.id)

        self._move_restored_class(1, 2)

        live.refresh_from_db()
        restored_state = views_other.deserialize_runtime_state_snapshot(live.snapshot)
        restored_classes = list(restored_state.get("classes") or [])
        moved_class = next(
            cls for cls in restored_classes
            if getattr(cls, "section", "") == self.section.section_id
            and getattr(getattr(cls, "subject", None), "subject_name", "") == self.theory_subject.subject_name
        )
        self.assertEqual(getattr(getattr(moved_class, "meeting_time", None), "day", None), "Monday")
        self.assertEqual(int(getattr(getattr(moved_class, "meeting_time", None), "time", 0) or 0), 2)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        reopened_state = self._load_live_state(live.id)
        reopened_classes = list(reopened_state.get("classes") or [])
        reopened_class = next(
            cls for cls in reopened_classes
            if getattr(cls, "section", "") == self.section.section_id
            and getattr(getattr(cls, "subject", None), "subject_name", "") == self.theory_subject.subject_name
        )
        self.assertEqual(getattr(getattr(reopened_class, "meeting_time", None), "day", None), "Monday")
        self.assertEqual(int(getattr(getattr(reopened_class, "meeting_time", None), "time", 0) or 0), 2)

        reopened_context = self._current_live_projection_context()
        reopened_teacher_table = next(
            table for table in reopened_context["teacher_tables"]
            if table["teacher"].uid == self.teacher.uid
        )
        reopened_room_table = next(
            table for table in reopened_context["room_tables"]
            if table["room"].r_number == self.lecture_room.r_number
        )
        self.assertTrue(self._rows_have_class_at_slot(reopened_teacher_table["rows"], "Monday", 2))
        self.assertTrue(self._rows_have_class_at_slot(reopened_room_table["rows"], "Monday", 2))

    def test_live_timetable_add_slot_updates_current_snapshot_for_reload_and_reopen(self):
        save_response = self.client.get(reverse("save_live_timetable", args=[1]))
        self.assertEqual(save_response.status_code, 200)
        live = LiveTimetable.objects.get(user=self.user)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        self._load_live_state(live.id)

        response = self.client.post(
            reverse("add_slot", args=[self.section.section_id]),
            {
                "day": "Monday",
                "slot": "2",
                "subject": str(self.theory_subject.pk),
                "teacher": str(self.teacher.pk),
                "room": str(self.lecture_room.pk),
            },
        )
        self.assertEqual(response.status_code, 302)

        live.refresh_from_db()
        restored_state = views_other.deserialize_runtime_state_snapshot(live.snapshot)
        restored_classes = list(restored_state.get("classes") or [])
        monday_slots = sorted(
            int(getattr(getattr(cls, "meeting_time", None), "time", 0) or 0)
            for cls in restored_classes
            if getattr(cls, "section", "") == self.section.section_id
            and getattr(getattr(cls, "meeting_time", None), "day", None) == "Monday"
            and getattr(getattr(cls, "subject", None), "subject_name", "") == self.theory_subject.subject_name
        )
        self.assertEqual(monday_slots, [1, 2])

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        reopened_state = self._load_live_state(live.id)
        reopened_classes = list(reopened_state.get("classes") or [])
        reopened_slots = sorted(
            int(getattr(getattr(cls, "meeting_time", None), "time", 0) or 0)
            for cls in reopened_classes
            if getattr(cls, "section", "") == self.section.section_id
            and getattr(getattr(cls, "meeting_time", None), "day", None) == "Monday"
            and getattr(getattr(cls, "subject", None), "subject_name", "") == self.theory_subject.subject_name
        )
        self.assertEqual(reopened_slots, [1, 2])

    def test_live_timetable_manual_bucket_create_updates_current_snapshot_for_reload_and_reopen(self):
        save_response = self.client.get(reverse("save_live_timetable", args=[1]))
        self.assertEqual(save_response.status_code, 200)
        live = LiveTimetable.objects.get(user=self.user)

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        self._load_live_state(live.id)

        response = self.client.post(
            reverse("generated_create_parking_slot", args=[self.section.section_id]),
            data=json.dumps(
                {
                    "subject_text": "Manual Live Slot",
                    "teacher_uid": self.teacher.uid,
                    "room_number": self.lecture_room.r_number,
                    "duration": 1,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        live.refresh_from_db()
        restored_state = views_other.deserialize_runtime_state_snapshot(live.snapshot)
        restored_parking = list(restored_state.get("generated_parking_items") or [])
        self.assertEqual(len(restored_parking), 1)
        restored_item = restored_parking[0].get("item")
        self.assertEqual(getattr(getattr(restored_item, "subject", None), "subject_name", ""), "Manual Live Slot")

        views_other._USER_STATE.pop(views_other._coerce_user_state_key(self.user.id), None)
        reopened_state = self._load_live_state(live.id)
        reopened_parking = list(reopened_state.get("generated_parking_items") or [])
        self.assertEqual(len(reopened_parking), 1)
        reopened_item = reopened_parking[0].get("item")
        self.assertEqual(getattr(getattr(reopened_item, "subject", None), "subject_name", ""), "Manual Live Slot")


class LiveTimetableLockTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="live_lock_user", password="testpass123")
        self.client.force_login(self.user)

        views_other.ensure_private_generator_loaded()

        self.department = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        self.section = Section.objects.create(section_id="SEC-LOCK", department=self.department, user=self.user)
        self.teacher = Instructor.objects.create(
            uid="LOCK-T1",
            name="Lock Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.department,
        )
        self.room = Room.objects.create(
            r_number="LH-LOCK",
            room_type="Lecture Hall",
            seating_capacity=80,
            department=self.department,
            user=self.user,
        )
        self.subject = Subject.objects.create(
            subject_number="TH-LOCK",
            subject_name="Lock Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            duration=1,
            user=self.user,
        )
        self.subject.instructors.add(self.teacher)
        self.section.allowed_subjects.add(self.subject)
        self.mt1 = MeetingTime.objects.create(pid="Mo1-lock", day="Monday", time="1", user=self.user)

        class_obj = views_other.Class(1, self.department, self.section.section_id, self.subject)
        class_obj.set_instructor(self.teacher)
        class_obj.set_room(self.room)
        class_obj.set_meetingTime(self.mt1)
        class_obj.meeting_times = [self.mt1]
        class_obj.duration = 1

        state = views_other._get_user_state(self.user.id)
        state["schedules"] = [{
            "classes": [class_obj],
            "labs": [],
            "stats": {},
            "reco_block": {},
        }]
        views_other._bind_runtime_to_schedule(state, 1)
        state["view_mode"] = "editing"

        snapshot = views_other._validate_live_timetable_snapshot(state)
        self.live = LiveTimetable.objects.create(
            user=self.user,
            name="Locked Snapshot",
            snapshot_version=int(snapshot.get("version") or 1),
            snapshot=snapshot,
        )

    def _message_texts(self, response):
        return [message.message for message in get_messages(response.wsgi_request)]

    def test_lock_persists_and_blocks_delete(self):
        lock_response = self.client.post(reverse("lock_live_timetable", args=[self.live.id]), follow=True)
        self.assertEqual(lock_response.status_code, 200)

        self.live.refresh_from_db()
        self.assertTrue(views_other._live_timetable_is_locked(self.live))
        self.assertTrue(any("locked" in message.lower() for message in self._message_texts(lock_response)))

        list_response = self.client.get(reverse("live_timetable_list"))
        self.assertContains(list_response, "Delete Locked")
        self.assertContains(list_response, "Locked")

        delete_response = self.client.get(reverse("delete_live_timetable", args=[self.live.id]), follow=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(LiveTimetable.objects.filter(id=self.live.id, user=self.user).exists())
        self.assertTrue(any("unlock it before deleting" in message.lower() for message in self._message_texts(delete_response)))

    def test_unlock_requires_exact_code_and_open_still_works(self):
        self.client.post(reverse("lock_live_timetable", args=[self.live.id]), follow=True)

        wrong_response = self.client.post(
            reverse("unlock_live_timetable", args=[self.live.id]),
            {"unlock_code": "wrong-code"},
            follow=True,
        )
        self.assertEqual(wrong_response.status_code, 200)
        self.live.refresh_from_db()
        self.assertTrue(views_other._live_timetable_is_locked(self.live))
        self.assertTrue(any("incorrect unlock code" in message.lower() for message in self._message_texts(wrong_response)))

        request = RequestFactory().get("/")
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        index, loaded_live = views_other.load_live_timetable_into_runtime(request, self.live.id)
        self.assertEqual(index, 1)
        self.assertEqual(loaded_live.id, self.live.id)

        unlock_response = self.client.post(
            reverse("unlock_live_timetable", args=[self.live.id]),
            {"unlock_code": "asdfgh985258"},
            follow=True,
        )
        self.assertEqual(unlock_response.status_code, 200)
        self.live.refresh_from_db()
        self.assertFalse(views_other._live_timetable_is_locked(self.live))
        self.assertTrue(any("unlocked" in message.lower() for message in self._message_texts(unlock_response)))

        delete_response = self.client.get(reverse("delete_live_timetable", args=[self.live.id]), follow=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(LiveTimetable.objects.filter(id=self.live.id, user=self.user).exists())


class TeacherWorkloadSlotCountingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="workload_user", password="testpass123")
        self.department = Department.objects.create(name="Computer Science", code="CS", user=self.user)

        self.teacher_a = Instructor.objects.create(
            uid="WA1",
            name="Teacher A",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.department,
        )
        self.teacher_b = Instructor.objects.create(
            uid="WB1",
            name="Teacher B",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.department,
        )

        views_other.ensure_private_generator_loaded()

    def _meeting_time(self, day, slot, key_prefix="mt"):
        return SimpleNamespace(day=day, time=str(slot), pk=f"{key_prefix}-{day}-{slot}", id=f"{key_prefix}-{day}-{slot}")

    def _room(self, number, pk=1):
        return SimpleNamespace(r_number=number, pk=pk, id=pk, department=self.department)

    def _subject(self, name, pk=1):
        return SimpleNamespace(subject_name=name, pk=pk, id=pk)

    def _class(self, teacher, day, slot, *, duration=1, section="S1", room=None, subject=None, co_instructors=None, elective=False):
        meeting_time = self._meeting_time(day, slot, key_prefix=f"cls-{section}")
        meeting_times = [self._meeting_time(day, int(slot) + offset, key_prefix=f"cls-{section}") for offset in range(duration)]
        return SimpleNamespace(
            instructor=teacher,
            co_instructors=list(co_instructors or []),
            meeting_time=meeting_time,
            meeting_times=meeting_times,
            duration=duration,
            section=section,
            room=room or self._room("LT-01", 101),
            subject=subject or self._subject("Theory", 201),
            department=self.department,
            second_instructor=None,
            is_elective=elective,
        )

    def _lab(self, teacher, slots, *, second_instructor=None, co_instructors=None, section="S1", room=None, subject=None, elective=False):
        meeting_times = [self._meeting_time(day, slot, key_prefix=f"lab-{section}") for day, slot in slots]
        return SimpleNamespace(
            instructor=teacher,
            second_instructor=second_instructor,
            co_instructors=list(co_instructors or []),
            meeting_times=meeting_times,
            duration=len(meeting_times),
            section=section,
            room=room or self._room("LAB-01", 301),
            subject=subject or self._subject("Lab", 401),
            department=self.department,
            is_elective=elective,
        )

    def _summary_for(self, teacher, classes=None, labs=None):
        workloads = views_other._compute_teacher_workloads(classes or [], labs or [])
        return workloads.get(teacher, {"lectures": 0, "labs": 0, "shared_labs": 0, "total": 0})

    def _teacher_table_workload_for(self, teacher, classes=None, labs=None):
        tables = views_other.build_teacher_tables(classes or [], labs or [], user=self.user)
        matching = next(table for table in tables if table["teacher"].pk == teacher.pk)
        return matching["workload"]

    def test_workload_counts_unique_occupied_slots_across_all_paths(self):
        shared_room = self._room("LT-01", 501)
        shared_subject = self._subject("Shared Session", 601)

        one_class = [self._class(self.teacher_a, "Monday", 1)]
        self.assertEqual(self._summary_for(self.teacher_a, one_class)["total"], 1)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, one_class)["total"], 1)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, one_class, []), 1)

        two_slots = [
            self._class(self.teacher_a, "Monday", 1),
            self._class(self.teacher_a, "Monday", 2),
        ]
        self.assertEqual(self._summary_for(self.teacher_a, two_slots)["total"], 2)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, two_slots)["total"], 2)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, two_slots, []), 2)

        same_session_two_sections = [
            self._class(self.teacher_a, "Monday", 1, section="CE31", room=shared_room, subject=shared_subject),
            self._class(self.teacher_a, "Monday", 1, section="CE32", room=shared_room, subject=shared_subject),
        ]
        self.assertEqual(self._summary_for(self.teacher_a, same_session_two_sections)["total"], 1)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, same_session_two_sections)["total"], 1)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, same_session_two_sections, []), 1)

        elective_duplicate_records = [
            self._class(self.teacher_a, "Monday", 3, section="CE31", room=shared_room, subject=shared_subject, elective=True),
            self._class(self.teacher_a, "Monday", 3, section="CE32", room=shared_room, subject=shared_subject, elective=True),
        ]
        self.assertEqual(self._summary_for(self.teacher_a, elective_duplicate_records)["total"], 1)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, elective_duplicate_records)["total"], 1)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, elective_duplicate_records, []), 1)

        repeated_records_same_slot = [
            self._class(self.teacher_a, "Tuesday", 4, section="CE31", room=shared_room, subject=shared_subject),
            self._class(self.teacher_a, "Tuesday", 4, section="CE31", room=shared_room, subject=shared_subject),
        ]
        self.assertEqual(self._summary_for(self.teacher_a, repeated_records_same_slot)["total"], 1)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, repeated_records_same_slot)["total"], 1)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, repeated_records_same_slot, []), 1)

        two_slot_class = [self._class(self.teacher_a, "Wednesday", 3, duration=2)]
        self.assertEqual(self._summary_for(self.teacher_a, two_slot_class)["lectures"], 2)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, two_slot_class)["lectures"], 2)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, two_slot_class, []), 2)

        three_slot_lab = [self._lab(self.teacher_a, [("Thursday", 1), ("Thursday", 2), ("Thursday", 3)])]
        self.assertEqual(self._summary_for(self.teacher_a, labs=three_slot_lab)["labs"], 3)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, labs=three_slot_lab)["labs"], 3)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, [], three_slot_lab), 3)

        parallel_lab_same_session = [
            self._lab(self.teacher_a, [("Friday", 1), ("Friday", 2)], section="CE31", room=self._room("LAB-01", 701), subject=self._subject("Parallel Lab", 801)),
            self._lab(self.teacher_a, [("Friday", 1), ("Friday", 2)], section="CE32", room=self._room("LAB-01", 701), subject=self._subject("Parallel Lab", 801)),
        ]
        self.assertEqual(self._summary_for(self.teacher_a, labs=parallel_lab_same_session)["labs"], 2)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, labs=parallel_lab_same_session)["labs"], 2)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, [], parallel_lab_same_session), 2)

        co_instructor_class = [self._class(self.teacher_b, "Monday", 6, co_instructors=[self.teacher_a])]
        self.assertEqual(self._summary_for(self.teacher_a, co_instructor_class)["lectures"], 1)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, co_instructor_class)["lectures"], 1)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, co_instructor_class, []), 1)

        second_instructor_lab = [self._lab(self.teacher_b, [("Tuesday", 7), ("Tuesday", 8)], second_instructor=self.teacher_a)]
        self.assertEqual(self._summary_for(self.teacher_a, labs=second_instructor_lab)["shared_labs"], 2)
        self.assertEqual(self._teacher_table_workload_for(self.teacher_a, labs=second_instructor_lab)["shared_labs"], 2)
        self.assertEqual(views_other._compute_teacher_workload(self.teacher_a, [], second_instructor_lab), 2)


class TeacherTimetableDepartmentFilterTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="teacher_filter_user", password="testpass123")
        self.cse = Department.objects.create(name="Computer Science", code="CSE", user=self.user)
        self.ece = Department.objects.create(name="Electronics", code="ECE", user=self.user)

        self.cse_teacher = Instructor.objects.create(
            uid="CSE-T1",
            name="CSE Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.cse,
        )
        self.ece_teacher = Instructor.objects.create(
            uid="ECE-T1",
            name="ECE Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
            department=self.ece,
        )

        views_other.ensure_private_generator_loaded()

    def _meeting_time(self, day, slot, key_prefix="mt"):
        return SimpleNamespace(day=day, time=str(slot), pk=f"{key_prefix}-{day}-{slot}", id=f"{key_prefix}-{day}-{slot}")

    def _room(self, number, department, pk=1):
        return SimpleNamespace(r_number=number, pk=pk, id=pk, department=department)

    def _subject(self, name, pk=1):
        return SimpleNamespace(subject_name=name, pk=pk, id=pk)

    def _class(self, teacher, department, day, slot, *, section="S1", room=None, subject=None):
        meeting_time = self._meeting_time(day, slot, key_prefix=f"cls-{section}")
        return SimpleNamespace(
            instructor=teacher,
            co_instructors=[],
            second_instructor=None,
            meeting_time=meeting_time,
            meeting_times=[meeting_time],
            duration=1,
            section=section,
            room=room or self._room("LT-01", department, 101),
            subject=subject or self._subject("Theory", 201),
            department=department,
        )

    def test_teacher_department_filter_uses_home_department_not_taught_department(self):
        classes = [
            self._class(self.cse_teacher, self.cse, "Monday", 1, section="CSE-1"),
            self._class(self.ece_teacher, self.cse, "Monday", 2, section="CSE-2"),
        ]
        teacher_tables = views_other.build_teacher_tables(classes, [], user=self.user)
        fallback_map = views_other._teacher_home_dept_fallback(classes, [])

        cse_table = next(table for table in teacher_tables if table["teacher"].pk == self.cse_teacher.pk)
        ece_table = next(table for table in teacher_tables if table["teacher"].pk == self.ece_teacher.pk)

        self.assertEqual(cse_table["home_dept_code"], "CSE")
        self.assertEqual(ece_table["home_dept_code"], "ECE")
        self.assertIn("CSE", ece_table["dept_codes"])
        self.assertTrue(any(cell.get("classes") for row in ece_table["rows"] for cell in row["cells"]))

        cse_visible = views_other._filter_teacher_tables_by_department(teacher_tables, "CSE", fallback_map)
        ece_visible = views_other._filter_teacher_tables_by_department(teacher_tables, "ECE", fallback_map)

        self.assertEqual([table["teacher"].pk for table in cse_visible], [self.cse_teacher.pk])
        self.assertEqual([table["teacher"].pk for table in ece_visible], [self.ece_teacher.pk])
        self.assertTrue(any(cell.get("classes") for row in ece_visible[0]["rows"] for cell in row["cells"]))


class ElectiveSchedulingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="elective_test",
            password="testpass123",
        )
        self.department = Department.objects.create(name="Computer Science", code="CS", user=self.user)

        for room_number in ["LH-1", "LH-2"]:
            Room.objects.create(
                r_number=room_number,
                room_type="Lecture Hall",
                seating_capacity=60,
                department=self.department,
                user=self.user,
            )
        Room.objects.create(
            r_number="LAB-1",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="CAT-A",
            user=self.user,
        )

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            for slot in ["1", "2", "3", "4", "6", "7", "8", "9"]:
                MeetingTime.objects.create(
                    pid=f"{day[:2]}{slot}",
                    day=day,
                    time=slot,
                    user=self.user,
                )

    def test_elective_theory_mirrors_to_linked_sections(self):
        section_a = Section.objects.create(section_id="A", department=self.department, user=self.user)
        Section.objects.create(section_id="B", department=self.department, user=self.user)
        Section.objects.create(section_id="C", department=self.department, user=self.user)
        teacher = Instructor.objects.create(
            uid="ET001",
            name="Elective Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="EL101",
            subject_name="Elective Maths",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject.instructors.add(teacher)
        section_a.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section_a, subject=subject).update(
            group_count=1,
            elective_section_ids="B;C",
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        elective_classes = [cls for cls in schedule.get_classes() if cls.subject == subject]
        self.assertEqual(len(elective_classes), 3)
        self.assertEqual({cls.section for cls in elective_classes}, {"A", "B", "C"})
        self.assertEqual(len({(cls.meeting_time.day, cls.meeting_time.time) for cls in elective_classes}), 1)
        self.assertEqual(len({cls.room.r_number for cls in elective_classes}), 1)
        self.assertEqual(len({cls.instructor.uid for cls in elective_classes}), 1)

    def test_grouped_elective_theory_can_run_parallel(self):
        section_a = Section.objects.create(section_id="A", department=self.department, user=self.user)
        Section.objects.create(section_id="B", department=self.department, user=self.user)
        teacher_one = Instructor.objects.create(
            uid="ET101",
            name="Elective Teacher 1",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        teacher_two = Instructor.objects.create(
            uid="ET102",
            name="Elective Teacher 2",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject_one = Subject.objects.create(
            subject_number="EL201",
            subject_name="Elective One",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject_two = Subject.objects.create(
            subject_number="EL202",
            subject_name="Elective Two",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject_one.instructors.add(teacher_one)
        subject_two.instructors.add(teacher_two)
        section_a.allowed_subjects.add(subject_one, subject_two)
        SectionSubjectMapping.objects.filter(section=section_a, subject=subject_one).update(
            group_count=2,
            elective_section_ids="B",
        )
        SectionSubjectMapping.objects.filter(section=section_a, subject=subject_two).update(
            group_count=2,
            elective_section_ids="B",
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        grouped_classes = [cls for cls in schedule.get_classes() if cls.subject in {subject_one, subject_two}]
        self.assertEqual(len(grouped_classes), 8)

        parallel_slots = {}
        for cls in grouped_classes:
            key = (cls.section, cls.meeting_time.day, cls.meeting_time.time)
            parallel_slots.setdefault(key, set()).add(cls.subject.subject_number)

        self.assertTrue(any(len(subjects) == 2 for subjects in parallel_slots.values()))

        subject_slot_sections = {}
        for cls in grouped_classes:
            key = (cls.subject.subject_number, cls.meeting_time.day, cls.meeting_time.time)
            subject_slot_sections.setdefault(key, []).append(cls)

        for classes_at_slot in subject_slot_sections.values():
            self.assertEqual({cls.section for cls in classes_at_slot}, {"A", "B"})
            self.assertEqual(len({cls.room.r_number for cls in classes_at_slot}), 1)
            self.assertEqual(len({cls.instructor.uid for cls in classes_at_slot}), 1)

    def test_elective_lab_mirrors_to_linked_sections(self):
        section_a = Section.objects.create(section_id="A", department=self.department, user=self.user)
        Section.objects.create(section_id="B", department=self.department, user=self.user)
        teacher = Instructor.objects.create(
            uid="ELAB1",
            name="Elective Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="ELLAB1",
            subject_name="Elective Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="CAT-A",
            classes_per_week=1,
            duration=2,
            user=self.user,
        )
        subject.instructors.add(teacher)
        section_a.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section_a, subject=subject).update(
            group_count=1,
            elective_section_ids="B",
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        labs = [lab for lab in schedule.get_labs() if lab.subject == subject]
        self.assertEqual(len(labs), 2)
        self.assertEqual({lab.section for lab in labs}, {"A", "B"})

    def test_expected_theory_count_includes_elective_theory_for_linked_sections(self):
        section_a = Section.objects.create(section_id="EA", department=self.department, user=self.user)
        Section.objects.create(section_id="EB", department=self.department, user=self.user)
        teacher = Instructor.objects.create(
            uid="ET201",
            name="Elective Count Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="EL301",
            subject_name="Counted Elective",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=2,
            user=self.user,
        )
        subject.instructors.add(teacher)
        section_a.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section_a, subject=subject).update(
            group_count=1,
            elective_section_ids="EB",
        )

        views_other.data = views_other.Data()
        schedule = views_other.Schedule()

        self.assertEqual(schedule._expected_theory_count(), 4)


class RecheckScheduleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="recheck_test",
            password="testpass123",
        )
        self.department = Department.objects.create(name="Math", code="MATH", user=self.user)

        self.room_a = Room.objects.create(
            r_number="LH-A",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        self.room_b = Room.objects.create(
            r_number="LH-B",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
            user=self.user,
        )
        Room.objects.create(
            r_number="LAB-A",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
            lab_category="MATH LAB",
            user=self.user,
        )

        for day, slots in {"Monday": ["1"], "Tuesday": ["1"]}.items():
            for slot in slots:
                MeetingTime.objects.create(
                    pid=f"{day[:2]}{slot}",
                    day=day,
                    time=slot,
                    user=self.user,
                )

    def test_recheck_can_shift_single_lecture_to_place_missing_subject(self):
        section = Section.objects.create(section_id="Math-A", department=self.department, user=self.user)
        other_section = Section.objects.create(section_id="Math-B", department=self.department, user=self.user)

        teacher_a = Instructor.objects.create(
            uid="RA001",
            name="Teacher A",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        teacher_b = Instructor.objects.create(
            uid="RA002",
            name="Teacher B",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )

        subject_a = Subject.objects.create(
            subject_number="MAT101",
            subject_name="Moveable Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject_b = Subject.objects.create(
            subject_number="MAT102",
            subject_name="Missing Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject_c = Subject.objects.create(
            subject_number="MAT103",
            subject_name="Teacher Blocker",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        subject_a.instructors.add(teacher_a)
        subject_b.instructors.add(teacher_b)
        subject_c.instructors.add(teacher_b)
        section.allowed_subjects.add(subject_a, subject_b)
        other_section.allowed_subjects.add(subject_c)

        monday = MeetingTime.objects.get(user=self.user, day="Monday", time="1")
        tuesday = MeetingTime.objects.get(user=self.user, day="Tuesday", time="1")

        views_other.data = views_other.Data(self.user)
        schedule = views_other.Schedule()

        cls_a = views_other.Class(0, self.department, section.section_id, subject_a)
        cls_a.set_instructor(teacher_a)
        cls_a.set_meetingTime(monday)
        cls_a.meeting_times = [monday]
        cls_a.set_room(self.room_a)

        cls_c = views_other.Class(1, self.department, other_section.section_id, subject_c)
        cls_c.set_instructor(teacher_b)
        cls_c.set_meetingTime(tuesday)
        cls_c.meeting_times = [tuesday]
        cls_c.set_room(self.room_b)

        schedule._classes = [cls_a, cls_c]
        schedule._classNumb = 2
        schedule.recheck(max_rounds=2)

        assigned_target = [
            cls for cls in schedule.get_classes()
            if cls.section == section.section_id and cls.subject == subject_b
        ]
        current_slots = {
            (cls.section, cls.subject.subject_number): (cls.meeting_time.day, cls.meeting_time.time)
            for cls in schedule.get_classes()
        }

        self.assertEqual(len(assigned_target), 1)
        self.assertTrue(
            current_slots[(section.section_id, subject_a.subject_number)] != ("Monday", "1")
            or current_slots[(other_section.section_id, subject_c.subject_number)] != ("Tuesday", "1")
        )

    def test_recheck_does_not_force_lab_without_matching_category(self):
        section = Section.objects.create(section_id="Math-Lab", department=self.department, user=self.user)
        teacher = Instructor.objects.create(
            uid="RL001",
            name="Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="MATLAB1",
            subject_name="Unavailable Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            required_lab_category="BET Lab",
            classes_per_week=2,
            duration=2,
            user=self.user,
        )
        subject.instructors.add(teacher)
        section.allowed_subjects.add(subject)

        views_other.data = views_other.Data(self.user)
        schedule = views_other.Schedule()
        schedule.recheck(max_rounds=2)

        self.assertEqual(
            [lab for lab in schedule.get_labs() if lab.section == section.section_id and lab.subject == subject],
            [],
        )


class AddDepartmentViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="deptadmin",
            password="testpass123",
        )

    def test_second_department_can_be_added(self):
        self.client.login(username="deptadmin", password="testpass123")
        Department.objects.create(name="Computer Science", code="CS", user=self.user)

        response = self.client.post(
            reverse("addDepts"),
            {
                "name": "Mechanical Engineering",
                "code": "ME",
                "add_department": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("addDepts"))
        self.assertEqual(Department.objects.count(), 2)
        self.assertTrue(Department.objects.filter(code="ME", name="Mechanical Engineering").exists())

    def test_data_loads_multiple_departments(self):
        cs = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        me = Department.objects.create(name="Mechanical Engineering", code="ME", user=self.user)

        Room.objects.create(
            r_number="CS-LH",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=cs,
            user=self.user,
        )
        Room.objects.create(
            r_number="ME-LH",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=me,
            user=self.user,
        )

        subject_cs = Subject.objects.create(
            subject_number="CS101",
            subject_name="Algorithms",
            department=cs,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        subject_me = Subject.objects.create(
            subject_number="ME101",
            subject_name="Thermodynamics",
            department=me,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )

        section_cs = Section.objects.create(section_id="CS-A", department=cs, user=self.user)
        section_me = Section.objects.create(section_id="ME-A", department=me, user=self.user)
        section_cs.allowed_subjects.add(subject_cs)
        section_me.allowed_subjects.add(subject_me)

        data = views.Data()

        self.assertEqual({dept.code for dept in data.get_depts()}, {"CS", "ME"})
        self.assertEqual({section.section_id for section in data.get_sections()}, {"CS-A", "ME-A"})
        self.assertEqual(
            {subject.subject_number for subject in data.get_department_subjects(cs)},
            {"CS101"},
        )
        self.assertEqual(
            {subject.subject_number for subject in data.get_department_subjects(me)},
            {"ME101"},
        )

    def test_map_section_subjects_csv_persists_group_count(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Chemistry", code="CHE", user=self.user)
        subject = Subject.objects.create(
            subject_number="CH-105 B",
            subject_name="Organic Chemistry Lab",
            department=department,
            max_numb_students=60,
            room_required="Lab",
            classes_per_week=1,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="MSCCHE(Isem)",
            department=department,
            user=self.user,
        )

        csv_content = (
            "section_id,subject_number,group_count,elective_section_id\n"
            "MSCCHE(Isem),CH-105 B,2,\n"
        )
        upload = SimpleUploadedFile("section_subjects.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("map_section_subjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("map_section_subjects"))
        mapping = SectionSubjectMapping.objects.get(section=section, subject=subject)
        self.assertEqual(mapping.group_count, 2)
        self.assertEqual(mapping.elective_section_ids, "")

    def test_add_subjects_csv_reports_row_level_validation_details(self):
        self.client.login(username="deptadmin", password="testpass123")
        Department.objects.create(name="Chemistry", code="CHE", user=self.user)

        csv_content = (
            "department_code,subject_number,subject_name,room_required,lab_category_required,classes_per_week\n"
            "CHE,CHE101,Valid Theory,Lecture Hall,,3\n"
            "BAD,CHE102,Bad Department,Lecture Hall,,3\n"
            "CHE,CHE103,Bad Lab,Lab,,1\n"
        )
        upload = SimpleUploadedFile("subjects.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("addSubjects"),
            {"csv_upload": "1", "csv_file": upload},
            follow=True,
        )

        self.assertTrue(Subject.objects.filter(user=self.user, subject_number="CHE101").exists())
        self.assertFalse(Subject.objects.filter(user=self.user, subject_number="CHE102").exists())
        self.assertFalse(Subject.objects.filter(user=self.user, subject_number="CHE103").exists())

        message_texts = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("1 subjects uploaded successfully! 2 skipped.", message_texts)
        self.assertIn("Row 3: department_code 'BAD' does not exist", message_texts)
        self.assertIn("Row 4: subject 'CHE103' is Lab but required_lab_category is blank", message_texts)

    def test_add_subjects_csv_trims_duration_header_whitespace(self):
        self.client.login(username="deptadmin", password="testpass123")
        Department.objects.create(name="Computer Science and Engg", code="CSE", user=self.user)

        csv_content = (
            "department_code,subject_number,subject_name,room_required,lab_category_required,specific_equipment/software_lab,classes_per_week,max_numb_students,duration \n"
            "CSE,PCC-CS-302,IT Workshop,LAB,Computer Lab,,1,,4\n"
        )
        upload = SimpleUploadedFile("subjects.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("addSubjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        subject = Subject.objects.get(user=self.user, subject_number="PCC-CS-302")
        self.assertEqual(subject.duration, 4)

    def test_add_rooms_csv_reports_row_level_validation_details(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Chemistry", code="CHE", user=self.user)

        csv_content = (
            "r_number,department,seating_capacity,room_type,lab_category\n"
            "LAB-1,CHE,30,Lab,CAT-A\n"
            "LAB-2,UNKNOWN,30,Lab,CAT-A\n"
            "LAB-3,CHE,abc,Lab,CAT-A\n"
        )
        upload = SimpleUploadedFile("rooms.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("addRooms"),
            {"csv_upload": "1", "csv_file": upload},
            follow=True,
        )

        self.assertTrue(Room.objects.filter(user=self.user, r_number="LAB-1", department=department).exists())
        self.assertFalse(Room.objects.filter(user=self.user, r_number="LAB-2").exists())
        self.assertFalse(Room.objects.filter(user=self.user, r_number="LAB-3").exists())

        message_texts = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("1 room(s) added from CSV! 2 skipped.", message_texts)
        self.assertIn("Row 3: department 'UNKNOWN' not found", message_texts)
        self.assertIn("Row 4: seating_capacity 'abc' is not a whole number", message_texts)

    def test_add_sections_csv_accepts_section_strength_header_without_500(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Computer Science and Engg", code="CSE", user=self.user)

        csv_content = (
            "section_id,program_name,department_code,section_strength\n"
            "CSE11 1ST SEM,Computer Science and Engg,CSE,70\n"
            "CSE12 1ST SEM,Computer Science and Engg,CSE,70\n"
        )
        upload = SimpleUploadedFile("sections.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("addSections"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("addSections"))
        self.assertTrue(Section.objects.filter(user=self.user, section_id="CSE11 1ST SEM", department=department).exists())
        self.assertTrue(Section.objects.filter(user=self.user, section_id="CSE12 1ST SEM", department=department).exists())


class GenerationSelectionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="deptadmin",
            password="testpass123",
        )

    def test_private_generator_prefers_more_complete_schedule_over_higher_fitness(self):
        private_views_main = views._load_external_views_main()

        class FakeSchedule:
            def __init__(self, class_count, lab_count, fitness):
                self._classes = [object()] * class_count
                self._labs = [object()] * lab_count
                self._fitness = fitness

            def get_classes(self):
                return self._classes

            def get_labs(self):
                return self._labs

            def get_fitness(self):
                return self._fitness

        less_complete = FakeSchedule(class_count=151, lab_count=36, fitness=0.01)
        more_complete = FakeSchedule(class_count=155, lab_count=36, fitness=0.005)

        chosen = private_views_main._pick_best_generated_schedule([less_complete, more_complete])

        self.assertIs(chosen, more_complete)

    def test_private_generator_selection_prioritizes_hard_slot_conflict_free_schedule(self):
        private_views_main = views._load_external_views_main()

        class FakeMeetingTime:
            def __init__(self, day, time):
                self.day = day
                self.time = time

        class FakeEvent:
            def __init__(self, section, day, time, is_elective=False):
                self.section = section
                self.meeting_time = FakeMeetingTime(day, time)
                self.meeting_times = [self.meeting_time]
                self.is_elective = is_elective

        class FakeSchedule:
            def __init__(self, classes, labs, fitness):
                self._classes = classes
                self._labs = labs
                self._fitness = fitness

            def get_classes(self):
                return self._classes

            def get_labs(self):
                return self._labs

            def get_fitness(self):
                return self._fitness

        conflict_schedule = FakeSchedule(
            classes=[],
            labs=[
                FakeEvent("SEC-A", "Monday", "1"),
                FakeEvent("SEC-A", "Monday", "1"),
            ],
            fitness=0.02,
        )
        clean_schedule = FakeSchedule(
            classes=[],
            labs=[FakeEvent("SEC-A", "Monday", "1")],
            fitness=0.01,
        )

        chosen = private_views_main._pick_best_generated_schedule([conflict_schedule, clean_schedule])

        self.assertIs(chosen, clean_schedule)

    def test_private_generator_selection_allows_parallel_elective_overlap(self):
        private_views_main = views._load_external_views_main()

        class FakeMeetingTime:
            def __init__(self, day, time):
                self.day = day
                self.time = time

        class FakeEvent:
            def __init__(self, section, day, time, is_elective=False):
                self.section = section
                self.meeting_time = FakeMeetingTime(day, time)
                self.meeting_times = [self.meeting_time]
                self.is_elective = is_elective

        class FakeSchedule:
            def __init__(self, classes, labs, fitness):
                self._classes = classes
                self._labs = labs
                self._fitness = fitness

            def get_classes(self):
                return self._classes

            def get_labs(self):
                return self._labs

            def get_fitness(self):
                return self._fitness

        elective_parallel = FakeSchedule(
            classes=[
                FakeEvent("SEC-A", "Monday", "1", is_elective=True),
                FakeEvent("SEC-A", "Monday", "1", is_elective=True),
            ],
            labs=[],
            fitness=0.02,
        )
        single_event = FakeSchedule(
            classes=[FakeEvent("SEC-A", "Monday", "1", is_elective=True)],
            labs=[],
            fitness=0.01,
        )

        chosen = private_views_main._pick_best_generated_schedule([elective_parallel, single_event])

        self.assertIs(chosen, elective_parallel)

    def test_schedule_initialize_prefers_more_complete_labs_when_theory_counts_tie(self):
        class FakeItem:
            def __init__(self):
                self.co_instructors = []

        payloads = [
            {"classes": [FakeItem() for _ in range(5)], "labs": [FakeItem() for _ in range(1)]},
            {"classes": [FakeItem() for _ in range(5)], "labs": [FakeItem() for _ in range(3)]},
        ]
        call_index = {"value": 0}
        views_other.data = views_other.Data()

        def fake_initialize_labs(schedule):
            payload = payloads[call_index["value"]]
            schedule._labs = list(payload["labs"])

        def fake_initialize_classes(schedule):
            payload = payloads[call_index["value"]]
            schedule._classes = list(payload["classes"])
            call_index["value"] += 1

        with patch.object(views_other.Schedule, "initialize_labs", fake_initialize_labs), patch.object(
            views_other.Schedule, "initialize_classes_v2", fake_initialize_classes
        ), patch.object(views_other.Schedule, "_expected_theory_count", return_value=99), patch.object(
            views_other.Schedule, "_expected_lab_count", return_value=99
        ), patch.object(views_other.Schedule, "_initialize_electives", return_value=None), patch.object(
            views_other.Schedule, "recheck", return_value=False
        ), patch.object(views_other.Schedule, "_log_schedule_summary", return_value=None), patch.object(
            views_other.Schedule, "get_fitness", return_value=0.0
        ), patch.dict(views_other.__dict__, {"INITIALIZE_SCHEDULE_PASSES": 2}, clear=False):
            schedule = views_other.Schedule().initialize()

        self.assertEqual(len(schedule.get_classes()), 5)
        self.assertEqual(len(schedule.get_labs()), 3)

    def test_map_section_subjects_csv_persists_elective_section_ids(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Chemistry", code="CHE", user=self.user)
        subject = Subject.objects.create(
            subject_number="CH-106 B",
            subject_name="Inorganic Chemistry",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=1,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="MSCCHE(Isem)",
            department=department,
            user=self.user,
        )

        csv_content = (
            "section_id,subject_number,group_count,elective_section_id\n"
            "MSCCHE(Isem),CH-106 B,2,MSCCHE(IIIsem);MSCCHE(Vsem)\n"
        )
        upload = SimpleUploadedFile("section_subjects.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("map_section_subjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        mapping = SectionSubjectMapping.objects.get(section=section, subject=subject)
        self.assertEqual(mapping.group_count, 2)
        self.assertEqual(mapping.elective_section_ids, "MSCCHE(IIIsem);MSCCHE(Vsem)")

    def test_map_section_subjects_manual_form_persists_group_count(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Chemistry", code="CHE", user=self.user)
        subject = Subject.objects.create(
            subject_number="CH-106 B",
            subject_name="Inorganic Chemistry Lab",
            department=department,
            max_numb_students=60,
            room_required="Lab",
            classes_per_week=1,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="MSCCHE(IIIsem)",
            department=department,
            user=self.user,
        )

        response = self.client.post(
            reverse("map_section_subjects"),
            {
                "manual_add": "1",
                "section_id": section.section_id,
                "subjects": [str(subject.id)],
                "group_count": "3",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("map_section_subjects"))
        mapping = SectionSubjectMapping.objects.get(section=section, subject=subject)
        self.assertEqual(mapping.group_count, 3)

    def test_add_subjects_csv_persists_specific_rooms(self):
        self.client.login(username="deptadmin", password="testpass123")
        Department.objects.create(name="Chemistry", code="CHE", user=self.user)
        csv_content = (
            "department_code,subject_number,subject_name,room_required,lab_category_required,specific_equipment/software_lab,duration (in hr),classes_per_week\n"
            "CHE,CHE101,Locked Lab,LAB,CAT-A,LAB-42; LAB-43,2,1\n"
        )
        upload = SimpleUploadedFile("subjects.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("addSubjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        subject = Subject.objects.get(user=self.user, subject_number="CHE101")
        self.assertEqual(subject.specific_rooms, "LAB-42;LAB-43")
        self.assertEqual(subject.duration, 2)
        self.assertEqual(subject.required_lab_category, "CAT-A")

    def test_map_teacher_subjects_csv_persists_group_teacher_lists(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Chemistry", code="CHE", user=self.user)
        section = Section.objects.create(section_id="MSCCHE(Isem)", department=department, user=self.user)
        subject = Subject.objects.create(
            subject_number="CH-105 B",
            subject_name="Organic Chemistry Lab",
            department=department,
            max_numb_students=60,
            room_required="Lab",
            classes_per_week=1,
            user=self.user,
        )
        section.allowed_subjects.add(subject)
        SectionSubjectMapping.objects.filter(section=section, subject=subject).update(group_count=2)

        teacher_one = Instructor.objects.create(uid="T001", name="Teacher 1", designation="Assistant Professor", max_workload=25, user=self.user)
        teacher_two = Instructor.objects.create(uid="T002", name="Teacher 2", designation="Assistant Professor", max_workload=25, user=self.user)
        teacher_three = Instructor.objects.create(uid="T003", name="Teacher 3", designation="Assistant Professor", max_workload=25, user=self.user)

        csv_content = (
            "section_id,subject_number,instructor_uid,shared_lab,second_instructor_uid\n"
            "MSCCHE(Isem),CH-105 B,T001;T002,true,;T003\n"
        )
        upload = SimpleUploadedFile("teacher_map.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("map_teacher_subjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("map_teacher_subjects"))
        mapping = SectionSubjectInstructor.objects.get(section=section, subject=subject)
        self.assertEqual(mapping.group_instructor_ids, [teacher_one.id, teacher_two.id])
        self.assertEqual(mapping.group_second_instructor_ids, [None, teacher_three.id])

    def test_map_teacher_subjects_accepts_instructor_name_in_csv(self):
        from .models import SectionSubjectInstructor
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        instructor = Instructor.objects.create(
            uid="T9001",
            name="Anita Sharma",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        subject = Subject.objects.create(
            subject_number="CS500",
            subject_name="Compiler Design",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        section = Section.objects.create(
            section_id="CS-Test",
            department=department,
            user=self.user,
        )

        csv_content = "section_id,subject_number,instructor_uid\nCS-Test,CS500,Anita Sharma\n"
        upload = SimpleUploadedFile("teacher_map.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("map_teacher_subjects"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("map_teacher_subjects"))
        self.assertTrue(
            SectionSubjectInstructor.objects.filter(
                section=section, subject=subject, instructor=instructor
            ).exists()
        )

    def test_new_section_can_clone_subjects_from_similar_existing_section(self):
        department = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        subject_one = Subject.objects.create(
            subject_number="CS215",
            subject_name="Mathematics-I",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        subject_two = Subject.objects.create(
            subject_number="CS216",
            subject_name="Chemistry",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )

        template_section = Section.objects.create(section_id="IT 1st Sem", department=department, user=self.user)
        template_section.allowed_subjects.add(subject_one, subject_two)

        new_section = Section.objects.create(section_id="IT 1st Sem A", department=department, user=self.user)

        matched = views_other.clone_section_subjects_from_similar(new_section)

        self.assertEqual(matched, template_section)
        self.assertEqual(
            set(new_section.allowed_subjects.values_list("subject_number", flat=True)),
            {"CS215", "CS216"},
        )

    def test_new_section_without_static_rule_is_not_skipped_by_scheduler(self):
        department = Department.objects.create(name="Computer Science", code="CS", user=self.user)
        Room.objects.create(
            r_number="NH-1",
            room_type="Lecture Hall",
            seating_capacity=70,
            department=department,
            user=self.user,
        )
        Room.objects.create(
            r_number="NLab-1",
            room_type="Lab",
            seating_capacity=35,
            department=department,
            user=self.user,
        )

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            for slot in ["1", "2", "3", "4", "6", "7", "8", "9"]:
                MeetingTime.objects.get_or_create(
                    pid=f"N{day[:2]}{slot}",
                    defaults={"day": day, "time": slot, "user": self.user},
                )

        theory_teacher = Instructor.objects.create(
            uid="NS001",
            name="New Section Theory",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )
        lab_teacher = Instructor.objects.create(
            uid="NS002",
            name="New Section Lab",
            designation="Assistant Professor",
            max_workload=25,
            user=self.user,
        )

        theory_subject = Subject.objects.create(
            subject_number="NS101",
            subject_name="Intro Programming",
            department=department,
            max_numb_students=70,
            room_required="Lecture Hall",
            classes_per_week=3,
            user=self.user,
        )
        theory_subject.instructors.add(theory_teacher)

        lab_subject = Subject.objects.create(
            subject_number="NS102",
            subject_name="Programming Lab",
            department=department,
            max_numb_students=35,
            room_required="Lab",
            classes_per_week=4,
            user=self.user,
        )
        lab_subject.instructors.add(lab_teacher)

        section = Section.objects.create(
            section_id="New Section X",
            department=department,
            student_strength=35,
            user=self.user,
        )
        section.allowed_subjects.add(theory_subject, lab_subject)

        views_other.data = views_other.Data()
        schedule = views_other.Schedule().initialize()

        section_classes = [cls for cls in schedule.get_classes() if cls.section == "New Section X"]
        section_labs = [lab for lab in schedule.get_labs() if lab.section == "New Section X"]

        self.assertTrue(section_classes or section_labs)
