from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from . import views
from . import views_other
from .models import Subject, Department, Instructor, MeetingTime, Room, Section, SectionSubjectInstructor, SectionSubjectMapping


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
        self.assertEqual(
            compact_subject_counts,
            [
                {"name": "Solo Lab", "count": 1, "required": 1, "missing": 0, "is_lab": True},
                {"name": "Theory 1", "count": 2, "required": 2, "missing": 0, "is_lab": False},
                {"name": "Theory 2", "count": 1, "required": 2, "missing": 1, "is_lab": False},
                {"name": "Theory 3", "count": 0, "required": 2, "missing": 2, "is_lab": False},
                {"name": "Theory 4", "count": 0, "required": 2, "missing": 2, "is_lab": False},
                {"name": "Theory 5", "count": 0, "required": 1, "missing": 1, "is_lab": False},
            ],
        )
        self.assertEqual(test_table["total_missing_classes"], 6)

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
        extra_lab_subject.instructors.add(self.section.allowed_subjects.get(subject_number="LAB001").instructors.first())
        self.section.allowed_subjects.add(extra_lab_subject)

        views_other.data = views_other.Data()
        tables = views_other.build_section_tables([], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")

        missed_lab = next(lab for lab in test_table["missed_labs"] if lab["name"] == "Missed Lab")

        self.assertEqual(missed_lab["missing"], 1)
        self.assertEqual(missed_lab["reason"], "Required lab category unavailable")

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

        def room_pool(required_category=None):
            if required_category == "CAT-A":
                return [room_a]
            if required_category == "CAT-B":
                return [room_b]
            return []

        def conflict_checker(mts, room, instructor, section_id, group=None, max_parallel=2, co_instructor=None):
            day = mts[0].day
            allowed = {
                ("Monday", room_a.r_number, a1.uid),
                ("Monday", room_a.r_number, a2.uid),
                ("Tuesday", room_a.r_number, a2.uid),
                ("Monday", room_b.r_number, b1.uid),
                ("Monday", room_b.r_number, b2.uid),
                ("Tuesday", room_b.r_number, b1.uid),
            }
            return (day, room.r_number, instructor.uid) not in allowed

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
        self.assertEqual({lab.instructor.uid for lab in grouped_labs if lab.subject == subject_a}, {"RA002"})
        parallel_slots = {}
        for lab in grouped_labs:
            key = (lab.meeting_times[0].day, lab.meeting_times[0].time)
            parallel_slots.setdefault(key, []).append(lab.subject.subject_number)
        self.assertEqual({key for key, vals in parallel_slots.items() if len(vals) == 2}, {("Monday", "1"), ("Tuesday", "1")})


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
