# Database Schema Diagram

These Mermaid ER files are generated from `db.sqlite3`:

- `docs/schema_app.mmd`: app-focused view for `ttgen_*` and related user tables.
- `docs/schema_full.mmd`: full database view including Django/auth/allauth tables.
- `docs/schema_app.svg`: app-focused image export.
- `docs/schema_full.svg`: full database image export.

## Image files

- Open [schema_app.svg](/c:/wowo/Scheduler_UI_only/projttgs/docs/schema_app.svg) for the app-focused schema image.
- Open [schema_full.svg](/c:/wowo/Scheduler_UI_only/projttgs/docs/schema_full.svg) for the full database image.

## App-focused preview

```mermaid
erDiagram
    auth_user {
        integer id PK
        varchar(128) password NOT NULL
        datetime last_login
        bool is_superuser NOT NULL
        varchar(150) username NOT NULL
        varchar(150) last_name NOT NULL
        varchar(254) email NOT NULL
        bool is_staff NOT NULL
        bool is_active NOT NULL
        datetime date_joined NOT NULL
        varchar(150) first_name NOT NULL
    }
    ttgen_course {
        integer id PK
        varchar(20) course_number NOT NULL
        varchar(100) course_name NOT NULL
        integer unsigned max_numb_students NOT NULL
        varchar(20) room_required NOT NULL
        varchar(50) required_lab_category NOT NULL
        integer unsigned classes_per_week NOT NULL
        integer user_id NOT NULL
        bigint department_id NOT NULL
    }
    ttgen_course_instructors {
        integer id PK
        bigint course_id NOT NULL
        bigint instructor_id NOT NULL
    }
    ttgen_department {
        integer id PK
        varchar(100) name NOT NULL
        varchar(10) code NOT NULL
        integer user_id NOT NULL
    }
    ttgen_instructor {
        integer id PK
        varchar(6) uid NOT NULL
        varchar(100) name NOT NULL
        varchar(50) designation NOT NULL
        integer unsigned max_workload NOT NULL
        integer user_id NOT NULL
    }
    ttgen_meetingtime {
        integer id PK
        varchar(5) pid NOT NULL
        varchar(15) day NOT NULL
        varchar(2) time NOT NULL
        integer user_id NOT NULL
    }
    ttgen_profile {
        integer id PK
        varchar(50) role NOT NULL
        varchar(100) avatar NOT NULL
        integer user_id NOT NULL
    }
    ttgen_room {
        integer id PK
        varchar(50) r_number NOT NULL
        varchar(20) room_type NOT NULL
        varchar(50) lab_category NOT NULL
        integer unsigned seating_capacity NOT NULL
        bigint department_id NOT NULL
        integer user_id NOT NULL
    }
    ttgen_savedtimetable {
        integer id PK
        datetime created_at NOT NULL
        integer user_id
    }
    ttgen_scheduledslot {
        integer id PK
        bool is_lab NOT NULL
        bigint course_id NOT NULL
        bigint instructor_id NOT NULL
        bigint meeting_time_id NOT NULL
        bigint room_id NOT NULL
        bigint timetable_id NOT NULL
        bigint section_id NOT NULL
    }
    ttgen_scheduledslot_lab_slots {
        integer id PK
        bigint scheduledslot_id NOT NULL
        bigint meetingtime_id NOT NULL
    }
    ttgen_section {
        integer id PK
        varchar(50) section_id NOT NULL
        integer unsigned student_strength NOT NULL
        bigint department_id NOT NULL
        integer user_id NOT NULL
    }
    ttgen_section_allowed_courses {
        integer id PK
        bigint section_id NOT NULL
        bigint course_id NOT NULL
    }
    ttgen_teachersection {
        integer id PK
        bigint instructor_id NOT NULL
        bigint section_id NOT NULL
    }
    ttgen_useraccessplan {
        integer id PK
        varchar(20) plan_code NOT NULL
        varchar(100) plan_name NOT NULL
        integer unsigned amount_paid NOT NULL
        integer unsigned generations_total NOT NULL
        integer unsigned generations_used NOT NULL
        bool can_edit_delete NOT NULL
        bool can_substitute NOT NULL
        bool can_drag_drop NOT NULL
        bool is_active NOT NULL
        varchar(100) razorpay_order_id NOT NULL
        varchar(100) razorpay_payment_id NOT NULL
        datetime purchased_at NOT NULL
        integer user_id NOT NULL
    }
    user_account_profile {
        integer id PK
        date date_of_birth
        varchar(100) photo NOT NULL
        integer user_id NOT NULL
        varchar(10) role NOT NULL
    }
    ttgen_department ||--o{ ttgen_course : "id <- department_id"
    auth_user ||--o{ ttgen_course : "id <- user_id"
    ttgen_instructor ||--o{ ttgen_course_instructors : "id <- instructor_id"
    ttgen_course ||--o{ ttgen_course_instructors : "id <- course_id"
    auth_user ||--o{ ttgen_department : "id <- user_id"
    auth_user ||--o{ ttgen_instructor : "id <- user_id"
    auth_user ||--o{ ttgen_meetingtime : "id <- user_id"
    auth_user ||--o{ ttgen_profile : "id <- user_id"
    auth_user ||--o{ ttgen_room : "id <- user_id"
    ttgen_department ||--o{ ttgen_room : "id <- department_id"
    auth_user ||--o{ ttgen_savedtimetable : "id <- user_id"
    ttgen_section ||--o{ ttgen_scheduledslot : "id <- section_id"
    ttgen_savedtimetable ||--o{ ttgen_scheduledslot : "id <- timetable_id"
    ttgen_room ||--o{ ttgen_scheduledslot : "id <- room_id"
    ttgen_meetingtime ||--o{ ttgen_scheduledslot : "id <- meeting_time_id"
    ttgen_instructor ||--o{ ttgen_scheduledslot : "id <- instructor_id"
    ttgen_course ||--o{ ttgen_scheduledslot : "id <- course_id"
    ttgen_meetingtime ||--o{ ttgen_scheduledslot_lab_slots : "id <- meetingtime_id"
    ttgen_scheduledslot ||--o{ ttgen_scheduledslot_lab_slots : "id <- scheduledslot_id"
    auth_user ||--o{ ttgen_section : "id <- user_id"
    ttgen_department ||--o{ ttgen_section : "id <- department_id"
    ttgen_course ||--o{ ttgen_section_allowed_courses : "id <- course_id"
    ttgen_section ||--o{ ttgen_section_allowed_courses : "id <- section_id"
    ttgen_section ||--o{ ttgen_teachersection : "id <- section_id"
    ttgen_instructor ||--o{ ttgen_teachersection : "id <- instructor_id"
    auth_user ||--o{ ttgen_useraccessplan : "id <- user_id"
    auth_user ||--o{ user_account_profile : "id <- user_id"
```

## Regenerate

```powershell
python scripts/generate_schema_diagram.py --db db.sqlite3 --mode app --out docs/schema_app.mmd
python scripts/generate_schema_diagram.py --db db.sqlite3 --mode full --out docs/schema_full.mmd
python scripts/generate_schema_diagram.py --db db.sqlite3 --mode app --out docs/schema_app.svg
python scripts/generate_schema_diagram.py --db db.sqlite3 --mode full --out docs/schema_full.svg
```

Use any Mermaid-compatible editor or Markdown preview extension to render the Mermaid files, or open the SVG files directly as images.
