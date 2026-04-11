from django import forms
from django.forms import ModelForm
from .models import (
    Room,
    Instructor,
    MeetingTime,
    Course,
    Section,
    Department,
    LAB_CATEGORY_CHOICES,
)
class DepartmentForm(ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code"]
        labels = {
            "name": "Department Name",
            "code": "Department Code",
        }

# ==================================================
# ROOM FORM
# ==================================================

class RoomForm(ModelForm):
    class Meta:
        model = Room
        fields = [
            'r_number',
            'department',
            'seating_capacity',
            'room_type',
            'lab_category',
        ]
        labels = {
            "r_number": "Room ID",
            "department": "Department",
            "seating_capacity": "Capacity",
            "room_type": "Room Type",
            "lab_category": "Lab Category",
        }
        widgets = {
            "department": forms.Select(),
            "room_type": forms.Select(choices=[
                ('Lecture Hall', 'Lecture Hall'),
                ('Lab', 'Lab'),
                ('Seminar Room', 'Seminar Room'),
            ]),
            "lab_category": forms.Select(choices=[("", "---------")] + list(LAB_CATEGORY_CHOICES)),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Department.objects.all()
        if user:
            qs = qs.filter(user=user)
        self.fields["department"].queryset = qs.order_by("code", "name")


# ==================================================
# INSTRUCTOR FORM
# ==================================================

class InstructorForm(ModelForm):
    class Meta:
        model = Instructor
        fields = ['uid', 'name', 'designation', 'max_workload']
        labels = {
            "uid": "Teacher UID",
            "name": "Full Name",
            "designation": "Designation",
            "max_workload": "Max Workload",
        }
        widgets = {
            "designation": forms.Select(choices=Instructor.DESIGNATION_CHOICES),
            "max_workload": forms.NumberInput(attrs={"min": 1}),
        }


# ==================================================
# MEETING TIME FORM
# ==================================================

class MeetingTimeForm(ModelForm):
    class Meta:
        model = MeetingTime
        fields = ['pid', 'time', 'day']
        labels = {
            "pid": "Meeting ID",
            "time": "Time Slot",
            "day": "Day of Week",
        }
        widgets = {
            'pid': forms.TextInput(),
            'time': forms.Select(choices=[
                ('1', 'Slot 1'),
                ('2', 'Slot 2'),
                ('3', 'Slot 3'),
                ('4', 'Slot 4'),
                ('5', 'Slot 5'),
                ('6', 'Slot 6'),
                ('7', 'Slot 7'),
                ('8', 'Slot 8'),
                ('9', 'Slot 9'),
            ]),
            'day': forms.Select(),
        }


# ==================================================
# COURSE FORM
# ==================================================

class CourseForm(ModelForm):
    class Meta:
        model = Course
        fields = [
            'department',
            'course_number',
            'course_name',
            'max_numb_students',
            'room_required',
            'required_lab_category',
            'instructors',
            'classes_per_week',
        ]
        labels = {
            "department": "Department",
            "course_number": "Course ID",
            "course_name": "Course Name",
            "max_numb_students": "Max Students",
            "room_required": "Required Room Type",
            "required_lab_category": "Required Lab Category",
            "instructors": "Assigned Teacher",
            "classes_per_week": "Classes Per Week",
        }
        widgets = {
            "department": forms.Select(),
            "room_required": forms.Select(choices=[
                ('Lecture Hall', 'Lecture Hall'),
                ('Lab', 'Lab'),
            ]),
            "required_lab_category": forms.Select(choices=[("", "---------")] + list(LAB_CATEGORY_CHOICES)),
            "instructors": forms.Select(),
            "classes_per_week": forms.NumberInput(attrs={
                'min': 1,
                'max': 10,
                'placeholder': 'e.g., 3',
            }),
        }
        help_texts = {
            "classes_per_week": "How many times this course runs per week",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        dept_qs = Department.objects.all()
        inst_qs = Instructor.objects.all()
        if user:
            dept_qs = dept_qs.filter(user=user)
            inst_qs = inst_qs.filter(user=user)
        self.fields["department"].queryset = dept_qs.order_by("code", "name")
        self.fields["instructors"].queryset = inst_qs.order_by("uid")


# ==================================================
# SECTION FORM
# ==================================================

class SectionForm(ModelForm):
    class Meta:
        model = Section
        fields = [
            "section_id",
            "department",
            "student_strength",
        ]
        labels = {
            "section_id": "Section ID",
            "department": "Department",
            "student_strength": "Student Strength",
        }
        widgets = {
            "department": forms.Select(),
            "student_strength": forms.NumberInput(attrs={"min": 1}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Department.objects.all()
        if user:
            qs = qs.filter(user=user)
        self.fields["department"].queryset = qs.order_by("code", "name")
