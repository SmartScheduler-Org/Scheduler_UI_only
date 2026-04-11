// ============================================================
//  SmartScheduler Chatbot — Client-Side Knowledge Base + UI Engine
//  All responses are instant (no server calls).
// ============================================================

(function () {
  "use strict";

  // ── STOP WORDS — ignored during matching ────────────────────
  const STOP_WORDS = new Set([
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "shall", "may", "might", "can", "must", "need",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "its", "this", "that", "these", "those",
    "what", "which", "who", "whom", "whose", "where", "when", "why",
    "how", "if", "then", "so", "but", "and", "or", "not", "no", "yes",
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "up",
    "out", "about", "into", "over", "after", "before", "between",
    "under", "above", "just", "also", "very", "too", "quite",
    "am", "im", "dont", "cant", "wont", "isnt", "arent",
    "tell", "me", "please", "plz", "pls", "know", "want",
    "give", "get", "got", "thing", "things", "some", "any",
    "there", "here", "more", "much", "many", "all", "each",
    "really", "actually", "basically", "like", "dude", "bro",
    "while", "during", "when", "still", "yet", "already",
    "your", "our", "their", "whats", "hows", "whos", "does",
    "platform", "system", "tool", "website", "app", "site"
  ]);

  // ── KNOWLEDGE BASE ──────────────────────────────────────────
  // Each entry has:
  //   - tags: short meaningful keywords (1-2 words each) for matching
  //   - answer: the response text
  //   - priority: higher = preferred when scores are close

  const KB = [
    // ─── GENERAL / WHAT IS SCHEDULOAI ───
    {
      tags: ["scheduloai", "introduction", "explain", "overview"],
      answer: "**SmartScheduler** is an AI-powered automatic timetable generation platform built specifically for colleges, schools, and institutes.\n\n**The Problem We Solve:**\nCreating academic timetables manually takes weeks of painful back-and-forth — juggling teacher availability, room conflicts, lab slots, and workload balancing. Most coordinators dread it every semester.\n\n**Our Solution:**\nSmartScheduler uses a hybrid **Genetic Algorithm + Particle Swarm Optimization (PSO)** engine that generates a complete, clash-free, optimized timetable in just **3-8 seconds**. You simply input your departments, teachers, rooms, courses, sections, and time slots — and the AI handles everything else.\n\n**What makes us different:**\n• Zero conflicts — guaranteed by hard constraint validation\n• Fair workload — AI distributes hours evenly across faculty\n• Lab-smart — handles 4-slot continuous labs with room-category matching\n• 9 solutions — choose the best from 9 optimized candidates\n• Edit after generation — add, swap, or substitute any slot\n• PDF export — one-click professional timetable downloads\n\nBuilt with ❤️ by Sanjeevan, Ishaanvi, Tushar & Pramod.\n📞 Questions? Call **8406043847**",
      priority: 1
    },

    // ─── HOW DOES IT WORK (PROCESS FLOW) ───
    {
      tags: ["work", "working", "how work", "platform work", "process", "flow", "pipeline", "behind scenes", "how does", "mechanism", "function"],
      answer: "Here's exactly how SmartScheduler works — from start to finish:\n\n**📥 STEP 1: Input Your Data**\nYou enter (or CSV-import) all your academic data:\n• Departments (CS, IT, ECE, etc.)\n• Teachers with workload limits\n• Rooms & Labs with seating capacity and lab categories\n• Courses linked to instructors\n• Sections (student batches) mapped to courses\n• Time slots (9 per day, Monday-Friday)\n\n**🧠 STEP 2: AI Generation (3-8 seconds)**\nWhen you click 'Generate', the engine:\n① Creates 9 random timetable candidates (population)\n② Scores each one using a fitness function (fewer conflicts = higher score)\n③ Selects the best via tournament selection\n④ Crossover — combines the best schedules to create even better ones\n⑤ Mutation (5% rate) — introduces random changes to avoid getting stuck\n⑥ Repeats for multiple generations until optimization peaks\n⑦ (Optional) PSO refinement — fine-tunes with 25 swarm iterations for extra polish\n\n**🔒 What It Checks Automatically:**\n• No teacher teaching 2 classes at once\n• No room double-booked\n• No student section with overlapping classes\n• Labs only in matching lab rooms (electronics lab → electronics room)\n• Teacher workload within limits\n• Lunch break (Slot 5) always kept free\n• Max 2 consecutive classes per teacher\n• Compact student schedules with minimal gaps\n\n**📊 STEP 3: Pick Your Favorite**\nYou get 9 optimized solutions to browse — each is a complete valid timetable. Pick the one that suits your institution best.\n\n**✏️ STEP 4: Fine-Tune & Export**\nAfter saving, you can still edit individual slots, substitute teachers, or add/remove classes. When ready, export as a professional PDF.\n\n📞 Need a walkthrough? Call **8406043847**",
      priority: 15
    },

    // ─── TEAM / FOUNDERS ───
    {
      tags: ["built", "made", "team", "developers", "created", "founder", "founders", "members", "sanjeevan", "ishaanvi", "tushar", "pramod", "who made", "who built", "who created"],
      answer: "SmartScheduler was built by a passionate team of 4 developers:\n\n👨‍💻 **Sanjeevan** — Co-founder & Developer\n👩‍💻 **Ishaanvi** — Co-founder & Developer\n👨‍💻 **Tushar** — Co-founder & Developer\n👨‍💻 **Pramod** — Co-founder & Developer\n\nTogether they form **Team SmartScheduler** — driven by the mission of solving real-world academic scheduling problems using AI and optimization algorithms. They've experienced the pain of manual timetabling firsthand and built this platform to eliminate it for every institution.\n\n📞 Want to connect with the team? Call **8406043847**",
      priority: 10
    },
    {
      tags: ["sanjeevan"],
      answer: "**Sanjeevan** is one of the 4 co-founders and developers of SmartScheduler. He is part of **Team SmartScheduler** along with Ishaanvi, Tushar, and Pramod. Together they built this AI-powered timetable generation platform to solve the chaos of manual scheduling in educational institutions.\n\n📞 Reach the team: **8406043847**",
      priority: 12
    },
    {
      tags: ["ishaanvi"],
      answer: "**Ishaanvi** is one of the 4 co-founders and developers of SmartScheduler. She is part of **Team SmartScheduler** along with Sanjeevan, Tushar, and Pramod. Together they built this AI-powered timetable generation platform to solve the chaos of manual scheduling in educational institutions.\n\n📞 Reach the team: **8406043847**",
      priority: 12
    },
    {
      tags: ["tushar"],
      answer: "**Tushar** is one of the 4 co-founders and developers of SmartScheduler. He is part of **Team SmartScheduler** along with Sanjeevan, Ishaanvi, and Pramod. Together they built this AI-powered timetable generation platform to solve the chaos of manual scheduling in educational institutions.\n\n📞 Reach the team: **8406043847**",
      priority: 12
    },
    {
      tags: ["pramod"],
      answer: "**Pramod** is one of the 4 co-founders and developers of SmartScheduler. He is part of **Team SmartScheduler** along with Sanjeevan, Ishaanvi, and Tushar. Together they built this AI-powered timetable generation platform to solve the chaos of manual scheduling in educational institutions.\n\n📞 Reach the team: **8406043847**",
      priority: 12
    },

    // ─── TAGLINE ───
    {
      tags: ["tagline", "slogan", "motto"],
      answer: "Our tagline is: **'Timetables without chaos. Done in seconds.'**\n\nIt perfectly captures what SmartScheduler does — replaces weeks of stressful manual work with a single click that generates an optimized, clash-free timetable in 3-8 seconds. No chaos. No conflicts. Just smart scheduling.",
      priority: 3
    },

    // ─── FEATURES ───
    {
      tags: ["features", "capabilities", "functionality", "list features", "what can"],
      answer: "Here's everything SmartScheduler can do for your institution:\n\n**🧠 AI & Optimization:**\n1. **Genetic Algorithm + PSO Engine** — Finds the most optimized schedule using evolutionary AI\n2. **Clash-Free Guarantee** — Automatically eliminates all teacher, room, and section conflicts\n3. **9 Solutions At Once** — Generates 9 different optimized candidates to choose from\n\n**📚 Academic Intelligence:**\n4. **Lab Scheduling** — 4-slot continuous blocks with category matching (Electronics, Chemistry, etc.)\n5. **Balanced Workload** — Distributes hours fairly across faculty, max 5 classes/day\n6. **NEP 2020 Ready** — Flexible credits, electives, multi-discipline support\n7. **Lunch Break Protection** — Slot 5 is always kept free\n\n**🛠️ Management Tools:**\n8. **CSV Bulk Import** — Upload departments, teachers, rooms, courses, sections in seconds\n9. **Post-Generation Editing** — Add, update, delete, or substitute any slot after saving\n10. **Teacher Substitution** — Swap instructors for specific classes instantly\n\n**📤 Output & Access:**\n11. **PDF Export** — One-click professional timetable downloads\n12. **Role-Based Access** — Admin/Dean gets full control, Teachers get read-only views\n13. **Separate Views** — Auto-generated teacher-wise and student-wise timetables\n14. **Saved History** — Save and revisit any previously generated timetable\n\n📞 Want a demo? Call **8406043847**",
      priority: 2
    },
    {
      tags: ["clash", "conflict", "clashes", "conflicts", "clash-free", "collision", "double booking"],
      answer: "**Zero clashes — guaranteed.** This is SmartScheduler's core promise.\n\nThe AI engine uses real-time O(1) lookup indices to detect and prevent every type of conflict before the timetable is even shown to you:\n\n🔴 **Teacher double-booking** — A teacher can never be assigned to two classes at the same time. The engine tracks every teacher's schedule across all days and slots.\n\n🔴 **Room double-booking** — No two classes will ever be placed in the same room at the same time. Room occupancy is tracked per slot.\n\n🔴 **Section overlap** — Students in a section will never have two classes scheduled simultaneously.\n\n🔴 **Lab mismatch** — A chemistry course will never be assigned to an electronics lab. Lab categories are strictly matched.\n\n🔴 **Workload overflow** — Teachers will never exceed their configured maximum hours. The engine respects individual workload limits.\n\nThese are **hard constraints** — the engine will reject any solution that violates even one of them. What you see is always 100% conflict-free.",
      priority: 3
    },
    {
      tags: ["genetic algorithm", "algorithm", "ai engine", "optimization", "ga engine"],
      answer: "**The Brain Behind SmartScheduler — Genetic Algorithm + PSO**\n\nSmartScheduler uses a nature-inspired approach to solve the scheduling problem:\n\n**🧬 Genetic Algorithm (Core Engine):**\nThink of it like evolution — survival of the fittest timetable:\n\n1. **Population** — Creates 9 random timetable candidates\n2. **Fitness Evaluation** — Scores each one (fewer conflicts = higher fitness)\n3. **Tournament Selection** — Picks the best 3 and keeps the winner\n4. **Crossover** — Combines the best schedules to create even better offspring\n5. **Elite Preservation** — The single best timetable always survives to the next generation\n6. **Mutation** (5% rate) — Random changes to avoid getting stuck in local optima\n7. **Repeat** — Runs for multiple generations until the optimal solution emerges\n\n**🐦 PSO Refinement (Optional Boost):**\nAfter GA finishes, Particle Swarm Optimization can fine-tune the result:\n• 12 particles explore the solution space\n• 25 iterations of swarm intelligence\n• Typically improves fitness by 10-20%\n• Enable it with one checkbox on the generation page\n\n**Result:** 9 optimized, clash-free timetables generated in 3-8 seconds.\n\n📞 Want a technical walkthrough? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["lab", "labs", "practical", "lab scheduling", "lab blocks", "lab category", "lab duration"],
      answer: "**Lab scheduling is where most manual timetables break down.** SmartScheduler handles it natively:\n\n⏱️ **4-Slot Continuous Duration** — Labs occupy 4 consecutive time slots so students get uninterrupted practical sessions. No more split labs!\n\n🕐 **Smart Start Times** — Labs can only start at Slot 1 (morning) or Slot 6 (after lunch). This prevents labs from spanning across the lunch break at Slot 5.\n\n🏷️ **Lab Category Matching** — The engine knows that:\n• Electronics courses → Electronics labs only\n• Chemistry courses → Chemistry labs only\n• Supported categories: Electronics, Electrical, Mechanical, Chemistry, Physics, Animation, General\n\n👥 **Parallel Batch Support** — Large sections (70+ students) can be split into multiple lab batches running simultaneously in different rooms.\n\n🔗 **Lab Pairing** — Related labs are paired together (e.g., DSA Lab + AEC Lab run in the same time block for different batches).\n\n🏫 **Shared Lab Spaces** — When departments share lab rooms, the engine schedules them without any overlap.\n\n📞 Need help configuring labs? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["workload", "faculty workload", "balanced", "fair distribution", "overload", "teacher load"],
      answer: "**Fair workload = happy faculty.** SmartScheduler ensures no teacher gets an unfair deal:\n\n📊 **Maximum Workload Limit** — Each teacher has a configurable max (default: 25 units/week). The AI never assigns beyond this.\n\n📅 **Daily Limits** — No teacher gets more than 5 classes in a single day. If they're approaching the limit, the engine automatically spreads remaining classes to other days.\n\n⏰ **Consecutive Class Limit** — Max 2 back-to-back classes. No teacher is stuck teaching 3+ hours straight. The engine inserts breaks naturally.\n\n⚖️ **Even Weekly Distribution** — Hours are spread fairly across Monday-Friday. No \"death Fridays\" with 6 classes or empty Mondays with none.\n\n🎓 **Designation-Aware** — Professors, Associate Professors, and Assistant Professors can have different workload caps.\n\nThe result: a timetable that respects your faculty's time and energy.\n\n📞 Questions? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["csv", "import", "bulk import", "upload", "csv upload", "data import"],
      answer: "**Skip hours of manual data entry — use CSV import!**\n\nSmartScheduler lets you bulk-import all your institutional data from CSV files:\n\n📁 **What you can import:**\n• **Departments** — columns: `code, name`\n• **Teachers** — columns: `uid, name, designation, max_workload`\n• **Rooms** — columns: `r_number, department_code, seating_capacity, room_type, lab_category`\n• **Courses** — columns: `course_number, course_name, max_students, room_type, lab_category, classes_per_week`\n• **Sections** — columns: `section_id, department_code, student_strength`\n• **Section-Course Mapping** — which courses each section takes\n• **Instructor-Course Mapping** — which teachers teach which courses\n\n**How to use:**\n1. Prepare your CSV file with the correct column headers\n2. Go to the relevant management page (e.g., Add Teachers)\n3. Click the CSV upload button\n4. All records are created instantly\n\n💡 **Tip:** Sample CSV files are included with the platform — use them as templates!\n\n📞 Need help with CSV format? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["pdf", "export", "download", "print", "pdf export"],
      answer: "**One click — professional PDF timetable ready for distribution.**\n\nSmartScheduler's PDF export gives you print-ready timetables:\n\n📄 **What's included:**\n• Section-wise timetable grids (5 days × 9 time slots)\n• Lab sessions expanded into individual rows for clarity\n• Teacher names, room numbers, and course details\n• Clean, professional formatting\n\n**How to export:**\n1. Go to any **Saved Timetable** page\n2. Click the **Download PDF** button\n3. Your PDF is generated and downloaded instantly\n\nPerfect for printing, emailing to faculty, or posting on notice boards.\n\n📞 Need help? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["edit", "modify", "update", "post generation", "add slot", "delete slot", "substitute", "swap teacher"],
      answer: "**Generated timetable isn't perfect? No problem — edit anything.**\n\nSmartScheduler gives you full post-generation editing power:\n\n✏️ **Add Slot** — Drop a new class or lab into any empty time slot\n🔄 **Update Slot** — Change the instructor, course, or room for any existing class\n🗑️ **Delete Slot** — Remove a class or lab you don't need\n👨‍🏫 **Substitute Teacher** — A faculty member is unavailable? Swap them out for another instructor in one click\n🔬 **Substitute Lab Teacher** — Same for lab sessions\n\n**Smart validation:** Every edit is checked in real-time against all constraints. If your change would create a conflict (teacher double-booked, room clash, etc.), the system warns you before saving.\n\nNo need to regenerate the entire timetable for small changes!\n\n📞 Need help editing? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["multiple solutions", "9 solutions", "candidates", "options", "choose timetable"],
      answer: "**Why settle for one when you can have nine?**\n\nSmartScheduler doesn't give you a single take-it-or-leave-it timetable. Instead, it generates **9 fully optimized, clash-free timetable candidates** simultaneously.\n\n**How it works:**\n• The Genetic Algorithm evolves a population of 9 schedules\n• Each one is a complete, valid timetable with its own fitness score\n• All 9 satisfy every hard constraint (no clashes, no overloads)\n• They differ in slot arrangements, room assignments, and teacher placements\n\n**What you can do:**\n1. Browse through all 9 solutions\n2. Compare how each distributes classes differently\n3. Pick the one that feels right for your institution\n4. Save your chosen timetable\n\nThis gives administrators **real choice** instead of being stuck with whatever the algorithm spits out.\n\n📞 Want to see it in action? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["nep", "nep 2020", "national education policy", "electives", "credit"],
      answer: "**Built for India's new education framework — NEP 2020.**\n\nSmartScheduler doesn't just support traditional fixed schedules. It's designed for the flexibility NEP 2020 demands:\n\n🎓 **Flexible Credit Structure** — Courses can have variable credit hours (1-10 classes per week)\n📚 **Open Electives** — Handles elective batch allocation across departments seamlessly\n🏛️ **Multi-Discipline Scheduling** — Schedule classes across CS, IT, ECE, ME, and other departments simultaneously\n📊 **Credit-Based Workload** — Aligns perfectly with NEP 2020's credit-based academic model\n🔗 **ERP Integration Ready** — API-based syncing to keep course and faculty data updated in real-time\n\nWhether your institution has already adopted NEP 2020 or is transitioning, SmartScheduler is ready.\n\n📞 Need NEP-specific configuration? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["role", "roles", "teacher role", "admin role", "dean role", "access", "permissions", "login type"],
      answer: "**Different users, different access — by design.**\n\nSmartScheduler has role-based access control to ensure each user sees only what they need:\n\n👔 **Admin / Dean:**\n• Full access to the Admin Dashboard\n• Add, edit, and delete departments, teachers, rooms, courses, sections, and timings\n• Generate timetables, save them, edit them\n• Export PDFs, manage CSV imports\n• Map teachers to courses and sections\n• Basically — full control over everything\n\n👨‍🏫 **Teacher:**\n• View their assigned section's timetable (read-only)\n• See a clean weekly view: their classes, labs, and free slots\n• Cannot modify any timetable data\n• Perfect for teachers who just need to check their schedule\n\nEach role has a separate login page. Admins enter through the Dean login, teachers through the Teacher login.\n\n📞 Need custom roles? Call **8406043847**",
      priority: 3
    },

    // ─── HOW TO USE / GUIDE ───
    {
      tags: ["guide", "steps", "getting started", "tutorial", "walkthrough", "step by step", "instructions", "user guide", "how start", "how use", "setup"],
      answer: "**Complete Getting Started Guide for SmartScheduler:**\n\n**📝 STEP 1: Create Your Account**\nGo to the registration page, sign up with your email, and login. You'll be asked to choose your role — select **Admin/Dean** for full access.\n\n**📊 STEP 2: Set Up Your Data (one-time)**\nFrom the Admin Dashboard, add your institutional data in this order:\n\n① **Departments** — Create your department codes (CS, IT, ECE, etc.)\n② **Teachers** — Add faculty with their UID, name, designation, and max workload\n③ **Rooms** — Add lecture halls and labs (set room type, lab category, capacity)\n④ **Time Slots** — Configure your daily schedule (Slots 1-9, Monday-Friday)\n⑤ **Courses** — Add subjects, link them to instructors, set room requirements\n⑥ **Sections** — Create student batches, set strength, link to department\n⑦ **Map Teachers → Sections** — Assign which teacher teaches which section\n⑧ **Map Courses → Sections** — Define which courses each section takes\n\n💡 **Pro tip:** Use CSV import to bulk-upload everything in minutes!\n\n**🚀 STEP 3: Generate!**\nClick 'Generate Timetable', toggle PSO if you want extra optimization, and wait 3-8 seconds.\n\n**🎯 STEP 4: Choose & Save**\nBrowse through 9 optimized solutions, pick your favorite, and save it.\n\n**✏️ STEP 5: Fine-Tune & Export**\nMake any manual adjustments → Export as PDF → Distribute!\n\n📞 Need hands-on help? Call **8406043847** for a walkthrough.",
      priority: 2
    },
    {
      tags: ["add department", "department setup", "departments", "create department"],
      answer: "To add a department in SmartScheduler:\n\n1. Go to the **Admin Dashboard**.\n2. Click on **Add Departments**.\n3. Fill in:\n   • **Department Code** — A unique short code (e.g., CS, IT, ECE)\n   • **Department Name** — Full name (e.g., Computer Science)\n4. Click **Save**.\n\nYou can also bulk import departments via CSV with columns: `code, name`.\n\nTo view or delete departments, go to the **Departments List** page.",
      priority: 4
    },
    {
      tags: ["add teacher", "add instructor", "teacher setup", "add faculty", "create teacher"],
      answer: "To add a teacher/instructor:\n\n1. Go to **Admin Dashboard** → **Add Teachers**.\n2. Fill in:\n   • **UID** — Unique teacher ID (e.g., GF900)\n   • **Name** — Full name (e.g., Dr. Parul Gupta)\n   • **Designation** — Professor / Associate Professor / Assistant Professor\n   • **Max Workload** — Maximum teaching hours per week (default: 25)\n3. Click **Save**.\n\n**CSV Import:** Upload a CSV with columns: `uid, name, designation, max_workload`\n\nAfter adding teachers, you'll need to map them to courses and sections.",
      priority: 4
    },
    {
      tags: ["add room", "room setup", "add lab room", "create room"],
      answer: "To add a room or lab:\n\n1. Go to **Admin Dashboard** → **Add Rooms**.\n2. Fill in:\n   • **Room Number** — Unique identifier (e.g., LT01, CC02)\n   • **Department** — Select the department\n   • **Seating Capacity** — Number of seats\n   • **Room Type** — Lecture Hall or Lab\n   • **Lab Category** (if Lab) — Electronics, Electrical, Mechanical, Chemistry, Physics, Animation, or General\n3. Click **Save**.\n\n**CSV Import:** Upload CSV with columns: `r_number, department_code, seating_capacity, room_type, lab_category`",
      priority: 4
    },
    {
      tags: ["add course", "course setup", "add subject", "create course"],
      answer: "To add a course/subject:\n\n1. Go to **Admin Dashboard** → **Add Courses**.\n2. Fill in:\n   • **Course Number** — Unique ID (e.g., CS301)\n   • **Course Name** — Full name (e.g., Data Structures)\n   • **Max Students** — Maximum enrollment\n   • **Room Required** — Lecture Hall or Lab\n   • **Lab Category** (if Lab) — Select the matching lab type\n   • **Classes Per Week** — Number of weekly sessions (1-10)\n3. Assign instructors who can teach this course.\n4. Click **Save**.",
      priority: 4
    },
    {
      tags: ["add section", "section setup", "add batch", "create section", "student batch"],
      answer: "To add a student section/batch:\n\n1. Go to **Admin Dashboard** → **Add Sections**.\n2. Fill in:\n   • **Section ID** — Unique identifier (e.g., CE31 3rd Sem)\n   • **Department** — Select the department\n   • **Student Strength** — Number of students in this section\n3. Click **Save**.\n4. After saving, map the allowed courses to this section.\n\n**CSV Import:** Upload CSV with columns: `section_id, department_code, student_strength`",
      priority: 4
    },
    {
      tags: ["add timing", "meeting time", "time slot", "timings", "schedule slots", "add time"],
      answer: "To add meeting times/time slots:\n\n1. Go to **Admin Dashboard** → **Add Timings**.\n2. Fill in:\n   • **PID** — Unique slot ID (e.g., Mo1 for Monday Slot 1)\n   • **Day** — Monday through Friday\n   • **Time Slot** — Slot 1 through Slot 9\n3. Click **Save**.\n\n**Note:** Slot 5 is automatically reserved as the lunch break. The system supports 9 time slots per day across 5 working days.\n\n**Valid lab start times:** Slot 1 (morning block) and Slot 6 (afternoon block).",
      priority: 4
    },
    {
      tags: ["map teacher", "teacher mapping", "assign teacher", "teacher section", "map instructor"],
      answer: "Teacher mapping in SmartScheduler involves two steps:\n\n**1. Teacher-Course Mapping:**\n• Go to **Map Teacher Courses** page.\n• Select a course and assign one or more instructors who can teach it.\n\n**2. Teacher-Section Mapping:**\n• Go to **Map Teacher Sections** page.\n• For theory courses, assign which instructor teaches which section.\n\nBoth mappings are essential for accurate timetable generation.",
      priority: 4
    },
    {
      tags: ["generate", "generate timetable", "create timetable", "run generation", "start generation"],
      answer: "To generate a timetable:\n\n1. Ensure all master data is set up (departments, teachers, rooms, timings, courses, sections, and mappings).\n2. Go to the **Generate** page from the Admin Dashboard.\n3. Optionally toggle **PSO Refinement** for enhanced optimization.\n4. Click **Generate Timetable**.\n5. Wait 3-8 seconds while the AI engine runs.\n6. View the **9 generated solutions** — each is a complete, clash-free timetable.\n7. Browse through them and select the best one.\n8. Click **Save** to persist your chosen timetable.\n\nIf you're not satisfied, you can regenerate anytime!",
      priority: 4
    },
    {
      tags: ["save timetable", "saving", "save schedule"],
      answer: "To save a generated timetable:\n\n1. After generation, browse the 9 candidate timetables.\n2. Select the one you prefer.\n3. Click the **Save Timetable** button.\n4. The timetable is stored in the database with a timestamp.\n5. Access it anytime from **Saved Timetables** in the dashboard.\n\nSaved timetables can be edited, exported as PDF, or deleted later.",
      priority: 4
    },
    {
      tags: ["dashboard", "admin dashboard", "admin panel", "main page"],
      answer: "The **Admin Dashboard** is your central hub in SmartScheduler. It shows:\n\n• **Quick Stats** — Total teachers, departments, and sections at a glance.\n• **Quick Links** to all management pages:\n  - Add/manage departments, teachers, rooms, timings, courses, sections\n  - Teacher-course and section-course mappings\n  - Generate new timetables\n  - View saved timetable history\n\nFrom here, you can access every feature of the platform with one click.",
      priority: 4
    },

    // ─── WHY BUY / BENEFITS ───
    {
      tags: ["buy", "purchase", "choose", "benefits", "advantages", "worth", "value", "why use", "why choose", "why buy"],
      answer: "**Why should your institution choose SmartScheduler?**\n\nHere's the honest truth — if you're still making timetables manually, you're wasting weeks every semester on a problem that AI can solve in seconds.\n\n**⏱️ Speed:** Generate a complete timetable in 3-8 seconds. Not hours. Not days. Seconds.\n\n**🔒 Accuracy:** Zero conflicts — guaranteed. No teacher double-bookings, no room clashes, no student overlaps. Ever.\n\n**⚖️ Fairness:** AI distributes workload evenly across faculty. No teacher gets overloaded while others sit idle.\n\n**🔬 Lab Intelligence:** 4-slot continuous lab blocks, category-matched rooms, parallel batch support. Labs actually work.\n\n**🎯 Choice:** 9 optimized solutions to choose from, not a single take-it-or-leave-it result.\n\n**✏️ Flexibility:** Edit any slot after generation. Substitute teachers in one click. Add or remove classes freely.\n\n**📤 Professional Output:** One-click PDF export ready for printing and distribution.\n\n**📥 Easy Setup:** CSV bulk import — set up your entire institution's data in minutes.\n\n**🌐 Zero Installation:** Runs entirely in your browser. No software to install or maintain.\n\n**🎓 Future-Proof:** NEP 2020 compliant with flexible credits and elective support.\n\n**Bottom line:** SmartScheduler replaces your most dreaded administrative task with a single click.\n\n📞 See it in action — call **8406043847** for a demo!",
      priority: 2
    },
    {
      tags: ["manual", "legacy", "old way", "traditional", "spreadsheet", "compared", "vs manual", "comparison"],
      answer: "**The old way vs. SmartScheduler — there's no comparison:**\n\n❌ **Manual/Legacy Process:**\n• Takes **weeks** of iterations and back-and-forth\n• Teacher & room clashes discovered **after classes start**\n• Lab slots adjusted manually, often breaking continuity\n• No separate views for teachers and students\n• One change means starting over from scratch\n• Workload distribution is subjective and unfair\n• Hard to accommodate NEP 2020 flexibility\n\n✅ **SmartScheduler:**\n• Generates in **3-8 seconds** with every run optimized\n• Actively **prevents all clashes** before the timetable is finalized\n• Labs are grouped into continuous, logically ordered blocks automatically\n• Teacher & student timetables auto-generated as separate views\n• Edit individual slots without regenerating the whole thing\n• AI-balanced workload — fair for every faculty member\n• Built with NEP 2020 credit structure and electives in mind\n\n**Think of it this way:** Traditional tools are spreadsheets. SmartScheduler is an **AI coordinator** that understands labs, electives, workload, and institutional rules.\n\n📞 Ready to upgrade? Call **8406043847**",
      priority: 3
    },
    {
      tags: ["target audience", "who can use", "colleges", "schools", "institutes", "university"],
      answer: "**SmartScheduler works for any educational institution that needs timetables:**\n\n🎓 **Colleges & Universities** — B.Tech, BCA, B.Sc, M.Tech, MBA — handle complex multi-department scheduling\n🏫 **Schools** — High schools and senior secondary with multiple sections per grade\n🔧 **Polytechnics & ITIs** — Technical institutes with lab-heavy schedules that need special handling\n📖 **Coaching Institutes** — Batch-based scheduling with room optimization\n🏛️ **Multi-Department Institutions** — CS, IT, ECE, ME, Civil — all scheduled together without conflicts\n\nWhether you have 5 sections or 500, 10 teachers or 100 — SmartScheduler scales to handle it.\n\n📞 Want to discuss your institution's needs? Call **8406043847**",
      priority: 3
    },

    // ─── PRICING ───
    {
      tags: ["pricing", "cost", "price", "how much", "free", "paid", "subscription", "plan", "charge", "fee", "fees", "rate", "rates", "afford", "budget", "money", "pay", "payment"],
      answer: "**Pricing is customized based on your institution's size and needs.**\n\nWe don't believe in one-size-fits-all pricing. Your plan is tailored to:\n\n📊 **Number of departments** you need to schedule\n👥 **Number of sections/batches** in your institution\n🎨 **Custom branding** — your logo, colors, and institution name\n🔗 **ERP integration** — API syncing with your existing systems\n🛠️ **Support level** — standard vs. premium support\n\nTo get a personalized quote and see SmartScheduler in action:\n\n📞 **Call our team: 8406043847**\n\nWe'll walk you through the platform, understand your requirements, and provide a quote that fits your budget. No obligation!",
      priority: 10
    },

    // ─── HOW IT WORKS (TECHNICAL ARCHITECTURE) ───
    {
      tags: ["technical", "architecture", "technology", "tech stack", "built with", "stack", "django", "python"],
      answer: "**SmartScheduler — Technical Architecture:**\n\n**🔧 Backend: Django (Python)**\n• Full-featured web framework handling authentication, data management, and API logic\n• SQLite database for reliable data storage\n• Django ORM with optimized queries (select_related, prefetch_related)\n\n**🎨 Frontend: Modern Web Stack**\n• HTML5, CSS3, JavaScript\n• Bootstrap 4 for responsive layouts\n• GSAP for smooth animations\n• Font Awesome icons + Google Fonts (Poppins)\n\n**🧠 AI Engine: Hybrid GA + PSO**\n• Genetic Algorithm — evolutionary optimization with crossover, mutation, and elite preservation\n• Particle Swarm Optimization — 12-particle swarm with 25 iterations for fine-tuning\n• O(1) conflict detection using pre-built lookup indices\n• Fitness function: `1 / (1 + total_conflicts)` with soft constraint penalties\n\n**📤 Export Stack:**\n• html2pdf.js — client-side PDF generation\n• xhtml2pdf — server-side PDF rendering\n• html2canvas — canvas-to-image conversion\n\n**🔐 Security:**\n• Django's built-in CSRF protection\n• Password hashing with Argon2/PBKDF2\n• Session-based authentication\n• Role-based access control\n\n📞 Technical questions? Call **8406043847**",
      priority: 2
    },
    {
      tags: ["fitness", "fitness function", "scoring", "constraints", "hard constraints", "soft constraints", "penalty"],
      answer: "**SmartScheduler Fitness & Constraint System:**\n\n**Fitness Formula:** `fitness = 1 / (1 + total_conflicts)`\n(Higher fitness = fewer conflicts = better timetable)\n\n**Hard Constraints (Must satisfy — violation = invalid):**\n• No teacher double-booking\n• No room double-booking\n• No section double-booking\n• Instructor workload within limits\n• Lab category must match room category\n• Teacher-section mappings must be respected\n\n**Soft Constraints (Penalties for suboptimal):**\n• Teacher: Max 5 classes/day (penalty 0.5 per extra)\n• Teacher: Max 2 consecutive classes (penalty 1 for 3rd)\n• Student: Max 2 Slot-1 classes/week (penalty 5 per extra)\n• Student: Classes should be compact, no gaps (penalty 0.5 per gap)\n• Missing theory classes: penalty 25 each",
      priority: 3
    },
    {
      tags: ["pso", "particle swarm", "swarm optimization", "pso refinement"],
      answer: "**Particle Swarm Optimization (PSO) in SmartScheduler:**\n\nPSO is an optional post-processing step that fine-tunes the timetable generated by the Genetic Algorithm:\n\n• **Swarm Size:** 12 particles\n• **Iterations:** 25 rounds of optimization\n• **How it works:** Each particle represents a modified version of the GA solution. Particles move through the solution space, sharing information about the best configurations found.\n• **Enable it:** Toggle the PSO checkbox on the generation page.\n• **When to use:** Enable PSO when you want the highest quality timetable.\n\nPSO typically produces 10-20% better fitness scores compared to GA alone.",
      priority: 5
    },
    {
      tags: ["lunch", "lunch break", "break time", "slot 5"],
      answer: "SmartScheduler automatically handles the lunch break:\n\n• **Slot 5** is reserved as the lunch break across all days.\n• No classes or labs are scheduled during Slot 5.\n• Labs are constrained to start at Slot 1 or Slot 6 to avoid spanning across the lunch period.\n• This ensures students and faculty always have an uninterrupted break.",
      priority: 5
    },
    {
      tags: ["time slots", "how many slots", "slots per day", "working days", "schedule structure"],
      answer: "**SmartScheduler Schedule Structure:**\n\n• **Working Days:** Monday through Friday (5 days)\n• **Slots Per Day:** 9 time slots\n• **Lunch Break:** Slot 5 (automatically blocked)\n• **Usable Slots:** 8 per day (40 per week per room)\n• **Lab Blocks:** 4 consecutive slots (Slot 1-4 morning block or Slot 6-9 afternoon block)\n\nMeeting times are identified by a PID format like 'Mo1' (Monday Slot 1), 'Tu3' (Tuesday Slot 3), etc.",
      priority: 5
    },

    // ─── HELPLINE / CONTACT ───
    {
      tags: ["helpline", "phone", "call", "phone number", "contact number", "support number", "customer support", "call us", "reach us", "number"],
      answer: "📞 **SmartScheduler Helpline: 8406043847**\n\nOur team is ready to help you with:\n\n🛠️ **Setup & Configuration** — Help setting up departments, rooms, courses, and mappings\n🐛 **Technical Issues** — Bug fixes, troubleshooting, and error resolution\n🎨 **Customization** — Custom branding, rules, and institution-specific constraints\n💰 **Pricing & Licensing** — Get a personalized quote for your institution\n🎥 **Demo & Walkthrough** — See SmartScheduler in action with your own data\n🔗 **ERP Integration** — API setup and data syncing\n\n**Team:** Sanjeevan, Ishaanvi, Tushar & Pramod are here to help!\n\nDon't hesitate to call — we're passionate about making your scheduling effortless.",
      priority: 5
    },
    {
      tags: ["contact", "contact us", "reach out", "get in touch", "email", "support"],
      answer: "**Get in touch with Team SmartScheduler:**\n\n📞 **Helpline:** 8406043847 (fastest way to reach us)\n📧 **Contact Form:** Available on our Contact Us page — fill it out and we'll get back to you\n\n**Our team (Sanjeevan, Ishaanvi, Tushar & Pramod) can help with:**\n• Technical support and troubleshooting\n• Platform demo and walkthrough\n• Pricing and licensing discussions\n• Customization requests\n• ERP integration queries\n\nWe respond quickly — your scheduling problems won't wait, and neither will we!",
      priority: 4
    },
    {
      tags: ["demo", "walkthrough", "live demo", "book demo", "trial", "try", "showcase"],
      answer: "**Want to see SmartScheduler in action? Two ways to try:**\n\n🎥 **Option 1: Book a Personalized Demo**\nCall us at **8406043847** and our team will:\n• Walk you through every feature\n• Show generation with sample data\n• Answer all your institution-specific questions\n• Discuss customization options\n\n💻 **Option 2: Try It Yourself (Free)**\n• Click **'Try Magic'** on the homepage → Login and explore\n• Click **'Try Generator'** → Select your role and start scheduling\n• No installation, no credit card — runs entirely in your browser\n\nWe recommend starting with our sample CSV data to see instant results!",
      priority: 4
    },

    // ─── JOIN / CAREERS ───
    {
      tags: ["join", "career", "careers", "hiring", "job", "jobs", "work with", "internship", "intern", "apply", "recruit", "recruitment", "vacancy", "openings", "position", "contribute"],
      answer: "**Interested in joining the SmartScheduler team? We'd love to hear from you!**\n\nWe're always looking for passionate people who want to build the future of academic scheduling:\n\n👨‍💻 **Developer Roles** — Python/Django backend, JavaScript frontend, AI/ML optimization\n🎨 **Design Roles** — UI/UX for educational platforms\n📊 **Data Roles** — Algorithm optimization and constraint modeling\n🎓 **Internships** — Great opportunity for students passionate about AI\n🤝 **Freelance/Collaboration** — Open to project-based partnerships\n\n**Current team:** Sanjeevan, Ishaanvi, Tushar & Pramod\n\n📞 **Call us to discuss: 8406043847**\n\nWe value skills, passion, and the drive to solve real-world problems!",
      priority: 8
    },

    // ─── TROUBLESHOOTING / COMMON QUESTIONS ───
    {
      tags: ["not working", "error", "bug", "issue", "problem", "stuck", "cannot", "doesnt work", "broken", "fix", "trouble", "crash", "fail", "error generating", "generation error", "timetable error", "generating error", "error timetable", "wrong", "failed", "unable"],
      answer: "**Something not working? Let's fix it step by step:**\n\n**🔍 Before Generating — Check These:**\n1. ✅ All **departments** are added\n2. ✅ All **teachers** are added with correct workload limits\n3. ✅ All **rooms** are added (with correct type: Lecture Hall vs Lab)\n4. ✅ All **time slots** are configured (9 per day, Monday-Friday)\n5. ✅ All **courses** are created and linked to instructors\n6. ✅ All **sections** are created with student strength\n7. ✅ **Teacher-Course mapping** is complete (which teacher teaches what)\n8. ✅ **Teacher-Section mapping** is done (which teacher teaches which section)\n9. ✅ **Course-Section mapping** is done (which section takes which courses)\n\n**🐛 Common Generation Errors:**\n• **\"No valid timetable generated\"** → A mapping is missing. Check teacher-course AND teacher-section mappings.\n• **Timetable has empty slots** → Not enough courses mapped to that section.\n• **Lab not appearing** → Verify lab category matches between course and room (e.g., Electronics course → Electronics room).\n• **Teacher overloaded** → Reduce classes per week or increase teacher's max workload.\n• **CSV not importing?** → Column headers must match exactly.\n• **Page looks broken?** → Clear browser cache (Ctrl+Shift+R).\n\n**Quick fix checklist:**\n① Go to Dashboard → check total teachers, rooms, sections count\n② Go to Map Teacher Courses → ensure every course has an instructor\n③ Go to Map Teacher Sections → ensure every theory course has section mapping\n④ Go to View Section Courses → ensure every section has courses assigned\n⑤ Try generating again\n\n**Still stuck?** Don't waste time debugging — call us:\n📞 **8406043847** — we'll help you fix it immediately!",
      priority: 8
    },
    {
      tags: ["forgot password", "reset password", "cant login", "password reset", "lost password", "password"],
      answer: "To reset your password:\n\n1. Go to the **Login** page.\n2. Click on **'Forgot Password?'** or **'Reset Password'** link.\n3. Enter your registered email address.\n4. Check your email for the password reset link.\n5. Click the link and set a new password.\n\nIf you don't receive the email, check your spam folder. For further help, call: **8406043847**.",
      priority: 5
    },
    {
      tags: ["register", "sign up", "create account", "new account", "registration", "signup"],
      answer: "To create a new SmartScheduler account:\n\n1. Go to the **Registration** page (accessible from the login page).\n2. Fill in your details:\n   • Username\n   • Email address\n   • Password (with confirmation)\n3. Click **Register**.\n4. You'll be redirected to the login page.\n5. Login with your new credentials.\n6. Select your role (Admin/Dean or Teacher).\n\nNeed help? Call **8406043847**.",
      priority: 5
    },
    {
      tags: ["browser", "compatibility", "supported browsers", "mobile", "responsive", "device"],
      answer: "SmartScheduler works across all modern platforms:\n\n• **Browsers:** Chrome, Firefox, Safari, Edge (latest versions)\n• **Devices:** Desktop, laptop, tablet, mobile\n• **Installation:** None required — runs entirely in the browser\n• **OS:** Windows, macOS, Linux, and mobile OS\n\nFor the best experience, we recommend Google Chrome on a desktop/laptop.",
      priority: 5
    },
    {
      tags: ["data safe", "security", "privacy", "data protection", "safe", "secure"],
      answer: "SmartScheduler takes data security seriously:\n\n• **Authenticated Access** — All data pages require login.\n• **Role-Based Permissions** — Teachers can only view, not modify timetables.\n• **Password Hashing** — Securely hashed using Django's built-in security.\n• **CSRF Protection** — All forms protected against cross-site request forgery.\n• **Session Management** — Automatic secure session handling.",
      priority: 5
    },
    {
      tags: ["erp", "erp integration", "api", "sync", "integrate"],
      answer: "SmartScheduler supports **API-based ERP integration**:\n\n• Sync course data, faculty information, and room details from your ERP system.\n• Keep data automatically updated without manual re-entry.\n• Supports standard API protocols for seamless connectivity.\n\nFor ERP integration setup, contact our team:\n📞 **Helpline:** 8406043847",
      priority: 5
    },
    {
      tags: ["customize", "customization", "branding", "custom rules", "white label"],
      answer: "SmartScheduler is fully customizable for your institution:\n\n• **Custom Branding** — Add your institution's logo, name, and color scheme.\n• **Custom Rules** — Configure specific scheduling constraints.\n• **Lab Pairings** — Set up custom lab pairing rules.\n• **Workload Rules** — Different limits for different designations.\n• **Compact Scheduling** — Configure max active days for specific programs.\n\nFor customization requests, contact: 📞 **8406043847**",
      priority: 5
    },
    {
      tags: ["speed", "how fast", "generation time", "how long", "time taken", "seconds", "fast"],
      answer: "SmartScheduler generates a complete, optimized, clash-free timetable in just **3-8 seconds**!\n\n• **Without PSO:** ~3-5 seconds\n• **With PSO Refinement:** ~5-8 seconds\n\nCompare that to the **weeks** it takes manually, and you'll see why institutions love SmartScheduler. One click, instant results.",
      priority: 5
    },
    {
      tags: ["sample", "example", "sample data", "sample csv", "test data", "demo data"],
      answer: "SmartScheduler comes with sample CSV files to help you get started:\n\n• **departments.csv** — Sample department codes and names\n• **teachers.csv** — Sample instructor data\n• **rooms.csv** — Sample rooms and labs\n• **courses.csv** — Sample course definitions\n• **sections.csv** — Sample student sections\n• **section_courses.csv** — Course-section mappings\n• **course_instructors.csv** — Instructor-course assignments\n\nUse these as templates to prepare your own data!",
      priority: 5
    },
    {
      tags: ["room type", "lecture hall", "seminar room", "room categories", "types rooms"],
      answer: "SmartScheduler supports multiple room types:\n\n**Room Types:**\n• **Lecture Hall** — For regular theory classes\n• **Lab** — For practical/laboratory sessions\n• **Seminar Room** — For seminars and discussions\n\n**Lab Categories:**\n• Electronics, Electrical, Mechanical, Chemistry, Physics, Animation, General\n\nWhen creating a course that needs a lab, specify the required lab category — the engine auto-assigns matching rooms.",
      priority: 5
    },
    {
      tags: ["designation", "professor", "associate professor", "assistant professor"],
      answer: "SmartScheduler supports three teacher designations:\n\n• **Professor** — Senior faculty members\n• **Associate Professor** — Mid-level faculty\n• **Assistant Professor** — Junior faculty\n\nEach designation can have different workload configurations. Default max workload is 25 units/week, customizable per teacher.",
      priority: 5
    },
    {
      tags: ["compact", "compact scheduling", "mtech", "fewer days", "active days"],
      answer: "SmartScheduler supports compact scheduling for specific programs:\n\n• **MTech 1st Sem** — Max 3 active days\n• **MTech 3rd Sem** — Max 2 active days\n\nIdeal for post-graduate programs where students have research commitments. The engine packs all classes into minimum days while maintaining all constraints.",
      priority: 5
    },
    {
      tags: ["student view", "teacher view", "faculty view", "separate views", "different views"],
      answer: "SmartScheduler auto-generates separate views from the same timetable:\n\n**Faculty/Teacher View:**\n• Weekly schedule with assigned classes, labs, and free slots.\n\n**Student/Section View:**\n• Complete weekly timetable (5 days x 9 slots grid).\n• Labs highlighted with their duration.\n\nBoth views are generated automatically — no additional setup required!",
      priority: 5
    },

    // ─── GREETINGS & META ───
    {
      tags: ["hello", "hi", "hey", "good morning", "good afternoon", "good evening", "howdy", "greetings", "hola", "sup", "yo"],
      answer: "Hey there! 👋 Welcome to **SmartScheduler** — the AI that generates timetables in seconds.\n\nI can answer anything about our platform. Try asking:\n\n💡 **\"How does the platform work?\"** — Full process explained\n⚡ **\"What are the features?\"** — Everything we can do\n🚀 **\"How do I get started?\"** — Step-by-step guide\n💰 **\"What's the pricing?\"** — Plans and quotes\n👥 **\"Who built this?\"** — Meet the team\n📞 **\"How do I contact support?\"** — Helpline info\n\nOr just type your question — I'll respond instantly!\n\n📞 Helpline: **8406043847**",
      priority: 8
    },
    {
      tags: ["thanks", "thank you", "thankyou", "ty", "appreciate", "thx"],
      answer: "You're welcome! 😊 Glad I could help.\n\nIf you have more questions later, just open this chat — I'm available 24/7. For direct human assistance, our team is a call away:\n\n📞 **8406043847** — Sanjeevan, Ishaanvi, Tushar & Pramod\n\nHappy scheduling! 🎯",
      priority: 8
    },
    {
      tags: ["bye", "goodbye", "see you", "exit", "close", "quit"],
      answer: "Goodbye! 👋 Thanks for exploring SmartScheduler.\n\nRemember — whenever you need help with timetabling, we're here:\n🤖 This chat — instant answers, anytime\n📞 **8406043847** — personal support from our team\n\nHave a great day!",
      priority: 8
    },
    {
      tags: ["help", "options", "menu", "what can you do", "what can ask"],
      answer: "**Here's everything I can help you with:**\n\n🔹 **\"How does the platform work?\"** — Full process flow explained\n🔹 **\"What are the features?\"** — Complete feature list\n🔹 **\"How do I get started?\"** — Step-by-step setup guide\n🔹 **\"How do I add teachers/rooms/courses?\"** — Specific setup help\n🔹 **\"How does the AI algorithm work?\"** — Technical deep-dive\n🔹 **\"Why should I choose SmartScheduler?\"** — Benefits & comparison\n🔹 **\"What is the pricing?\"** — Plans and quotes\n🔹 **\"Who built SmartScheduler?\"** — Meet the team\n🔹 **\"How can I join?\"** — Careers & openings\n🔹 **\"I'm facing an issue\"** — Troubleshooting help\n🔹 **\"What's the helpline?\"** — Contact info\n\nJust type naturally — I understand questions in plain English! 🎯",
      priority: 2
    },
    {
      tags: ["human", "real person", "talk someone", "agent", "operator", "representative"],
      answer: "I'm SmartScheduler's automated assistant — I can answer most questions instantly. But if you need human help:\n\n📞 **Call our helpline: 8406043847**\n\nYou'll reach one of our founders directly:\n• **Sanjeevan**\n• **Ishaanvi**\n• **Tushar**\n• **Pramod**\n\nThey can help with setup, customization, technical issues, pricing, and anything else you need!",
      priority: 5
    },
  ];

  // ── SMART MATCHING ENGINE ───────────────────────────────────
  // 1. Merge compound words ("time table" → "timetable")
  // 2. Strip stop words from user query
  // 3. Extract meaningful keywords
  // 4. Match against KB tags — cap score per tag to prevent one word dominating
  // 5. Priority boosts the final score

  // Compound words to merge before matching
  var COMPOUND_WORDS = {
    "time table": "timetable",
    "time tables": "timetables",
    "timetable": "timetable",
    "class room": "classroom",
    "work load": "workload",
    "work flow": "workflow",
    "data base": "database",
    "lab category": "labcategory",
    "meeting time": "meetingtime",
    "time slot": "timeslot",
    "sign up": "signup",
    "log in": "login",
    "log out": "logout"
  };

  function normalize(str) {
    return str
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function mergeCompounds(text) {
    var result = text;
    for (var phrase in COMPOUND_WORDS) {
      if (result.includes(phrase)) {
        result = result.replace(new RegExp(phrase, "g"), COMPOUND_WORDS[phrase]);
      }
    }
    return result;
  }

  function extractKeywords(text) {
    var merged = mergeCompounds(normalize(text));
    var words = merged.split(" ");
    // Filter out stop words, keep meaningful words (2+ chars)
    var meaningful = [];
    for (var i = 0; i < words.length; i++) {
      if (words[i].length >= 2 && !STOP_WORDS.has(words[i])) {
        meaningful.push(words[i]);
      }
    }
    // If ALL words were stop words, return original words (fallback)
    if (meaningful.length === 0) {
      return words.filter(function(w) { return w.length >= 2; });
    }
    return meaningful;
  }

  function findBestAnswer(query) {
    var qNorm = mergeCompounds(normalize(query));
    var qKeywords = extractKeywords(query);
    var bestScore = 0;
    var bestEntry = null;

    for (var i = 0; i < KB.length; i++) {
      var entry = KB[i];
      var score = 0;

      // Track which query keywords have been matched to avoid
      // the same keyword inflating score across many tags
      var matchedQWords = {};

      for (var t = 0; t < entry.tags.length; t++) {
        var tag = normalize(entry.tags[t]);
        var tagWords = tag.split(" ");

        // ── Check 1: Full query contains the full tag (multi-word tags) ──
        if (tag.length > 3 && tag.includes(" ") && qNorm.includes(tag)) {
          score += 30 + tag.length * 2;
          // Mark all tag words as matched
          for (var m = 0; m < tagWords.length; m++) {
            matchedQWords[tagWords[m]] = true;
          }
          continue;
        }

        // ── Check 2: Keyword-level matching ──
        // Score this tag, but cap contribution per tag
        var tagScore = 0;
        for (var tw = 0; tw < tagWords.length; tw++) {
          if (tagWords[tw].length < 2) continue;
          for (var qw = 0; qw < qKeywords.length; qw++) {
            if (qKeywords[qw].length < 2) continue;

            // Exact word match
            if (qKeywords[qw] === tagWords[tw]) {
              tagScore += 10;
              matchedQWords[qKeywords[qw]] = true;
            }
            // Substring/stem match (e.g., "generating" ↔ "generat")
            else if (qKeywords[qw].length >= 4 && tagWords[tw].length >= 4) {
              // Get shared root (first N chars)
              var shorter = qKeywords[qw].length < tagWords[tw].length ? qKeywords[qw] : tagWords[tw];
              var longer = qKeywords[qw].length >= tagWords[tw].length ? qKeywords[qw] : tagWords[tw];
              if (longer.includes(shorter)) {
                tagScore += 5;
                matchedQWords[qKeywords[qw]] = true;
              }
              // Also check stem match (first 5+ chars match)
              else if (shorter.length >= 5 && qKeywords[qw].substring(0, 5) === tagWords[tw].substring(0, 5)) {
                tagScore += 4;
                matchedQWords[qKeywords[qw]] = true;
              }
            }
          }
        }
        // Cap per-tag score to prevent one common word matching many tags
        score += Math.min(tagScore, 15);
      }

      // Bonus: how many unique query keywords matched? More = better relevance
      var uniqueMatches = Object.keys(matchedQWords).length;
      if (uniqueMatches > 1) {
        score += uniqueMatches * 5; // Reward queries where multiple keywords match
      }

      // Priority boost
      if (score > 0) {
        score += (entry.priority || 1) * 0.5;
      }

      if (score > bestScore) {
        bestScore = score;
        bestEntry = entry;
      }
    }

    // Minimum threshold
    if (bestScore < 5) {
      return "Hmm, I don't have a specific answer for that. I'm trained to answer questions about the **SmartScheduler platform** — here's what I know best:\n\n🔹 **\"How does the platform work?\"**\n🔹 **\"What features does it have?\"**\n🔹 **\"How do I get started?\"**\n🔹 **\"What is the pricing?\"**\n🔹 **\"Who built SmartScheduler?\"**\n🔹 **\"How can I join the team?\"**\n\nFor anything else, our team can help personally:\n📞 **Helpline: 8406043847** (Sanjeevan, Ishaanvi, Tushar & Pramod)";
    }

    return bestEntry.answer;
  }

  // ── CHATBOT UI ──────────────────────────────────────────────

  function createChatbotUI() {
    // Inject CSS
    var style = document.createElement("style");
    style.textContent = '\
      .scheduloai-chat-toggle {\
        position: fixed;\
        bottom: 28px;\
        right: 28px;\
        width: 60px;\
        height: 60px;\
        border-radius: 50%;\
        background: linear-gradient(135deg, #7c3aed, #4f46e5);\
        border: none;\
        cursor: pointer;\
        z-index: 99999;\
        display: flex;\
        align-items: center;\
        justify-content: center;\
        box-shadow: 0 6px 24px rgba(124, 58, 237, 0.45);\
        transition: transform 0.3s ease, box-shadow 0.3s ease;\
      }\
      .scheduloai-chat-toggle:hover {\
        transform: scale(1.1);\
        box-shadow: 0 8px 32px rgba(124, 58, 237, 0.6);\
      }\
      .scheduloai-chat-toggle svg {\
        width: 28px;\
        height: 28px;\
        fill: #fff;\
      }\
      .scheduloai-chat-toggle .close-icon { display: none; }\
      .scheduloai-chat-toggle.active .chat-icon { display: none; }\
      .scheduloai-chat-toggle.active .close-icon { display: block; }\
      .scheduloai-chat-toggle::before {\
        content: "";\
        position: absolute;\
        inset: -4px;\
        border-radius: 50%;\
        border: 2px solid rgba(124, 58, 237, 0.4);\
        animation: scheduloai-pulse 2s ease-in-out infinite;\
      }\
      .scheduloai-chat-toggle.active::before { animation: none; border-color: transparent; }\
      @keyframes scheduloai-pulse {\
        0%, 100% { transform: scale(1); opacity: 1; }\
        50% { transform: scale(1.25); opacity: 0; }\
      }\
      .scheduloai-chat-window {\
        position: fixed;\
        bottom: 100px;\
        right: 28px;\
        width: 400px;\
        max-width: calc(100vw - 32px);\
        height: 560px;\
        max-height: calc(100vh - 140px);\
        background: #0f0f1a;\
        border: 1px solid rgba(124, 58, 237, 0.25);\
        border-radius: 20px;\
        z-index: 99998;\
        display: flex;\
        flex-direction: column;\
        overflow: hidden;\
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 40px rgba(124, 58, 237, 0.15);\
        opacity: 0;\
        transform: translateY(20px) scale(0.95);\
        pointer-events: none;\
        transition: opacity 0.3s ease, transform 0.3s ease;\
        font-family: "Poppins", sans-serif;\
      }\
      .scheduloai-chat-window.open {\
        opacity: 1;\
        transform: translateY(0) scale(1);\
        pointer-events: auto;\
      }\
      .scheduloai-chat-header {\
        padding: 18px 20px;\
        background: linear-gradient(135deg, rgba(124, 58, 237, 0.15), rgba(79, 70, 229, 0.1));\
        border-bottom: 1px solid rgba(124, 58, 237, 0.15);\
        display: flex;\
        align-items: center;\
        gap: 12px;\
        flex-shrink: 0;\
      }\
      .scheduloai-chat-avatar {\
        width: 36px;\
        height: 42px;\
        display: flex;\
        align-items: center;\
        justify-content: center;\
        flex-shrink: 0;\
        filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.5));\
      }\
      .scheduloai-chat-avatar svg {\
        width: 100%;\
        height: 100%;\
      }\
      .scheduloai-chat-header-info { flex: 1; }\
      .scheduloai-chat-header-title {\
        font-size: 15px;\
        font-weight: 600;\
        color: #f1f1f1;\
        line-height: 1.2;\
      }\
      .scheduloai-chat-header-subtitle {\
        font-size: 11px;\
        color: #94a3b8;\
        display: flex;\
        align-items: center;\
        gap: 5px;\
        margin-top: 2px;\
      }\
      .scheduloai-chat-header-subtitle .dot {\
        width: 7px;\
        height: 7px;\
        background: #22c55e;\
        border-radius: 50%;\
        animation: scheduloai-blink 1.5s infinite;\
      }\
      @keyframes scheduloai-blink {\
        0%, 100% { opacity: 1; }\
        50% { opacity: 0.4; }\
      }\
      .scheduloai-chat-messages {\
        flex: 1;\
        overflow-y: auto;\
        padding: 16px;\
        display: flex;\
        flex-direction: column;\
        gap: 12px;\
      }\
      .scheduloai-chat-messages::-webkit-scrollbar { width: 5px; }\
      .scheduloai-chat-messages::-webkit-scrollbar-track { background: transparent; }\
      .scheduloai-chat-messages::-webkit-scrollbar-thumb { background: rgba(124, 58, 237, 0.3); border-radius: 10px; }\
      .scheduloai-msg {\
        max-width: 85%;\
        padding: 12px 16px;\
        border-radius: 16px;\
        font-size: 13px;\
        line-height: 1.65;\
        color: #e2e8f0;\
        animation: scheduloai-msg-in 0.3s ease;\
        word-wrap: break-word;\
      }\
      @keyframes scheduloai-msg-in {\
        from { opacity: 0; transform: translateY(8px); }\
        to { opacity: 1; transform: translateY(0); }\
      }\
      .scheduloai-msg.bot {\
        align-self: flex-start;\
        background: rgba(124, 58, 237, 0.08);\
        border: 1px solid rgba(124, 58, 237, 0.15);\
        border-bottom-left-radius: 4px;\
      }\
      .scheduloai-msg.user {\
        align-self: flex-end;\
        background: linear-gradient(135deg, #7c3aed, #4f46e5);\
        color: #fff;\
        border-bottom-right-radius: 4px;\
      }\
      .scheduloai-msg.bot strong { color: #c4b5fd; font-weight: 600; }\
      .scheduloai-msg.bot code {\
        background: rgba(124, 58, 237, 0.15);\
        padding: 1px 5px;\
        border-radius: 4px;\
        font-size: 12px;\
      }\
      .scheduloai-quick-actions {\
        display: flex;\
        flex-wrap: wrap;\
        gap: 6px;\
        padding: 0 16px 8px;\
        flex-shrink: 0;\
      }\
      .scheduloai-quick-btn {\
        padding: 6px 14px;\
        border-radius: 20px;\
        border: 1px solid rgba(124, 58, 237, 0.25);\
        background: rgba(124, 58, 237, 0.06);\
        color: #c4b5fd;\
        font-size: 11.5px;\
        cursor: pointer;\
        transition: all 0.2s ease;\
        font-family: "Poppins", sans-serif;\
        white-space: nowrap;\
      }\
      .scheduloai-quick-btn:hover {\
        background: rgba(124, 58, 237, 0.18);\
        border-color: rgba(124, 58, 237, 0.5);\
        color: #e9d5ff;\
      }\
      .scheduloai-chat-input-area {\
        padding: 12px 16px 16px;\
        border-top: 1px solid rgba(124, 58, 237, 0.12);\
        display: flex;\
        gap: 8px;\
        align-items: center;\
        flex-shrink: 0;\
        background: rgba(15, 15, 26, 0.8);\
      }\
      .scheduloai-chat-input {\
        flex: 1;\
        padding: 11px 16px;\
        border-radius: 12px;\
        border: 1px solid rgba(124, 58, 237, 0.2);\
        background: rgba(30, 30, 50, 0.6);\
        color: #e2e8f0;\
        font-size: 13px;\
        font-family: "Poppins", sans-serif;\
        outline: none;\
        transition: border-color 0.2s ease;\
      }\
      .scheduloai-chat-input::placeholder { color: #64748b; }\
      .scheduloai-chat-input:focus { border-color: rgba(124, 58, 237, 0.5); }\
      .scheduloai-chat-send {\
        width: 42px;\
        height: 42px;\
        border-radius: 12px;\
        border: none;\
        background: linear-gradient(135deg, #7c3aed, #4f46e5);\
        cursor: pointer;\
        display: flex;\
        align-items: center;\
        justify-content: center;\
        flex-shrink: 0;\
        transition: transform 0.15s ease;\
      }\
      .scheduloai-chat-send:hover { transform: scale(1.08); }\
      .scheduloai-chat-send svg { width: 18px; height: 18px; fill: #fff; }\
      .scheduloai-typing {\
        display: flex;\
        gap: 4px;\
        padding: 10px 16px;\
        align-self: flex-start;\
      }\
      .scheduloai-typing span {\
        width: 7px;\
        height: 7px;\
        border-radius: 50%;\
        background: #7c3aed;\
        animation: scheduloai-typing-bounce 1.2s ease-in-out infinite;\
      }\
      .scheduloai-typing span:nth-child(2) { animation-delay: 0.15s; }\
      .scheduloai-typing span:nth-child(3) { animation-delay: 0.3s; }\
      @keyframes scheduloai-typing-bounce {\
        0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }\
        30% { transform: translateY(-6px); opacity: 1; }\
      }\
      @media (max-width: 480px) {\
        .scheduloai-chat-window {\
          bottom: 0; right: 0; left: 0;\
          width: 100%; max-width: 100%;\
          height: 100vh; max-height: 100vh;\
          border-radius: 0;\
        }\
        .scheduloai-chat-toggle { bottom: 16px; right: 16px; width: 52px; height: 52px; }\
      }\
    ';
    document.head.appendChild(style);

    // Toggle button
    var toggle = document.createElement("button");
    toggle.className = "scheduloai-chat-toggle";
    toggle.setAttribute("aria-label", "Open chat");
    toggle.innerHTML = '<svg class="chat-icon" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg><svg class="close-icon" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>';
    document.body.appendChild(toggle);

    // Chat window
    var win = document.createElement("div");
    win.className = "scheduloai-chat-window";
    win.innerHTML = '<div class="scheduloai-chat-header"><div class="scheduloai-chat-avatar"><svg viewBox="0 0 100 120" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="ssLgChat" x1="50" y1="0" x2="50" y2="120" gradientUnits="userSpaceOnUse"><stop stop-color="#38bdf8"/><stop offset=".5" stop-color="#0ea5e9"/><stop offset="1" stop-color="#0c3557"/></linearGradient></defs><path d="M50 2L8 42l14 50q28 20 56 0l14-50Z" fill="url(#ssLgChat)"/><path d="M50 36c13 17 13 37 0 52-13-15-13-35 0-52Z" fill="#081424" opacity=".85"/></svg></div><div class="scheduloai-chat-header-info"><div class="scheduloai-chat-header-title">SmartScheduler Assistant</div><div class="scheduloai-chat-header-subtitle"><span class="dot"></span> Online — Instant responses</div></div></div><div class="scheduloai-chat-messages" id="scheduloai-msgs"></div><div class="scheduloai-quick-actions" id="scheduloai-quick"></div><div class="scheduloai-chat-input-area"><input class="scheduloai-chat-input" id="scheduloai-input" type="text" placeholder="Ask me anything about SmartScheduler..." autocomplete="off" /><button class="scheduloai-chat-send" id="scheduloai-send" aria-label="Send"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button></div>';
    document.body.appendChild(win);

    var msgs = document.getElementById("scheduloai-msgs");
    var input = document.getElementById("scheduloai-input");
    var sendBtn = document.getElementById("scheduloai-send");
    var quickDiv = document.getElementById("scheduloai-quick");

    var quickQuestions = [
      "What is SmartScheduler?",
      "Features",
      "How to use?",
      "Why buy?",
      "Pricing",
      "Who built it?",
      "Helpline"
    ];

    function renderQuickActions() {
      quickDiv.innerHTML = "";
      quickQuestions.forEach(function (q) {
        var btn = document.createElement("button");
        btn.className = "scheduloai-quick-btn";
        btn.textContent = q;
        btn.addEventListener("click", function () {
          handleUserMessage(q);
        });
        quickDiv.appendChild(btn);
      });
    }

    function formatMessage(text) {
      return text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/`(.*?)`/g, "<code>$1</code>")
        .replace(/\n/g, "<br>");
    }

    function addMessage(text, sender) {
      var div = document.createElement("div");
      div.className = "scheduloai-msg " + sender;
      if (sender === "bot") {
        div.innerHTML = formatMessage(text);
      } else {
        div.textContent = text;
      }
      msgs.appendChild(div);
      msgs.scrollTop = msgs.scrollHeight;
    }

    function botReply(text) {
      var typing = document.createElement("div");
      typing.className = "scheduloai-typing";
      typing.innerHTML = "<span></span><span></span><span></span>";
      msgs.appendChild(typing);
      msgs.scrollTop = msgs.scrollHeight;

      setTimeout(function () {
        typing.remove();
        addMessage(text, "bot");
      }, 150);
    }

    function handleUserMessage(text) {
      if (!text.trim()) return;
      addMessage(text, "user");
      input.value = "";
      var answer = findBestAnswer(text);
      botReply(answer);
    }

    toggle.addEventListener("click", function () {
      toggle.classList.toggle("active");
      win.classList.toggle("open");
      if (win.classList.contains("open")) {
        input.focus();
      }
    });

    sendBtn.addEventListener("click", function () {
      handleUserMessage(input.value);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        handleUserMessage(input.value);
      }
    });

    renderQuickActions();
    setTimeout(function () {
      addMessage(
        "Hi there! 👋 I'm the **SmartScheduler Assistant**.\n\nI can help you with features, guides, pricing, technical details, and support.\n\nAsk me anything or tap a quick action below!\n\n📞 Helpline: **8406043847**",
        "bot"
      );
    }, 500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createChatbotUI);
  } else {
    createChatbotUI();
  }
})();
