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
    path('prefilled-timetable/', views.prefilled_timetable_setup, name='prefilled_timetable_setup'),
    path('prefilled-timetable/edit/', views.prefilled_timetable_view, name='prefilled_timetable_view'),
    path('prefilled-timetable/save/', views.save_prefilled_timetable, name='save_prefilled_timetable'),
    path('prefilled-timetable/export-csv/', views.export_prefill_csv, name='export_prefill_csv'),
    path('prefilled-timetable/import-csv/', views.import_prefill_csv, name='import_prefill_csv'),
    path('saved-prefills/', views.saved_prefill_list, name='saved_prefill_list'),
    path('saved-prefills/<int:prefill_id>/open/', views.open_saved_prefill, name='open_saved_prefill'),
    path('saved-prefills/<int:prefill_id>/generate/', views.generate_saved_prefill, name='generate_saved_prefill'),
    path('saved-prefills/generate-selected/', views.generate_selected_prefills, name='generate_selected_prefills'),
    path('generate-without-prefills/', views.generate_without_prefills, name='generate_without_prefills'),
    path('saved-prefills/<int:prefill_id>/rename/', views.rename_saved_prefill, name='rename_saved_prefill'),
    path('saved-prefills/<int:prefill_id>/delete/', views.delete_saved_prefill, name='delete_saved_prefill'),
    path('role', views.role, name='role'),
    path('teacher-login', views.teacherlogin, name='teacher/login'),
    path('teacher-register/', views.teacher_register, name='teacher_register'),
    path('teacher-register/teachers/', views.teacher_register_teachers, name='teacher_register_teachers'),
    path('teacher-register/info/', views.teacher_register_info, name='teacher_register_info'),
    path('teacher-register/send-otp/', views.teacher_register_send_otp, name='teacher_register_send_otp'),
    path('teacher-register/verify-otp/', views.teacher_register_verify_otp, name='teacher_register_verify_otp'),
    path('dean-login', views.deanlogin, name='dean/login'),
    path('set-role/hod/', views.admindash_role_set, name='set_role_hod'),
    path('set-role/teacher/', views.teacher_role_set, name='set_role_teacher'),
    path('set-role/dean/', views.dean_role_set, name='set_role_dean'),

    # --- Super Admin (inbuilt .env login + analytics dashboard) ---
    path('superadmin/login/', views.superadmin_login, name='superadmin_login'),
    path('superadmin/logout/', views.superadmin_logout, name='superadmin_logout'),
    path('superadmin/choose-user/', views.superadmin_choose_user, name='superadmin_choose_user'),
    path('superadmin/select-user/', views.superadmin_select_user, name='superadmin_select_user'),
    path('superadmin/dashboard/', views.superadmin_dashboard, name='superadmin_dashboard'),
    path('superadmin/resource/', views.superadmin_resource, name='superadmin_resource'),
    path('superadmin/teachers/', views.superadmin_teachers, name='superadmin_teachers'),
    path('superadmin/teachers/<int:teacher_id>/edit/', views.superadmin_teacher_edit, name='superadmin_teacher_edit'),
    path('superadmin/teachers/<int:teacher_id>/delete/', views.superadmin_teacher_delete, name='superadmin_teacher_delete'),
    path('superadmin/departments/', views.superadmin_depts, name='superadmin_depts'),
    path('superadmin/slots/', views.superadmin_slots, name='superadmin_slots'),
    path('superadmin/explorer/', views.superadmin_explorer, name='superadmin_explorer'),
    path('superadmin/saved-timetables/', views.superadmin_saved_page, name='superadmin_saved_page'),
    path('superadmin/saved-timetables/<int:tid>/open/', views.superadmin_open_saved, name='superadmin_open_saved'),
    path('superadmin/stop-impersonate/', views.superadmin_stop_impersonate, name='superadmin_stop_impersonate'),
    path('superadmin/preview/', views.superadmin_preview, name='superadmin_preview'),
    path('superadmin/activity/', views.superadmin_activity, name='superadmin_activity'),
    path('superadmin/appoint/', views.superadmin_appoint, name='superadmin_appoint'),
    path('superadmin/appoint/<int:aid>/delete/', views.superadmin_appoint_delete, name='superadmin_appoint_delete'),
    path('superadmin/users/', views.superadmin_users, name='superadmin_users'),
    path('superadmin/users/<int:uid>/delete/', views.superadmin_user_delete, name='superadmin_user_delete'),
    path('superadmin/saved-timetables/<int:tid>/delete/', views.superadmin_saved_delete, name='superadmin_saved_delete'),
    path('superadmin/drilldown/', views.superadmin_drilldown, name='superadmin_drilldown'),
    path('superadmin/room-analytics/', views.superadmin_room_analytics, name='superadmin_room_analytics'),
    path('superadmin/teacher-detail/', views.superadmin_teacher_detail, name='superadmin_teacher_detail'),
    path('superadmin/teacher-workload/', views.superadmin_teacher_workload, name='superadmin_teacher_workload'),
    path('superadmin/saved/', views.superadmin_saved_list, name='superadmin_saved_list'),
    path('superadmin/saved/<int:tid>/', views.superadmin_saved_detail, name='superadmin_saved_detail'),
    path('superadmin/move-slot/', views.superadmin_move_slot, name='superadmin_move_slot'),
    path('superadmin/export/excel/', views.superadmin_export_excel, name='superadmin_export_excel'),
    path('superadmin/export/pdf/', views.superadmin_export_pdf, name='superadmin_export_pdf'),

    path('teacher/onboarding/', views.teacher_onboarding, name='teacher_onboarding'),
    path('teacher/dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/profile/', views.teacher_profile_page, name='teacher_profile_page'),
    path('teacher/published-timetable/', views.teacher_published_timetable, name='teacher_published_timetable'),
    path('teacher/my-timetable/', views.teacher_my_timetable, name='teacher_my_timetable'),
    path('teacher-onboarding-responses/', views.teacher_onboarding_responses_page, name='teacher_onboarding_responses'),
    path('teacher-onboarding-responses/<int:submission_id>/resubmit/', views.request_teacher_onboarding_resubmission, name='request_teacher_onboarding_resubmission'),
    path('teacher-onboarding-responses/<int:submission_id>/delete/', views.delete_teacher_onboarding, name='delete_teacher_onboarding'),
    path('export/teacher-onboarding/csv/', views.export_teacher_onboarding_csv, name='export_teacher_onboarding_csv'),
    path('teacher_timetable/', views.teachertimetable, name='teachertimetable'),
    path('saved_timetables/', views.teachertimetable_list, name='teachertimetable_list'),
    path('add_teachers', views.addInstructor, name='addInstructors'),
    path('teachers_list/', views.inst_list_view , name='editinstructor'),
    path('dashboard_teachers_list/', views.dashboard_inst_list_view, name='dashboard_editinstructor'),
    path('delete_teacher/<int:pk>/', views.delete_instructor, name='deleteinstructor'), 
    path('delete_all_teachers/', views.delete_all_instructors, name='delete_all_instructors'),
    path('saved_teacher_timetables/<int:tid>/', views.saved_teacher_timetable, name='saved_teacher_timetable'),

    path('add_rooms', views.addRooms, name='addRooms'),
    path('rooms_list/', views.room_list, name='editrooms'),
    path('delete_room/<int:pk>/', views.delete_room, name='deleteroom'),
    path('delete_all_rooms/', views.delete_all_rooms, name='delete_all_rooms'),

    path('add_timings', views.addTimings, name='addTimings'),
    path('timings_list/', views.meeting_list_view, name='editmeetingtime'),
    path('delete_meetingtime/<str:pk>/', views.delete_meeting_time, name='deletemeetingtime'),
    path('delete_all_timings/', views.delete_all_meeting_times, name='delete_all_meeting_times'),

    path('add_subjects', views.addSubjects, name='addSubjects'),
    path('subjects_list/', views.subject_list_view, name='editsubject'),
    path('delete_subject/<str:pk>/', views.delete_subject, name='deletesubject'),
    path('delete_all_subjects/', views.delete_all_subjects, name='delete_all_subjects'),

    path('add_departments', views.addDepts, name='addDepts'),
    path('departments_list/', views.department_list, name='editdepartment'),
    path('dashboard_departments_list/', views.dashboard_department_list, name='dashboard_editdepartment'),
    path('delete_department/<int:pk>/', views.delete_department, name='deletedepartment'),
    path('delete_all_departments/', views.delete_all_departments, name='delete_all_departments'),

    path('add_sections', views.addSections, name='addSections'),
    path('sections_list/', views.section_list, name='editsection'),
    path('dashboard_sections_list/', views.dashboard_section_list, name='dashboard_editsection'),
    path('delete_section/<str:pk>/', views.delete_section, name='deletesection'),
    path('delete_all_sections/', views.delete_all_sections, name='delete_all_sections'),
    path("map-teacher-subjects/",views.map_teacher_subjects,name="map_teacher_subjects"),
    path(
    "delete-teacher-subject/<str:subject_number>/<int:instructor_id>/",
    views.delete_teacher_subject_mapping,
    name="delete_teacher_subject_mapping"),
    path(
    "delete-sci-mapping/<int:mapping_id>/",
    views.delete_sci_mapping,
    name="delete_sci_mapping"),
    path('delete_all_teacher_subject_mappings/', views.delete_all_teacher_subject_mappings, name='delete_all_teacher_subject_mappings'),
    path("map-section-subjects/",views.map_section_subjects,name="map_section_subjects"),
    path("view-section-subjects/", views.view_section_subjects, name="view_section_subjects"),
    path('delete_all_section_subject_mappings/', views.delete_all_section_subject_mappings, name='delete_all_section_subject_mappings'),



    path('generate/', views.generate, name='generate'),
    path("generate/demo/", views.demo_generate_start, name="demo_generate_start"),
    path("auth/role/subscription/", views.subscription_gate, name="subscription_gate"),
    path("auth/role/subscription/create-order/", views.create_razorpay_order, name="create_razorpay_order"),
    path("auth/role/subscription/verify-payment/", views.verify_razorpay_payment, name="verify_razorpay_payment"),
    path("auth/role/subscription/callback/", views.razorpay_payment_callback, name="razorpay_payment_callback"),


    path("generate_timetable/loading/", views.generate_timetable_loading, name="generate_timetable_loading"),
    path("generate_timetable/", views.generate_timetables, name="generate_timetables"),
    path("generate_timetable/logs/", views.generation_logs, name="generation_logs"),
    path("timetables/", views.timetables_page, name="timetables_page"),
    path("timetable/<int:index>/departments/", views.timetable_dept_select, name="timetable_dept_select"),
    path("timetable/<int:index>/full-statistics/", views.full_statistics, name="full_statistics"),
    path("timetable/<int:index>/", views.show_timetable, name="show_timetable"),


    path('timetable_generation/', views.timetable, name='timetable'),
    # path('timetable_generation/render/pdf', views.Pdf, name='pdf'),
    # path('timetable_generation/render/pdf/', views.Pdf.as_view(), name='pdf'),

    path('update_slot/<path:section>/<str:day>/<int:slot>/', views.update_slot, name='update_slot'),
    path('move_slot/<path:section>/<str:day>/<int:slot>/', views.move_slot_dragdrop, name='move_slot_dragdrop'),
    path('park_slot/<path:section>/<str:day>/<int:slot>/', views.generated_park_slot, name='generated_park_slot'),
    path('parking/<path:section>/create/', views.generated_create_parking_slot, name='generated_create_parking_slot'),
    path('parking/<int:parking_id>/restore/', views.generated_restore_parked_slot, name='generated_restore_parked_slot'),
    path('parking/<int:parking_id>/update/', views.generated_update_parking_item, name='generated_update_parking_item'),
    path('parking/<int:parking_id>/delete/', views.generated_delete_parking_item, name='generated_delete_parking_item'),
    path('parking/delete-created/<str:manual_slot_uid>/', views.generated_delete_manual_slot_item, name='generated_delete_manual_slot_item'),
    path('parking/update-created/<str:manual_slot_uid>/', views.generated_update_manual_slot_item, name='generated_update_manual_slot_item'),
    path('parking/delete-slot/<path:section>/<str:day>/<int:slot>/', views.generated_delete_slot_item, name='generated_delete_slot_item'),
    path('delete_slot/<path:section>/<str:day>/<int:slot>/', views.delete_slot, name='delete_slot'),
    path('add_slot/<path:section>/', views.add_slot, name='add_slot'),
    path('rename_instructor/', views.rename_instructor, name='rename_instructor'),
    
    path('save_timetable/<int:index>/', views.save_timetable, name='save_timetable'),
    path('saved_timetables/', views.saved_timetable_list, name='saved_timetable_list'),
    path('saved_timetables/<int:tid>/', views.saved_timetable, name='saved_timetable'),
    path('saved_timetables/<int:tid>/full-statistics/', views.saved_full_statistics, name='saved_full_statistics'),
    path("saved_timetable/delete/<int:tid>/", views.delete_saved_timetable, name="delete_saved_timetable"),

    path('saved_timetables/<int:tid>/download/', views.saved_timetable_download_center, name='saved_timetable_download_center'),
    path('download_timetable/<int:tid>/', views.download_saved_timetable_pdf, name='download_timetable'),
    path('download_timetable/<int:tid>/<str:view_type>/', views.download_saved_timetable_pdf, name='download_timetable_view'),
    path('download_timetable_excel/<int:tid>/', views.download_timetable_excel, name='download_timetable_excel'),
    path('download_timetable_excel/<int:tid>/<str:view_type>/', views.download_timetable_excel, name='download_timetable_excel_view'),
    path(
        'download_generated_timetable_excel/<int:index>/<str:view_type>/',
        views.download_generated_timetable_excel,
        name='download_generated_timetable_excel'
    ),
    path(
        'timetable/<int:index>/download/',
        views.timetable_download_center,
        name='timetable_download_center'
    ),
    path(
        'download_generated_timetable_pdf/<int:index>/',
        views.download_generated_timetable_pdf,
        name='download_generated_timetable_pdf'
    ),
    path(
        'download_generated_timetable_pdf/<int:index>/<str:view_type>/',
        views.download_generated_timetable_pdf,
        name='download_generated_timetable_pdf_view'
    ),
    
    # Saved timetable slot editing
    path("saved/<int:tid>/add/<path:section>/", views.saved_add_slot, name="saved_add_slot"),
    path("saved/<int:tid>/update/<path:section>/<str:day>/<int:slot>/", views.saved_update_slot, name="saved_update_slot"),
    path("saved/<int:tid>/delete/<path:section>/<str:day>/<int:slot>/", views.saved_delete_slot, name="saved_delete_slot"),
    path("saved/<int:tid>/substitute/<path:section>/<str:day>/<int:slot>/", views.saved_substitute_teacher, name="saved_substitute_teacher"),
    path("saved/<int:tid>/substitute_lab/<path:section>/<str:day>/<int:slot>/", views.saved_substitute_lab_teacher, name="saved_substitute_lab_teacher"),
    path("saved/<int:tid>/move/<path:section>/<str:day>/<int:slot>/", views.saved_move_slot_dragdrop, name="saved_move_slot_dragdrop"),
    path("saved/<int:tid>/park/<path:section>/<str:day>/<int:slot>/", views.saved_park_slot, name="saved_park_slot"),
    path("saved/<int:tid>/parking/<int:parking_id>/restore/", views.saved_restore_parked_slot, name="saved_restore_parked_slot"),

    path("substitute_teacher/<path:section>/<str:day>/<int:slot>/",views.substitute_teacher,name="substitute_teacher"),
    path("substitute_lab/<path:section>/<str:day>/<int:slot>/",views.substitute_lab_teacher,name="substitute_lab_teacher"),

    # Publish / Teacher read-only
    path('saved_timetable/<int:tid>/publish/', views.publish_timetable, name='publish_timetable'),
    path('saved_timetable/<int:tid>/publish/notifications/', views.saved_timetable_publish_notifications, name='saved_timetable_publish_notifications'),
    path('saved_timetable/<int:tid>/publish/notify-teachers/', views.publish_notify_all_teachers, name='publish_notify_all_teachers'),
    path('saved_timetable/<int:tid>/publish/notify-teacher/', views.publish_notify_single_teacher, name='publish_notify_single_teacher'),
    path('saved_timetable/<int:tid>/publish/notify-coordinators/', views.publish_notify_all_coordinators, name='publish_notify_all_coordinators'),
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



