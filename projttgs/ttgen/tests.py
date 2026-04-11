from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from . import views
from .models import Course, Department, Instructor, MeetingTime, Room, Section


class SchedulerInitializationTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create()

        Room.objects.create(
            r_number="LH-1",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
        )
        Room.objects.create(
            r_number="LAB-1",
            room_type="Lab",
            seating_capacity=30,
            department=self.department,
        )

        for day in ["Monday", "Tuesday"]:
            for slot in ["1", "2", "3", "4", "6", "7", "8", "9"]:
                MeetingTime.objects.create(
                    pid=f"{day[:2]}{slot}",
                    day=day,
                    time=slot,
                )

        self.section = Section.objects.create(
            section_id="Test Section",
            department=self.department,
        )

        theory_loads = [2, 2, 2, 2, 1]
        for index, classes_per_week in enumerate(theory_loads, start=1):
            instructor = Instructor.objects.create(
                uid=f"T{index:03d}",
                name=f"Theory Teacher {index}",
                designation="Assistant Professor",
                max_workload=25,
            )
            course = Course.objects.create(
                course_number=f"TH{index:03d}",
                course_name=f"Theory {index}",
                department=self.department,
                max_numb_students=60,
                room_required="Lecture Hall",
                classes_per_week=classes_per_week,
            )
            course.instructors.add(instructor)
            self.section.allowed_courses.add(course)

        lab_instructor = Instructor.objects.create(
            uid="L001",
            name="Lab Teacher",
            designation="Assistant Professor",
            max_workload=25,
        )
        lab_course = Course.objects.create(
            course_number="LAB001",
            course_name="Solo Lab",
            department=self.department,
            max_numb_students=30,
            room_required="Lab",
            classes_per_week=1,
        )
        lab_course.instructors.add(lab_instructor)
        self.section.allowed_courses.add(lab_course)

    def test_initialize_schedules_theory_even_when_lab_uses_part_of_day(self):
        with patch.object(views, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views, "COMPACT_SECTIONS", {}
        ):
            views.data = views.Data()
            schedule = views.Schedule().initialize()

        theory_classes = [cls for cls in schedule.get_classes() if cls.section == "Test Section"]
        self.assertEqual(len(theory_classes), 9)
        self.assertTrue(any(cls.meeting_time.day == "Monday" for cls in theory_classes))

    def test_compute_real_metrics_handles_empty_schedule(self):
        teacher_load, resource_util, student_load = views.compute_real_metrics([], [])

        self.assertEqual(teacher_load, 5)
        self.assertEqual(resource_util, 0)
        self.assertEqual(student_load, 5)

    def test_build_section_tables_includes_subject_counts(self):
        theory_courses = list(self.section.allowed_courses.filter(room_required="Lecture Hall").order_by("course_number"))
        lab_course = self.section.allowed_courses.get(room_required="Lab")
        teacher = theory_courses[0].instructors.first()
        room = Room.objects.get(r_number="LH-1")
        lab_room = Room.objects.get(r_number="LAB-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")
        monday_2 = MeetingTime.objects.get(pid="Mo2")
        tuesday_1 = MeetingTime.objects.get(pid="Tu1")

        cls1 = views.Class(1, self.department, self.section.section_id, theory_courses[0])
        cls1.set_instructor(teacher)
        cls1.set_room(room)
        cls1.set_meetingTime(monday_1)

        cls2 = views.Class(2, self.department, self.section.section_id, theory_courses[0])
        cls2.set_instructor(teacher)
        cls2.set_room(room)
        cls2.set_meetingTime(monday_2)

        cls3 = views.Class(3, self.department, self.section.section_id, theory_courses[1])
        cls3.set_instructor(theory_courses[1].instructors.first())
        cls3.set_room(room)
        cls3.set_meetingTime(tuesday_1)

        lab = views.Lab(4, self.department, self.section.section_id, lab_course)
        lab.set_instructor(lab_course.instructors.first())
        lab.set_room(lab_room)
        lab.set_meetingTimes([
            monday_1,
            MeetingTime.objects.get(pid="Mo2"),
            MeetingTime.objects.get(pid="Mo3"),
            MeetingTime.objects.get(pid="Mo4"),
        ])

        tables = views.build_section_tables([cls1, cls2, cls3], [lab])
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
        course = Course.objects.create(
            course_number="TH999",
            course_name="Unmapped Theory",
            department=self.department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )
        self.section.allowed_courses.add(course)

        tables = views.build_section_tables([], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")
        subject = next(subject for subject in test_table["subject_counts"] if subject["name"] == "Unmapped Theory")

        self.assertEqual(subject["unfulfilled"], 3)
        self.assertEqual(subject["reason"], "Teacher not mapped")

    def test_build_section_tables_includes_manual_add_suggestions_for_missed_lecture(self):
        tables = views.build_section_tables([], [])
        test_table = next(table for table in tables if table["section"].section_id == "Test Section")
        subject = next(subject for subject in test_table["subject_counts"] if subject["name"] == "Theory 1")

        self.assertGreater(subject["unfulfilled"], 0)
        self.assertTrue(subject["suggested_slots"])

    def test_initialize_keeps_same_teacher_for_section_subject_pair(self):
        course = self.section.allowed_courses.filter(room_required="Lecture Hall").order_by("course_number").first()
        primary = Instructor.objects.create(
            uid="FX001",
            name="Fixed Teacher",
            designation="Assistant Professor",
            max_workload=1,
        )
        backup = Instructor.objects.create(
            uid="FX002",
            name="Backup Teacher",
            designation="Assistant Professor",
            max_workload=25,
        )
        course.instructors.clear()
        course.instructors.add(primary, backup)

        with patch.object(views, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views, "COMPACT_SECTIONS", {}
        ):
            views.data = views.Data()
            schedule = views.Schedule().initialize()

        course_classes = [
            cls for cls in schedule.get_classes()
            if cls.section == "Test Section" and cls.course.course_number == course.course_number
        ]

        assigned_teachers = {cls.instructor.uid for cls in course_classes}
        self.assertLessEqual(len(assigned_teachers), 1)
        self.assertLessEqual(len(course_classes), 1)

    def test_crossover_keeps_same_teacher_for_section_subject_pair(self):
        course = self.section.allowed_courses.filter(room_required="Lecture Hall").order_by("course_number").first()
        teacher_one = Instructor.objects.create(
            uid="CX001",
            name="Crossover Teacher 1",
            designation="Assistant Professor",
            max_workload=25,
        )
        teacher_two = Instructor.objects.create(
            uid="CX002",
            name="Crossover Teacher 2",
            designation="Assistant Professor",
            max_workload=25,
        )
        room = Room.objects.get(r_number="LH-1")
        monday_1 = MeetingTime.objects.get(pid="Mo1")
        monday_2 = MeetingTime.objects.get(pid="Mo2")

        s1 = views.Schedule()
        c1 = views.Class(1, self.department, self.section.section_id, course)
        c1.set_instructor(teacher_one)
        c1.set_room(room)
        c1.set_meetingTime(monday_1)
        s1._classes = [c1]
        s1._instructor_fixed[(self.section.section_id, course.pk)] = teacher_one

        s2 = views.Schedule()
        c2 = views.Class(2, self.department, self.section.section_id, course)
        c2.set_instructor(teacher_two)
        c2.set_room(room)
        c2.set_meetingTime(monday_2)
        s2._classes = [c2]
        s2._instructor_fixed[(self.section.section_id, course.pk)] = teacher_two

        child = views.GeneticAlgorithm()._crossover(s1, s2)

        assigned_teachers = {
            cls.instructor.uid
            for cls in child.get_classes()
            if cls.section == self.section.section_id and cls.course.course_number == course.course_number
        }
        self.assertLessEqual(len(assigned_teachers), 1)

    def test_initialize_keeps_same_room_within_half_day_block(self):
        with patch.object(views, "SECTION_LOAD_RULES", {"Test Section": (9, 4)}), patch.object(
            views, "COMPACT_SECTIONS", {}
        ):
            views.data = views.Data()
            schedule = views.Schedule().initialize()

        rooms_by_block = {}
        for cls in schedule.get_classes():
            if cls.section != "Test Section" or not cls.meeting_time or not cls.room:
                continue
            block = "pre_lunch" if int(cls.meeting_time.time) < int(views.LUNCH_SLOT) else "post_lunch"
            key = (cls.section, cls.meeting_time.day, block)
            rooms_by_block.setdefault(key, set()).add(cls.room.r_number)

        self.assertTrue(rooms_by_block)
        self.assertTrue(all(len(rooms) <= 1 for rooms in rooms_by_block.values()))

    def test_room_candidates_prefer_other_half_room_first_for_full_day_reuse(self):
        schedule = views.Schedule()
        home_room = Room.objects.get(r_number="LH-1")
        extra_room = Room.objects.create(
            r_number="LH-2",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=self.department,
        )
        room_map = {
            schedule._room_block_key(self.section.section_id, "Monday", "1"): home_room,
        }

        candidates = schedule._build_room_candidates(
            self.section.section_id,
            "Monday",
            "6",
            None,
            [extra_room, home_room],
            room_map,
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
        Department.objects.create(name="Computer Science", code="CS")

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
        cs = Department.objects.create(name="Computer Science", code="CS")
        me = Department.objects.create(name="Mechanical Engineering", code="ME")

        Room.objects.create(
            r_number="CS-LH",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=cs,
        )
        Room.objects.create(
            r_number="ME-LH",
            room_type="Lecture Hall",
            seating_capacity=60,
            department=me,
        )

        course_cs = Course.objects.create(
            course_number="CS101",
            course_name="Algorithms",
            department=cs,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )
        course_me = Course.objects.create(
            course_number="ME101",
            course_name="Thermodynamics",
            department=me,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )

        section_cs = Section.objects.create(section_id="CS-A", department=cs)
        section_me = Section.objects.create(section_id="ME-A", department=me)
        section_cs.allowed_courses.add(course_cs)
        section_me.allowed_courses.add(course_me)

        data = views.Data()

        self.assertEqual({dept.code for dept in data.get_depts()}, {"CS", "ME"})
        self.assertEqual({section.section_id for section in data.get_sections()}, {"CS-A", "ME-A"})
        self.assertEqual(
            {course.course_number for course in data.get_department_courses(cs)},
            {"CS101"},
        )
        self.assertEqual(
            {course.course_number for course in data.get_department_courses(me)},
            {"ME101"},
        )

    def test_map_teacher_courses_accepts_instructor_name_in_csv(self):
        self.client.login(username="deptadmin", password="testpass123")
        department = Department.objects.create(name="Computer Science", code="CS")
        instructor = Instructor.objects.create(
            uid="T9001",
            name="Anita Sharma",
            designation="Assistant Professor",
            max_workload=25,
        )
        course = Course.objects.create(
            course_number="CS500",
            course_name="Compiler Design",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )

        csv_content = "instructor_name,course_number\nAnita Sharma,CS500\n"
        upload = SimpleUploadedFile("teacher_map.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("map_teacher_courses"),
            {"csv_upload": "1", "csv_file": upload},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("map_teacher_courses"))
        self.assertTrue(course.instructors.filter(pk=instructor.pk).exists())

    def test_new_section_can_clone_subjects_from_similar_existing_section(self):
        department = Department.objects.create(name="Computer Science", code="CS")
        course_one = Course.objects.create(
            course_number="CS215",
            course_name="Mathematics-I",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )
        course_two = Course.objects.create(
            course_number="CS216",
            course_name="Chemistry",
            department=department,
            max_numb_students=60,
            room_required="Lecture Hall",
            classes_per_week=3,
        )

        template_section = Section.objects.create(section_id="IT 1st Sem", department=department)
        template_section.allowed_courses.add(course_one, course_two)

        new_section = Section.objects.create(section_id="IT 1st Sem A", department=department)

        matched = views.clone_section_courses_from_similar(new_section)

        self.assertEqual(matched, template_section)
        self.assertEqual(
            set(new_section.allowed_courses.values_list("course_number", flat=True)),
            {"CS215", "CS216"},
        )

    def test_new_section_without_static_rule_is_not_skipped_by_scheduler(self):
        department = Department.objects.create(name="Computer Science", code="CS")
        Room.objects.create(
            r_number="NH-1",
            room_type="Lecture Hall",
            seating_capacity=70,
            department=department,
        )
        Room.objects.create(
            r_number="NLab-1",
            room_type="Lab",
            seating_capacity=35,
            department=department,
        )

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            for slot in ["1", "2", "3", "4", "6", "7", "8", "9"]:
                MeetingTime.objects.get_or_create(
                    pid=f"N{day[:2]}{slot}",
                    defaults={"day": day, "time": slot},
                )

        theory_teacher = Instructor.objects.create(
            uid="NS001",
            name="New Section Theory",
            designation="Assistant Professor",
            max_workload=25,
        )
        lab_teacher = Instructor.objects.create(
            uid="NS002",
            name="New Section Lab",
            designation="Assistant Professor",
            max_workload=25,
        )

        theory_course = Course.objects.create(
            course_number="NS101",
            course_name="Intro Programming",
            department=department,
            max_numb_students=70,
            room_required="Lecture Hall",
            classes_per_week=3,
        )
        theory_course.instructors.add(theory_teacher)

        lab_course = Course.objects.create(
            course_number="NS102",
            course_name="Programming Lab",
            department=department,
            max_numb_students=35,
            room_required="Lab",
            classes_per_week=4,
        )
        lab_course.instructors.add(lab_teacher)

        section = Section.objects.create(
            section_id="New Section X",
            department=department,
            student_strength=35,
        )
        section.allowed_courses.add(theory_course, lab_course)

        views.data = views.Data()
        schedule = views.Schedule().initialize()

        section_classes = [cls for cls in schedule.get_classes() if cls.section == "New Section X"]
        section_labs = [lab for lab in schedule.get_labs() if lab.section == "New Section X"]

        self.assertTrue(section_classes or section_labs)
