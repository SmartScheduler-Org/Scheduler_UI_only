from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('about', views.about, name='about'),
    path('live-demo', views.live_demo, name='live_demo'),
    path('services', views.services, name='services'),
    path('help', views.help, name='help'),
    path('terms', views.terms, name='terms'),
    path('privacy', views.privacy, name='privacy'),
    path('contact', views.contact, name='contact'),
    path('apply-institute/', views.institute_application, name='institute_application'),
    path('apply-institute/thanks/', views.institute_application_thanks, name='institute_application_thanks'),

    path('admin_dashboard', views.admindash, name='admindash'),
    path('role', views.role, name='role'),
    path('teacher-login', views.teacherlogin, name='teacher/login'),
    path('dean-login', views.deanlogin, name='dean/login'),
    path('set-role/hod/', views.admindash_role_set, name='set_role_hod'),
    path('set-role/teacher/', views.teacher_role_set, name='set_role_teacher'),
    path('set-role/dean/', views.dean_role_set, name='set_role_dean'),
    path('teacher_timetable/', views.teachertimetable, name='teachertimetable'),
    path('saved_timetables/', views.teachertimetable_list, name='teachertimetable_list'),
    path('add_teachers', views.addInstructor, name='addInstructors'),
    path('teachers_list/', views.inst_list_view , name='editinstructor'),
    path('dashboard_teachers_list/', views.dashboard_inst_list_view, name='dashboard_editinstructor'),
    path('delete_teacher/<int:pk>/', views.delete_instructor, name='deleteinstructor'), 
    path('saved_teacher_timetables/<int:tid>/', views.saved_teacher_timetable, name='saved_teacher_timetable'),

    path('add_rooms', views.addRooms, name='addRooms'),
    path('rooms_list/', views.room_list, name='editrooms'),
    path('delete_room/<int:pk>/', views.delete_room, name='deleteroom'),

    path('add_timings', views.addTimings, name='addTimings'),
    path('timings_list/', views.meeting_list_view, name='editmeetingtime'),
    path('delete_meetingtime/<str:pk>/', views.delete_meeting_time, name='deletemeetingtime'),

    path('add_courses', views.addCourses, name='addCourses'),
    path('courses_list/', views.course_list_view, name='editcourse'),
    path('delete_course/<str:pk>/', views.delete_course, name='deletecourse'),
    path("map-teacher-courses/",views.map_teacher_courses,name="map_teacher_courses"),
    path(
    "delete-teacher-course/<str:course_number>/<int:instructor_id>/",
    views.delete_teacher_course_mapping,
    name="delete_teacher_course_mapping"),


    path('add_departments', views.addDepts, name='addDepts'),
    path('departments_list/', views.department_list, name='editdepartment'),
    path('dashboard_departments_list/', views.dashboard_department_list, name='dashboard_editdepartment'),
    path('delete_department/<int:pk>/', views.delete_department, name='deletedepartment'),

    path('add_sections', views.addSections, name='addSections'),
    path('sections_list/', views.section_list, name='editsection'),
    path('dashboard_sections_list/', views.dashboard_section_list, name='dashboard_editsection'),
    path('delete_section/<str:pk>/', views.delete_section, name='deletesection'),
    path("map-section-courses/",views.map_section_courses,name="map_section_courses"),
    path("view-section-courses/", views.view_section_courses, name="view_section_courses"),



    path('generate/', views.generate, name='generate'),
    path("generate/demo/", views.demo_generate_start, name="demo_generate_start"),
    path("auth/role/subscription/", views.subscription_gate, name="subscription_gate"),
    path("auth/role/subscription/create-order/", views.create_razorpay_order, name="create_razorpay_order"),
    path("auth/role/subscription/verify-payment/", views.verify_razorpay_payment, name="verify_razorpay_payment"),
    path("auth/role/subscription/callback/", views.razorpay_payment_callback, name="razorpay_payment_callback"),


    path("generate_timetable/loading/", views.generate_timetable_loading, name="generate_timetable_loading"),
    path("generate_timetable/", views.generate_timetables, name="generate_timetables"),
    path("timetables/", views.timetables_page, name="timetables_page"),
    path("timetable/<int:index>/departments/", views.timetable_dept_select, name="timetable_dept_select"),
    path("timetable/<int:index>/", views.show_timetable, name="show_timetable"),


    path('timetable_generation/', views.timetable, name='timetable'),
    # path('timetable_generation/render/pdf', views.Pdf, name='pdf'),
    # path('timetable_generation/render/pdf/', views.Pdf.as_view(), name='pdf'),

    path('update_slot/<str:section>/<str:day>/<int:slot>/', views.update_slot, name='update_slot'),
    path('move_slot/<str:section>/<str:day>/<int:slot>/', views.move_slot_dragdrop, name='move_slot_dragdrop'),
    path('delete_slot/<str:section>/<str:day>/<int:slot>/', views.delete_slot, name='delete_slot'),
    path('add_slot/<str:section>/', views.add_slot, name='add_slot'),
    
    path('save_timetable/<int:index>/', views.save_timetable, name='save_timetable'),
    path('saved_timetables/', views.saved_timetable_list, name='saved_timetable_list'),
    path('saved_timetables/<int:tid>/', views.saved_timetable, name='saved_timetable'),
    path("saved_timetable/delete/<int:tid>/", views.delete_saved_timetable, name="delete_saved_timetable"),

    path('download_timetable/<int:tid>/', views.download_saved_timetable_pdf, name='download_timetable'),
    path('download_timetable_excel/<int:tid>/', views.download_timetable_excel, name='download_timetable_excel'),
    path('download_timetable_excel/<int:tid>/<str:view_type>/', views.download_timetable_excel, name='download_timetable_excel_view'),
    path(
        'download_generated_timetable_excel/<int:index>/<str:view_type>/',
        views.download_generated_timetable_excel,
        name='download_generated_timetable_excel'
    ),
    
    # Saved timetable slot editing
    path("saved/<int:tid>/add/<str:section>/", views.saved_add_slot, name="saved_add_slot"),
    path("saved/<int:tid>/update/<str:section>/<str:day>/<int:slot>/", views.saved_update_slot, name="saved_update_slot"),
    path("saved/<int:tid>/delete/<str:section>/<str:day>/<int:slot>/", views.saved_delete_slot, name="saved_delete_slot"),
    path("saved/<int:tid>/substitute/<str:section>/<str:day>/<int:slot>/", views.saved_substitute_teacher, name="saved_substitute_teacher"),
    path("saved/<int:tid>/substitute_lab/<str:section>/<str:day>/<int:slot>/", views.saved_substitute_lab_teacher, name="saved_substitute_lab_teacher"),
    path("saved/<int:tid>/move/<str:section>/<str:day>/<int:slot>/", views.saved_move_slot_dragdrop, name="saved_move_slot_dragdrop"),

    path("substitute_teacher/<str:section>/<str:day>/<int:slot>/",views.substitute_teacher,name="substitute_teacher"),
    path("substitute_lab/<str:section>/<str:day>/<int:slot>/",views.substitute_lab_teacher,name="substitute_lab_teacher"),

    # Publish / Teacher read-only
    path('saved_timetable/<int:tid>/publish/', views.publish_timetable, name='publish_timetable'),
    path('saved_timetable/<int:tid>/unpublish/', views.unpublish_timetable, name='unpublish_timetable'),
    path('teacher/enter-code/', views.teacher_enter_code, name='teacher_enter_code'),
    path('teacher/view/<int:tid>/', views.teacher_view_timetable, name='teacher_view_timetable'),

    # CSV Converter (all entity types)
    path('convert_csv/', views.convert_csv, name='convert_csv'),
    path('convert_instructor_csv/', views.convert_csv, name='convert_instructor_csv'),







    # Teacher Preference
    path('teacher-pref-form/',      views.teacher_pref_form,         name='teacher_pref_form'),
    path('send-preferences/',       views.send_preferences_page,     name='send_preferences'),
    path('teacher-responses/',      views.teacher_responses_page,    name='teacher_responses'),
    path('api/pref/submit/',        views.teacher_pref_submit,       name='pref_submit'),
    path('api/pref/send-links/',    views.send_pref_links_smtp,      name='pref_send_links'),
    path('api/pref/parse-emails/',  views.parse_emails_view,         name='pref_parse_emails'),
    path('export/preferences/csv/', views.export_preferences_csv,    name='export_pref_csv'),
]
