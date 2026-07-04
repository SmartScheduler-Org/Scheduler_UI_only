"""
Diagnostic management command: run the real timetable generator against ANY
user's saved data (from whichever DB the app is pointed at) and report, per
department and per section, whether every required class/lab was scheduled.

Sections where everything fits are marked OK. Sections with unscheduled
subjects are listed with the exact reason for each missing subject (teacher not
mapped, required lab category unavailable, workshop room missing, no
conflict-free slot, etc.) — the same reasons the web UI shows.

USAGE (run from Scheduler_UI_only/projttgs):

    # by username (positional)
    ../.venv/bin/python manage.py diagnose_schedule schedule_01

    # by email or user id instead
    ../.venv/bin/python manage.py diagnose_schedule --email coordinator@jcboseust.ac.in
    ../.venv/bin/python manage.py diagnose_schedule --user-id 52

    # limit to one department, run more generation attempts, machine-readable
    ../.venv/bin/python manage.py diagnose_schedule schedule_01 --department CSE
    ../.venv/bin/python manage.py diagnose_schedule schedule_01 --attempts 6
    ../.venv/bin/python manage.py diagnose_schedule schedule_01 --json > report.json

    # EVERY user in the database at once (one combined report + grand summary)
    ../.venv/bin/python manage.py diagnose_schedule --all-users
    ../.venv/bin/python manage.py diagnose_schedule --all-users --json > all.json

The command is read-only: it never writes to the database.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ttgen import views_other as core


def _selection_key(schedule):
    """Rank a generated schedule: fewest hard conflicts, then most scheduled
    labs, then most total scheduled events, then fitness. Uses the real app's
    own selection key when the private generator is loaded so a diagnostic run
    picks exactly the same 'best' layout the production generator would."""
    app_key = getattr(core, "_generated_schedule_selection_key", None)
    if callable(app_key):
        return app_key(schedule)
    classes = list(schedule.get_classes())
    labs = list(schedule.get_labs())
    conflicts = getattr(schedule, "_numberOfConflicts", 0) or 0
    return (
        -conflicts,
        len(labs),
        len(classes) + len(labs),
        len(classes),
        round(schedule.get_fitness(), 6),
    )


class Command(BaseCommand):
    help = (
        "Run the timetable generator for a user's data and report, per "
        "department/section, which sections scheduled fully (OK) and which "
        "subjects could not be scheduled and why."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            nargs="?",
            default=None,
            help="Username of the account whose data to diagnose.",
        )
        parser.add_argument("--email", default=None, help="Select the user by email instead of username.")
        parser.add_argument("--user-id", type=int, default=None, help="Select the user by primary key.")
        parser.add_argument(
            "--all-users",
            action="store_true",
            help="Diagnose EVERY user in the database that has sections. "
                 "Runs the generator once per user and prints a combined report.",
        )
        parser.add_argument(
            "--attempts",
            type=int,
            default=None,
            help="Number of independent generation attempts (best result kept). "
                 "Default: auto (8 for large datasets, 4 otherwise).",
        )
        parser.add_argument("--department", default=None, help="Only report sections in this department code (e.g. CSE).")
        parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report instead of text.")
        parser.add_argument("--show-ok-subjects", action="store_true", help="Also list scheduled subjects for OK sections.")
        parser.add_argument(
            "--static",
            action="store_true",
            help="Fast data-feasibility check ONLY (no generator run). Reports per "
                 "section/subject data blockers (teacher not mapped, lab category/"
                 "specific room/workshop room missing) in seconds. Cannot detect "
                 "dynamic slot conflicts. Auto-used for very large datasets.",
        )
        parser.add_argument(
            "--generate",
            action="store_true",
            help="Force the full generator run even for large datasets "
                 "(can take many minutes). Overrides the auto static mode.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        core.ensure_private_generator_loaded()
        if not getattr(core, "GENERATOR_ALGO_AVAILABLE", False):
            raise CommandError(
                "Private generator algorithm not loaded. Check TTGEN_PRIVATE_DIR / "
                "views_other_algorithm.py is reachable."
            )

        as_json = options.get("json")

        if options.get("all_users"):
            users = self._resolve_all_users()
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"Diagnosing ALL {len(users)} user(s) with sections."
            ))
            per_user = []
            for index, user in enumerate(users, start=1):
                self.stdout.write("")
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"===== USER {index}/{len(users)}: id={user.id} "
                    f"username={user.get_username()!r} "
                    f"email={getattr(user, 'email', '')!r} ====="
                ))
                try:
                    report = self._diagnose_one_user(user, options)
                except Exception as exc:  # keep going for the remaining users
                    self.stdout.write(self.style.ERROR(
                        f"  !! diagnosis failed for this user: {exc}"
                    ))
                    report = None
                if report is not None and not as_json:
                    self._print_text(report, options.get("show_ok_subjects", False))
                per_user.append({
                    "user_id": user.id,
                    "username": user.get_username(),
                    "email": getattr(user, "email", ""),
                    "report": report,
                })
            if as_json:
                self.stdout.write(json.dumps(per_user, indent=2, default=str))
            else:
                self._print_grand_summary(per_user)
            return

        # ---- single user ----
        user = self._resolve_user(options)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Diagnosing user id={user.id} username={user.get_username()!r} "
            f"email={getattr(user, 'email', '')!r}"
        ))
        report = self._diagnose_one_user(user, options)
        if as_json:
            self.stdout.write(json.dumps(report, indent=2, default=str))
        else:
            self._print_text(report, options.get("show_ok_subjects", False))

    # ------------------------------------------------------------------
    def _diagnose_one_user(self, user, options):
        """Run the generator (or a fast static check) for one user and return
        the structured report."""
        if self._use_static(user, options):
            self.stdout.write(self.style.WARNING(
                "  Mode: STATIC data-feasibility check (no generator run). "
                "Dynamic slot conflicts are NOT simulated."
            ))
            self.stdout.flush()
            return self._static_report(user, options.get("department"))

        schedule = self._generate_best(user, options.get("attempts"))
        classes = list(schedule.get_classes())
        labs = list(schedule.get_labs())
        self.stdout.write(
            f"Best layout: {len(classes)} theory + {len(labs)} lab sessions placed, "
            f"conflicts={getattr(schedule, '_numberOfConflicts', 0)}."
        )
        tables = core.build_section_tables(classes, labs, user=user)
        return self._build_report(tables, options.get("department"))

    # ------------------------------------------------------------------
    def _use_static(self, user, options):
        """Decide whether to run the fast static check instead of the generator."""
        if options.get("generate"):
            return False
        if options.get("static"):
            return True
        # Auto: very large datasets are impractical to fully generate here.
        from ttgen.models import Section, Subject

        n_sections = Section.objects.filter(user=user).count()
        n_subjects = Subject.objects.filter(user=user).count()
        return n_sections >= 40 or n_subjects >= 300

    # ------------------------------------------------------------------
    def _static_report(self, user, department_filter):
        """Instant data-feasibility report: for every section's required
        subjects, flag the ones that CANNOT be scheduled for a data reason
        (teacher not mapped, lab category/specific room/workshop room missing).
        Mirrors the reason strings the web UI shows. Does not simulate slot
        conflicts, so sections with no data blocker are reported OK."""
        from ttgen.models import Section, Room, SectionSubjectMapping

        dept_filter = (department_filter or "").strip().casefold() or None

        all_rooms = list(Room.objects.filter(user=user))
        lab_rooms = [r for r in all_rooms if r.room_type == "Lab"]

        sections = Section.objects.filter(user=user).select_related("department")
        group_map = {
            (m.section_id, m.subject_id): m.group_count
            for m in SectionSubjectMapping.objects.filter(section__user=user)
        }

        departments = {}
        for section in sorted(sections, key=lambda s: s.section_id):
            dept = section.department
            dept_code = getattr(dept, "code", "?")
            if dept_filter and dept_code.casefold() != dept_filter:
                continue

            unscheduled = []
            scheduled = []
            for subject in section.allowed_subjects.all():
                is_lab = subject.room_required == "Lab"
                group_count = max(1, group_map.get((section.id, subject.id), 1) or 1)
                required = max(1, getattr(subject, "classes_per_week", 1)) * group_count
                reason = self._static_reason(subject, all_rooms, lab_rooms)
                entry = {
                    "subject_number": subject.subject_number,
                    "name": subject.subject_name,
                    "is_lab": is_lab,
                    "required": required,
                    "scheduled": 0 if reason else required,
                    "missing": required if reason else 0,
                    "reason": reason,
                }
                (unscheduled if reason else scheduled).append(entry)

            section_report = {
                "section_id": section.section_id,
                "ok": not unscheduled,
                "total_missing_classes": sum(e["missing"] for e in unscheduled),
                "unscheduled": unscheduled,
                "scheduled": scheduled,
            }
            bucket = departments.setdefault(dept_code, {
                "code": dept_code,
                "name": getattr(dept, "name", ""),
                "sections": [],
            })
            bucket["sections"].append(section_report)

        for bucket in departments.values():
            bucket["sections"].sort(key=lambda s: s["section_id"])
        ordered = [departments[k] for k in sorted(departments)]
        total_sections = sum(len(d["sections"]) for d in ordered)
        ok_sections = sum(1 for d in ordered for s in d["sections"] if s["ok"])
        return {
            "mode": "static",
            "departments": ordered,
            "summary": {
                "departments": len(ordered),
                "sections": total_sections,
                "ok_sections": ok_sections,
                "not_ok_sections": total_sections - ok_sections,
            },
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _static_reason(subject, all_rooms, lab_rooms):
        """Data-level blocker for a subject, or "" if the data is schedulable.
        Uses the generator's own normalization helpers for accuracy."""
        if not subject.instructors.exists():
            return "Teacher not mapped"
        if subject.room_required != "Lab":
            return ""
        specific_tokens = [
            t for t in core.normalize_specific_rooms(
                getattr(subject, "specific_rooms", "") or ""
            ).split(";") if t
        ]
        if specific_tokens:
            resolved = [r for r in all_rooms if r.r_number in specific_tokens]
            return "" if resolved else "Assigned specific room unavailable"
        categories = core.normalize_lab_categories(
            getattr(subject, "required_lab_category", "") or ""
        )
        matching = [
            r for r in lab_rooms
            if not categories or core.lab_category_matches(r.lab_category, categories)
        ]
        if categories and not matching:
            return "Required lab category unavailable"
        if len(categories) > 1:
            missing = [
                c for c in categories
                if not any(core.lab_category_matches(r.lab_category, [c]) for r in lab_rooms)
            ]
            if missing:
                return ("Workshop style can't be implemented — no room for: "
                        + ", ".join(missing))
        return ""

    # ------------------------------------------------------------------
    def _resolve_all_users(self):
        """Every user that owns at least one section, ordered by id."""
        from ttgen.models import Section

        User = get_user_model()
        user_ids = (
            Section.objects.values_list("user_id", flat=True).distinct()
        )
        users = list(User.objects.filter(pk__in=list(user_ids)).order_by("id"))
        if not users:
            raise CommandError("No users with any sections were found in this database.")
        return users

    # ------------------------------------------------------------------
    def _resolve_user(self, options):
        User = get_user_model()
        if options.get("user_id") is not None:
            try:
                return User.objects.get(pk=options["user_id"])
            except User.DoesNotExist:
                raise CommandError(f"No user with id={options['user_id']}")
        if options.get("email"):
            match = User.objects.filter(email__iexact=options["email"]).first()
            if not match:
                match = User.objects.filter(email__icontains=options["email"]).first()
            if not match:
                raise CommandError(f"No user with email matching {options['email']!r}")
            return match
        if options.get("username"):
            match = User.objects.filter(username__iexact=options["username"]).first()
            if not match:
                raise CommandError(f"No user with username {options['username']!r}")
            return match
        raise CommandError(
            "Provide a user: give a username positionally, or use --email / --user-id."
        )

    # ------------------------------------------------------------------
    def _generate_best(self, user, attempts):
        core.data = core.get_data(user)
        sections = core.data.get_sections()
        subjects = core.data.get_subjects()
        large = len(sections) >= 30 or len(subjects) >= 150

        original_pop = core.POPULATION_SIZE
        original_passes = getattr(core, "INITIALIZE_SCHEDULE_PASSES", 3)
        original_prefilled_classes = getattr(core, "PREFILLED_LOCKED_CLASSES", [])
        original_prefilled_labs = getattr(core, "PREFILLED_LOCKED_LABS", [])

        # Mirror the real app's generation effort so the report reflects what
        # production would actually schedule (not a pessimistic single draw).
        # Production uses best-of-8 with Population(2) on large datasets and
        # best-of-4 on small ones, keeping the most-complete layout and early
        # stopping once every placeable lab is placed.
        if attempts is None:
            attempts = 8 if large else 4

        if large:
            self.stdout.write(self.style.WARNING(
                f"  Large dataset ({len(sections)} sections, {len(subjects)} subjects): "
                f"running best-of-{attempts} (same effort as the live app). This can "
                f"take a few minutes — it is NOT hung. It early-stops once every "
                f"placeable lab is placed."
            ))
            self.stdout.flush()

        best = None
        best_key = None
        try:
            # No prefilled/locked slots for a clean diagnostic run.
            core.PREFILLED_LOCKED_CLASSES = []
            core.PREFILLED_LOCKED_LABS = []
            if large:
                # Two candidate layouts per attempt (matches production): gives a
                # lab that fails to place in one random layout a second chance,
                # and the completeness-aware selection keeps the better one.
                core.POPULATION_SIZE = 2
                core.INITIALIZE_SCHEDULE_PASSES = 1

            for attempt in range(1, attempts + 1):
                self.stdout.write(f"  attempt {attempt}/{attempts}: building layout...")
                self.stdout.flush()
                population = core.Population(core.POPULATION_SIZE)
                candidate = max(population.get_schedules(), key=_selection_key)
                key = _selection_key(candidate)
                if best_key is None or key > best_key:
                    best, best_key = candidate, key
                missed_labs = self._count_missed_labs(best, core.data)
                self.stdout.write(
                    f"  attempt {attempt}/{attempts} done: "
                    f"placed={len(candidate.get_classes()) + len(candidate.get_labs())} "
                    f"conflicts={getattr(candidate, '_numberOfConflicts', 0)} "
                    f"(best so far missed labs={missed_labs})"
                )
                self.stdout.flush()
                if missed_labs == 0:
                    break
        finally:
            core.POPULATION_SIZE = original_pop
            core.INITIALIZE_SCHEDULE_PASSES = original_passes
            core.PREFILLED_LOCKED_CLASSES = original_prefilled_classes
            core.PREFILLED_LOCKED_LABS = original_prefilled_labs

        if best is None:
            raise CommandError("Generation produced no schedule.")
        return best

    @staticmethod
    def _count_missed_labs(schedule, data):
        placed = {}
        for lab in schedule.get_labs():
            key = (str(getattr(lab, "section", "")), lab.subject.pk)
            placed[key] = placed.get(key, 0) + 1
        missed = 0
        for section in data.get_sections():
            for subject in data.get_non_elective_allowed_subjects(section):
                if getattr(subject, "room_required", None) != "Lab":
                    continue
                group_count = max(1, core.get_section_subject_group_count(section, subject))
                required = max(1, getattr(subject, "classes_per_week", 1)) * group_count
                missed += max(0, required - placed.get((str(section.section_id), subject.pk), 0))
        return missed

    # ------------------------------------------------------------------
    def _build_report(self, tables, department_filter):
        dept_filter = (department_filter or "").strip().casefold() or None
        departments = {}
        for table in tables:
            section = table["section"]
            dept = section.department
            dept_code = getattr(dept, "code", "?")
            if dept_filter and dept_code.casefold() != dept_filter:
                continue

            unscheduled = []
            scheduled = []
            for subject in table["subject_counts"]:
                entry = {
                    "subject_number": subject.get("subject_number", ""),
                    "name": subject["name"],
                    "is_lab": subject["is_lab"],
                    "required": subject["required"],
                    "scheduled": subject["count"],
                    "missing": subject["missing"],
                    "reason": (subject.get("reason") or "").strip(),
                }
                if subject["missing"] > 0:
                    unscheduled.append(entry)
                else:
                    scheduled.append(entry)

            section_report = {
                "section_id": section.section_id,
                "ok": table["total_missing_classes"] == 0 and not unscheduled,
                "total_missing_classes": table["total_missing_classes"],
                "unscheduled": unscheduled,
                "scheduled": scheduled,
            }
            bucket = departments.setdefault(dept_code, {
                "code": dept_code,
                "name": getattr(dept, "name", ""),
                "sections": [],
            })
            bucket["sections"].append(section_report)

        # stable ordering
        for bucket in departments.values():
            bucket["sections"].sort(key=lambda s: s["section_id"])
        ordered = [departments[k] for k in sorted(departments)]

        total_sections = sum(len(d["sections"]) for d in ordered)
        ok_sections = sum(1 for d in ordered for s in d["sections"] if s["ok"])
        return {
            "departments": ordered,
            "summary": {
                "departments": len(ordered),
                "sections": total_sections,
                "ok_sections": ok_sections,
                "not_ok_sections": total_sections - ok_sections,
            },
        }

    # ------------------------------------------------------------------
    def _print_text(self, report, show_ok_subjects):
        for dept in report["departments"]:
            dept_sections = dept["sections"]
            ok_count = sum(1 for s in dept_sections if s["ok"])
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"### {dept['code']} — {dept['name']}  "
                f"({ok_count}/{len(dept_sections)} sections OK)"
            ))
            for section in dept_sections:
                if section["ok"]:
                    line = f"  [OK]  {section['section_id']}"
                    self.stdout.write(self.style.SUCCESS(line))
                    if show_ok_subjects:
                        for subj in section["scheduled"]:
                            self.stdout.write(
                                f"          {subj['subject_number']} {subj['name']} "
                                f"({subj['scheduled']}/{subj['required']})"
                            )
                else:
                    line = (
                        f"  [NOT OK]  {section['section_id']}  "
                        f"— {section['total_missing_classes']} missing slot(s)"
                    )
                    self.stdout.write(self.style.ERROR(line))
                    for subj in section["unscheduled"]:
                        kind = "LAB" if subj["is_lab"] else "class"
                        reason = subj["reason"] or "No conflict-free slot available"
                        self.stdout.write(
                            f"          - [{kind}] {subj['subject_number']} {subj['name']}: "
                            f"scheduled {subj['scheduled']}/{subj['required']} "
                            f"(missing {subj['missing']}) -> {reason}"
                        )

        summary = report["summary"]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 60))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"SUMMARY: {summary['ok_sections']}/{summary['sections']} sections OK "
            f"across {summary['departments']} departments "
            f"({summary['not_ok_sections']} need attention)."
        ))

    # ------------------------------------------------------------------
    def _print_grand_summary(self, per_user):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("#" * 60))
        self.stdout.write(self.style.MIGRATE_HEADING("GRAND SUMMARY (all users)"))
        self.stdout.write(self.style.MIGRATE_HEADING("#" * 60))
        total_sections = 0
        total_ok = 0
        for item in per_user:
            report = item["report"]
            if report is None:
                self.stdout.write(self.style.ERROR(
                    f"  {item['username']!r} (id={item['user_id']}): FAILED"
                ))
                continue
            s = report["summary"]
            total_sections += s["sections"]
            total_ok += s["ok_sections"]
            style = self.style.SUCCESS if s["not_ok_sections"] == 0 else self.style.WARNING
            self.stdout.write(style(
                f"  {item['username']!r} (id={item['user_id']}): "
                f"{s['ok_sections']}/{s['sections']} sections OK "
                f"across {s['departments']} depts "
                f"({s['not_ok_sections']} need attention)."
            ))
        self.stdout.write(self.style.MIGRATE_HEADING("-" * 60))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"TOTAL: {total_ok}/{total_sections} sections OK across "
            f"{len(per_user)} user(s) "
            f"({total_sections - total_ok} need attention)."
        ))
