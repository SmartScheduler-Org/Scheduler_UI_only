from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from . import views
from . import views_other
from .models import Subject, Department, Instructor, MeetingTime, Room, Section


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
        self.assertTrue(any(cls.meeting_time.day == "Monday" for cls in theory_classes))

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
        )
        self.assertEqual(candidates[0], home_room)
        self.assertEqual(candidates[1], extra_room)


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
