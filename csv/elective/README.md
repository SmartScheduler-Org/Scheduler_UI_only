# Elective Feature Test Data

## Test Scenario

3 sections (EL-A, EL-B, EL-C) each have regular theory + shared elective subjects.

### Shared Elective Groups

| shared_group | Sections sharing it       | Subject        | Teacher |
|--------------|---------------------------|----------------|---------|
| PY_G1        | EL-A + EL-B + EL-C        | ELEC-PYTHON    | ET07    |
| ML_G1        | EL-A + EL-B               | ELEC-ML        | ET08    |
| JAVA_G1      | EL-B + EL-C               | ELEC-JAVA      | ET09    |

**Key test cases:**
- PY_G1 = 3 sections share 1 Python slot (same room, same teacher, same time)
- EL-B has PY_G1 + ML_G1 + JAVA_G1 → elective-vs-elective allowed at same slot
- ML and JAVA can run simultaneously for EL-B (different student subsets)

### Expected timetable behavior
- ELEC-PYTHON appears in EL-A, EL-B, EL-C timetables at the SAME slot
- ELEC-ML appears in EL-A and EL-B at the SAME slot
- ELEC-JAVA appears in EL-B and EL-C at the SAME slot
- EL-B may show ELEC-ML and ELEC-JAVA at the same slot (OK — different students)

---

## Upload Order

Upload these CSVs in the exact order below (each step = one page in the UI):

1. **Department** → `department.csv`
   - Upload on: Add Departments page

2. **Rooms** → `rooms.csv`
   - Upload on: Add Rooms page

3. **Teachers** → `teachers.csv`
   - Upload on: Add Teachers page

4. **Sections** → `sections.csv`
   - Upload on: Add Sections page

5. **Subjects** → `subjects.csv`
   - Upload on: Add Subjects page

6. **Section → Subject mapping** → `section_subject.csv`
   - Upload on: **Map Section Subjects** page
   - This CSV has the new `shared_group` column (3rd column)
   - Rows without shared_group = regular subjects
   - Rows with shared_group = shared elective (e.g., PY_G1)

7. **Teacher → Subject mapping** → `subject_teacher.csv`
   - Upload on: **Map Teacher Subjects** page
   - For shared electives, give the SAME teacher UID across all sections in the group
   - (ET07 for ELEC-PYTHON in EL-A, EL-B, and EL-C)

---

## What to Verify After Generation

1. **ELEC-PYTHON slot**: Open timetables for EL-A, EL-B, EL-C.
   - All three should show Python Programming at the exact same day + time slot.
   - All three should show the same room (EL-LH1/2/3) and teacher (ET07).

2. **ELEC-ML slot**: Open EL-A and EL-B timetables.
   - Both should show Machine Learning at the same day + slot.
   - Room and teacher (ET08) should match.

3. **ELEC-JAVA slot**: Open EL-B and EL-C timetables.
   - Both should show Advanced Java at the same slot.
   - Room and teacher (ET09) should match.

4. **EL-B has 3 electives**: EL-B timetable may show ELEC-ML and ELEC-JAVA
   at the same slot (this is correct — different student subsets choose each).

5. **No overlap with theory**: None of the elective slots should clash with
   the section's own regular theory classes (EL-T1 to EL-T6).
